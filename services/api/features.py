"""
Rotas das telas de Treinamento, Insights, Historico,
Dispositivos e Laboratorio de Dados (jobs de IA).

- Treinamento: le ai/models/metadata.json (montado so leitura).
- Insights: historico recente das previsoes (memoria) + alertas.
- Historico: consulta o InfluxDB pela API HTTP (Flux).
- Dispositivos: cadastro no PostgreSQL, com auditoria.
- Jobs: a API registra o job e publica no RabbitMQ
  (job.generate / job.train); o worker ai-jobs executa e
  devolve o andamento em eventos job.status.*.
"""

import csv
import io
import json
import logging
import os
import re
import uuid

from collections import deque
from pathlib import Path
from typing import Literal

import aio_pika
import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import get_current_user, require_roles


logger = logging.getLogger("smart-factory-features")

router = APIRouter()

MODEL_DIR = Path(os.getenv("MODEL_DIR", "/app/models"))

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "")

JOB_QUEUES = {
    "generate": "q.jobs.generate",
    "train": "q.jobs.train",
}

# Ultimas previsoes por motor (cerca de 1 hora a cada 3 s).
prediction_history = {}
PREDICTION_HISTORY_SIZE = 1200


def record_prediction(event):
    device_id = event.get("device_id")
    payload = event.get("payload", {})

    history = prediction_history.setdefault(
        device_id,
        deque(maxlen=PREDICTION_HISTORY_SIZE)
    )

    history.append({
        "timestamp": event.get("timestamp"),
        "health_percent": payload.get("health_percent"),
        "rul_cycles": payload.get("rul_cycles"),
        "maintenance_status": payload.get("maintenance_status"),
        "model_version": payload.get("model_version"),
    })


async def audit(pool, user, action, entity_type, entity_id, details):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs (
                action, entity_type, entity_id, details
            )
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            action,
            entity_type,
            entity_id,
            json.dumps({
                **details,
                "username": user["username"],
                "role": user["role"],
            })
        )


# ==========================================
# TREINAMENTO: MODELO EM USO
# ==========================================

def _read_importance(name):
    path = MODEL_DIR / f"{name}_importance.csv"

    try:
        with path.open(encoding="utf-8") as file:
            return [
                {
                    "feature": row["feature"],
                    "importance": float(row["importance"]),
                }
                for row in csv.DictReader(file)
            ]
    except (OSError, KeyError, ValueError):
        return []


@router.get(
    "/api/model/info",
    dependencies=[Depends(get_current_user)],
    tags=["Treinamento"]
)
async def model_info():
    try:
        metadata = json.loads(
            (MODEL_DIR / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        raise HTTPException(
            404,
            "Nenhum modelo treinado encontrado"
        )

    for name, info in metadata.get("targets", {}).items():
        if "importance" not in info:
            info["importance"] = _read_importance(name)

    return metadata


# ==========================================
# INSIGHTS
# ==========================================

@router.get(
    "/api/insights",
    dependencies=[Depends(get_current_user)],
    tags=["Insights"]
)
async def insights(request: Request, device_id: str = "motor-01"):
    pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        alerts = await conn.fetch(
            """
            SELECT id, device_id, severity, title, description,
                   health_percent, rul_cycles, status,
                   detected_at, resolved_at
            FROM maintenance_alerts
            WHERE device_id = $1
            ORDER BY detected_at DESC
            LIMIT 30
            """,
            device_id
        )

        counts = await conn.fetch(
            """
            SELECT severity, status, COUNT(*) AS total
            FROM maintenance_alerts
            WHERE device_id = $1
            GROUP BY severity, status
            """,
            device_id
        )

        commands = await conn.fetch(
            """
            SELECT action, status, requested_at
            FROM command_history
            WHERE device_id = $1
            ORDER BY requested_at DESC
            LIMIT 10
            """,
            device_id
        )

    history = list(prediction_history.get(device_id, []))

    return {
        "device_id": device_id,
        "history": history,
        "alerts": [dict(row) for row in alerts],
        "alert_counts": [dict(row) for row in counts],
        "commands": [dict(row) for row in commands],
    }


# ==========================================
# HISTORICO (INFLUXDB)
# ==========================================

HISTORY_FIELDS = {
    "motor-01": [
        "temperature_c",
        "vibration_mm_s",
        "current_a",
    ],
    "environment-01": [
        "temperature_c",
        "humidity_percent",
    ],
}

RANGES = {
    "15m": ("-15m", "15s"),
    "1h": ("-1h", "1m"),
    "6h": ("-6h", "5m"),
    "24h": ("-24h", "15m"),
}


@router.get(
    "/api/history",
    dependencies=[Depends(get_current_user)],
    tags=["Historico"]
)
async def telemetry_history(
    device_id: Literal["motor-01", "environment-01"] = "motor-01",
    period: Literal["15m", "1h", "6h", "24h"] = "1h"
):
    start, window = RANGES[period]
    fields = HISTORY_FIELDS[device_id]

    field_filter = " or ".join(
        f'r._field == "{field}"' for field in fields
    )

    # Valores vem de listas fixas acima: sem entrada livre
    # do usuario dentro da consulta Flux.
    flux = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {start})
  |> filter(fn: (r) => r._measurement == "sensor_readings")
  |> filter(fn: (r) => r.device_id == "{device_id}")
  |> filter(fn: (r) => {field_filter})
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["_time", {", ".join(f'"{f}"' for f in fields)}])
  |> sort(columns: ["_time"])
'''

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{INFLUXDB_URL}/api/v2/query",
                params={"org": INFLUXDB_ORG},
                headers={
                    "Authorization": f"Token {INFLUXDB_TOKEN}",
                    "Content-Type": "application/vnd.flux",
                    "Accept": "application/csv",
                },
                content=flux
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Falha ao consultar o InfluxDB")
        raise HTTPException(503, "InfluxDB indisponivel")

    points = []

    for row in csv.DictReader(io.StringIO(response.text)):
        if not row.get("_time"):
            continue

        point = {"time": row["_time"]}

        for field in fields:
            value = row.get(field)
            point[field] = (
                round(float(value), 2) if value not in (None, "") else None
            )

        points.append(point)

    return {
        "device_id": device_id,
        "period": period,
        "fields": fields,
        "points": points,
    }


# ==========================================
# DISPOSITIVOS (CADASTRO)
# ==========================================

DEVICE_TYPES = Literal[
    "motor",
    "environment_sensor",
    "conveyor",
    "fan",
    "sensor",
    "actuator",
]


class DeviceCreate(BaseModel):
    device_id: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    name: str = Field(min_length=3, max_length=100)
    device_type: DEVICE_TYPES
    location: str = Field(min_length=2, max_length=100)


class DeviceUpdate(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    device_type: DEVICE_TYPES
    location: str = Field(min_length=2, max_length=100)
    active: bool


DEVICE_COLUMNS = """
    id, device_id, name, device_type, location, active, created_at
"""


@router.post(
    "/api/devices",
    status_code=201,
    tags=["Dispositivos"]
)
async def create_device(
    body: DeviceCreate,
    request: Request,
    user=Depends(require_roles("admin"))
):
    pool = request.app.state.db_pool

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                INSERT INTO devices (
                    device_id, name, device_type, location
                )
                VALUES ($1, $2, $3, $4)
                RETURNING {DEVICE_COLUMNS}
                """,
                body.device_id,
                body.name,
                body.device_type,
                body.location
            )
    except Exception as error:
        if "unique" in str(error).lower():
            raise HTTPException(409, "Ja existe um dispositivo com esse ID")
        logger.exception("Falha ao cadastrar dispositivo")
        raise HTTPException(400, "Nao foi possivel cadastrar o dispositivo")

    await audit(
        pool, user, "device_created", "device",
        body.device_id, body.model_dump()
    )

    return dict(row)


@router.put(
    "/api/devices/{device_id}",
    tags=["Dispositivos"]
)
async def update_device(
    device_id: str,
    body: DeviceUpdate,
    request: Request,
    user=Depends(require_roles("admin"))
):
    pool = request.app.state.db_pool

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE devices
                SET name = $2,
                    device_type = $3,
                    location = $4,
                    active = $5
                WHERE device_id = $1
                RETURNING {DEVICE_COLUMNS}
                """,
                device_id,
                body.name,
                body.device_type,
                body.location,
                body.active
            )
    except Exception:
        logger.exception("Falha ao atualizar dispositivo")
        raise HTTPException(400, "Nao foi possivel atualizar o dispositivo")

    if row is None:
        raise HTTPException(404, "Dispositivo nao encontrado")

    await audit(
        pool, user, "device_updated", "device",
        device_id, body.model_dump()
    )

    return dict(row)


@router.delete(
    "/api/devices/{device_id}",
    tags=["Dispositivos"]
)
async def delete_device(
    device_id: str,
    request: Request,
    user=Depends(require_roles("admin"))
):
    pool = request.app.state.db_pool

    try:
        async with pool.acquire() as conn:
            deleted = await conn.fetchval(
                "DELETE FROM devices WHERE device_id = $1 RETURNING id",
                device_id
            )
    except Exception as error:
        # Dispositivo com historico (alertas, comandos) nao
        # pode ser apagado: a interface sugere desativar.
        if "foreign key" in str(error).lower():
            raise HTTPException(
                409,
                "Dispositivo possui historico; desative-o em vez de excluir"
            )
        logger.exception("Falha ao excluir dispositivo")
        raise HTTPException(400, "Nao foi possivel excluir o dispositivo")

    if deleted is None:
        raise HTTPException(404, "Dispositivo nao encontrado")

    await audit(pool, user, "device_deleted", "device", device_id, {})

    return {"deleted": device_id}


# ==========================================
# LABORATORIO DE DADOS E TREINAMENTO (JOBS)
# ==========================================

FAILURE_MODES = Literal["geral", "rolamento", "superaquecimento", "eletrica"]


class GenerateJob(BaseModel):
    motors: int = Field(default=200, ge=10, le=400)
    cycles: int = Field(default=5000, ge=500, le=8000)
    seed: int = Field(default=42, ge=0, le=999999)
    failure_rate: float = Field(default=70, ge=0, le=100)
    failure_modes: list[FAILURE_MODES] = Field(
        default=["geral"], min_length=1, max_length=4
    )
    noise: float = Field(default=1.0, ge=0, le=3)
    missing_percent: float = Field(default=0, ge=0, le=20)
    outlier_percent: float = Field(default=0.8, ge=0, le=10)
    days: int = Field(default=30, ge=1, le=365)


class TrainJob(BaseModel):
    max_iter: int = Field(default=120, ge=20, le=400)
    learning_rate: float = Field(default=0.08, ge=0.01, le=0.5)
    max_leaf_nodes: int = Field(default=20, ge=8, le=64)
    train_rows: int = Field(default=160000, ge=20000, le=400000)
    window_features: bool = True


JOB_COLUMNS = """
    id, job_type, status, progress, params, message, log_tail,
    result, requested_by, created_at, started_at, finished_at
"""


def _job_row(row):
    job = dict(row)
    for key in ("params", "result"):
        if isinstance(job.get(key), str):
            job[key] = json.loads(job[key])
    return job


async def _create_job(request, user, job_type, params):
    pool = request.app.state.db_pool
    job_id = uuid.uuid4()

    async with pool.acquire() as conn:
        running = await conn.fetchval(
            """
            SELECT COUNT(*) FROM ai_jobs
            WHERE status IN ('queued', 'running')
            """
        )

        if running >= 3:
            raise HTTPException(
                429,
                "Ja existem jobs na fila; aguarde terminarem"
            )

        row = await conn.fetchrow(
            f"""
            INSERT INTO ai_jobs (
                id, job_type, status, progress, params,
                message, requested_by
            )
            VALUES ($1, $2, 'queued', 0, $3::jsonb, 'Na fila', $4)
            RETURNING {JOB_COLUMNS}
            """,
            job_id,
            job_type,
            json.dumps(params),
            user["username"]
        )

    event = {
        "event_id": str(job_id),
        "job_id": str(job_id),
        "type": "job",
        "job_type": job_type,
        "params": params,
        "requested_by": user["username"],
    }

    try:
        await request.app.state.channel.ready()
        await request.app.state.exchange.publish(
            aio_pika.Message(
                body=json.dumps(event).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=str(job_id)
            ),
            routing_key=f"job.{job_type}",
            mandatory=True
        )
    except Exception as error:
        logger.exception("Falha ao publicar job")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ai_jobs
                SET status = 'failed', message = $2, finished_at = NOW()
                WHERE id = $1
                """,
                job_id,
                f"Falha ao publicar: {error}"[:500]
            )
        raise HTTPException(503, "Nao foi possivel enfileirar o job")

    await audit(
        pool, user, f"job_{job_type}_requested", "ai_job",
        str(job_id), params
    )

    return _job_row(row)


@router.post("/api/jobs/generate", status_code=202, tags=["Jobs de IA"])
async def request_generate(
    body: GenerateJob,
    request: Request,
    user=Depends(require_roles("admin", "operator"))
):
    return await _create_job(request, user, "generate", body.model_dump())


@router.post("/api/jobs/train", status_code=202, tags=["Jobs de IA"])
async def request_train(
    body: TrainJob,
    request: Request,
    user=Depends(require_roles("admin", "operator"))
):
    return await _create_job(request, user, "train", body.model_dump())


@router.get(
    "/api/jobs",
    dependencies=[Depends(get_current_user)],
    tags=["Jobs de IA"]
)
async def list_jobs(request: Request, limit: int = 20):
    limit = max(1, min(limit, 100))

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {JOB_COLUMNS}
            FROM ai_jobs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit
        )

    return {"jobs": [_job_row(row) for row in rows]}


JOB_STATUSES = ("queued", "running", "succeeded", "failed")
UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


async def handle_job_status(pool, event):
    """Evento job.status.* publicado pelo worker ai-jobs.
    Upsert: o job pode ter sido criado pela outra API
    (producao ou desenvolvimento), cada uma com seu banco."""

    job_id = str(event.get("job_id", ""))
    status = event.get("status")

    if not UUID_RE.match(job_id) or status not in JOB_STATUSES:
        raise ValueError("Evento de job invalido")

    progress = max(0, min(100, int(event.get("progress") or 0)))

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_jobs (
                id, job_type, status, progress, params, message,
                log_tail, result, requested_by, started_at, finished_at
            )
            VALUES (
                $1, $2, $3::text, $4, $5::jsonb, $6, $7, $8::jsonb, $9,
                CASE WHEN $3::text = 'running' THEN NOW() END,
                CASE WHEN $3::text IN ('succeeded', 'failed') THEN NOW() END
            )
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                progress = EXCLUDED.progress,
                message = EXCLUDED.message,
                log_tail = EXCLUDED.log_tail,
                result = COALESCE(EXCLUDED.result, ai_jobs.result),
                started_at = COALESCE(ai_jobs.started_at, EXCLUDED.started_at, NOW()),
                finished_at = EXCLUDED.finished_at
            -- Eventos podem chegar fora de ordem: um job concluido
            -- ou com falha nunca volta para "executando".
            WHERE ai_jobs.status NOT IN ('succeeded', 'failed')
            """,
            uuid.UUID(job_id),
            event.get("job_type", "generate"),
            status,
            progress,
            json.dumps(event.get("params") or {}),
            str(event.get("message") or "")[:500],
            str(event.get("log_tail") or "")[-4000:],
            json.dumps(event["result"]) if event.get("result") else None,
            str(event.get("requested_by") or "")[:80]
        )
