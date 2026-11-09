
import asyncio
import json
import logging
import os
import uuid
import httpx

from contextlib import asynccontextmanager, suppress
from typing import Literal

import aio_pika
import asyncpg

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from auth import router as auth_router
from auth import (
    get_current_user,
    require_roles,
    authorize_websocket
)

import assistant


# ==========================================
# CONFIGURACOES
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-factory-api")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_DB = os.environ["POSTGRES_DB"]

EXCHANGE = "factory.topic"
QUEUE = os.getenv("WEBSOCKET_QUEUE", "q.telemetry.websocket")

latest_events = {}
latest_predictions = {}
websocket_clients = set()


# ==========================================
# BANCO DE DADOS
# ==========================================

async def list_devices(pool):
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                id,
                device_id,
                name,
                device_type,
                location,
                active,
                created_at
            FROM devices
            ORDER BY id
            """
        )

    return [dict(row) for row in rows]


async def list_alerts(pool, limit=50):
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                id,
                device_id,
                severity,
                title,
                description,
                health_percent,
                rul_cycles,
                status,
                detected_at,
                resolved_at
            FROM maintenance_alerts
            ORDER BY detected_at DESC
            LIMIT $1
            """,
            limit
        )

    return [dict(row) for row in rows]


async def list_commands(pool, limit=50):
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                id,
                event_id,
                device_id,
                action,
                status,
                requested_at,
                executed_at,
                error_message
            FROM command_history
            ORDER BY requested_at DESC
            LIMIT $1
            """,
            limit
        )

    return [dict(row) for row in rows]


# ==========================================
# PERSISTENCIA DOS ALERTAS
# ==========================================

async def save_prediction_alert(pool, event):
    payload = event["payload"]
    device_id = event["device_id"]

    severity = payload.get("maintenance_status")

    if severity not in (
        "healthy",
        "warning",
        "critical"
    ):
        raise ValueError(
            "Status de manutencao invalido"
        )

    health = float(payload["health_percent"])
    rul = float(payload["rul_cycles"])

    if not (0 <= health <= 100 and rul >= 0):
        raise ValueError(
            "Valores de previsao invalidos"
        )

    async with pool.acquire() as connection:
        async with connection.transaction():

            # Procura um alerta ainda ativo.
            existing = await connection.fetchrow(
                """
                SELECT id, severity, status
                FROM maintenance_alerts
                WHERE device_id = $1
                  AND status IN (
                      'open',
                      'acknowledged'
                  )
                ORDER BY detected_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                device_id
            )

            if severity == "healthy":

                if existing:
                    await connection.execute(
                        """
                        UPDATE maintenance_alerts
                        SET status = 'resolved',
                            resolved_at = NOW()
                        WHERE device_id = $1
                          AND status IN (
                              'open',
                              'acknowledged'
                          )
                        """,
                        device_id
                    )

                    logger.info(
                        "Alertas resolvidos: %s",
                        device_id
                    )

                return

            # Se ja ha alerta da mesma gravidade,
            # evita criar outro a cada 3 segundos.
            if (
                existing
                and existing["severity"] == severity
            ):
                return

            # Se a gravidade mudou, encerra
            # o alerta anterior antes de criar outro.
            if existing:
                await connection.execute(
                    """
                    UPDATE maintenance_alerts
                    SET status = 'resolved',
                        resolved_at = NOW()
                    WHERE device_id = $1
                      AND status IN (
                          'open',
                          'acknowledged'
                      )
                    """,
                    device_id
                )

            if severity == "critical":
                title = "Manutencao critica do motor"
            else:
                title = "Atencao: manutencao preventiva"

            description = (
                f"Previsao sintetica: saude "
                f"{health:.2f}%, RUL "
                f"{rul:.2f} ciclos."
            )

            await connection.execute(
                """
                INSERT INTO maintenance_alerts (
                    device_id,
                    severity,
                    title,
                    description,
                    health_percent,
                    rul_cycles,
                    status
                )
                VALUES (
                    $1, $2, $3, $4,
                    $5, $6, 'open'
                )
                """,
                device_id,
                severity,
                title,
                description,
                health,
                rul
            )

            logger.warning(
                "Alerta registrado | %s | %s",
                device_id,
                severity
            )


# ==========================================
# WEBSOCKET
# ==========================================

async def broadcast(event):
    disconnected = []

    for websocket in list(websocket_clients):
        try:
            await websocket.send_json(event)
        except Exception:
            disconnected.append(websocket)

    for websocket in disconnected:
        websocket_clients.discard(websocket)


# ==========================================
# EVENTOS DO RABBITMQ
# ==========================================

async def process_event(message):
    async with message.process(requeue=True):

        try:
            event = json.loads(
                message.body.decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError):
            logger.warning("JSON invalido recebido")
            return

        if not isinstance(event, dict):
            logger.warning("Evento invalido")
            return

        device_id = event.get("device_id")
        event_type = event.get("type")
        payload = event.get("payload")

        if not isinstance(device_id, str):
            logger.warning("Evento sem device_id")
            return

        if not isinstance(payload, dict):
            logger.warning("Payload invalido")
            return

        if event_type not in (
            "telemetry",
            "state",
            "prediction"
        ):
            logger.warning(
                "Tipo desconhecido: %s",
                event_type
            )
            return

        if event_type == "prediction":

            previous = latest_predictions.get(
                device_id
            )

            if (
                previous
                and event.get("timestamp", "")
                < previous.get("timestamp", "")
            ):
                return

            try:
                # Primeiro grava no banco.
                # Depois disponibiliza a previsao
                # para o dashboard.
                await save_prediction_alert(
                    app.state.db_pool,
                    event
                )
            except (ValueError, KeyError, TypeError):
                logger.warning(
                    "Previsao invalida: %s",
                    device_id
                )
                return

            latest_predictions[device_id] = event

            logger.info(
                "IA recebida | %s | "
                "RUL: %s | Saude: %s%%",
                device_id,
                payload.get("rul_cycles"),
                payload.get("health_percent")
            )

        else:
            previous = latest_events.get(
                device_id
            )

            if (
                previous
                and event.get("timestamp", "")
                < previous.get("timestamp", "")
            ):
                return

            latest_events[device_id] = event

        if websocket_clients:
            await broadcast(event)


# ==========================================
# INICIALIZACAO DA APLICACAO
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Conectando ao PostgreSQL...")

    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        min_size=1,
        max_size=5
    )

    app.state.db_pool = pool

    logger.info("PostgreSQL conectado!")

    # Baixa (se preciso) e pre-carrega o LLM local
    # em segundo plano, sem travar a API.
    llm_task = asyncio.create_task(
        assistant.prepare_model()
    )

    connection = None

    try:
        connection = await aio_pika.connect_robust(
            host=RABBITMQ_HOST,
            login=RABBITMQ_USER,
            password=RABBITMQ_PASSWORD,
            heartbeat=60
        )

        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True
        )

        await channel.set_qos(
            prefetch_count=50
        )

        exchange = await channel.declare_exchange(
            EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True
        )

        queue = await channel.declare_queue(
            QUEUE,
            durable=True
        )

        for routing_key in (
            "telemetry.#",
            "state.#",
            "prediction.#"
        ):
            await queue.bind(
                exchange,
                routing_key=routing_key
            )

        await queue.consume(
            process_event
        )

        app.state.connection = connection
        app.state.channel = channel
        app.state.exchange = exchange

        logger.info("RabbitMQ conectado!")
        logger.info(
            "API pronta: PostgreSQL + RabbitMQ + IA"
        )

        yield

    finally:
        llm_task.cancel()

        with suppress(asyncio.CancelledError):
            await llm_task

        if connection:
            await connection.close()

        await pool.close()


# ==========================================
# FASTAPI
# ==========================================

app = FastAPI(
    title="Smart Factory AIoT",
    version="0.3.0",
    description=(
        "API industrial com MQTT, RabbitMQ, "
        "PostgreSQL e manutencao preditiva"
    ),
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=[
        "Content-Type",
        "Authorization"
    ]
)

# ==========================================
# AUTENTICACAO
# ==========================================

app.include_router(auth_router)

class ConveyorCommand(BaseModel):
    action: Literal["ON", "OFF"]


class MotorCommand(BaseModel):
    action: Literal["INJECT_FAULT", "MAINTENANCE"]


class AssistantQuestion(BaseModel):
    question: str = Field(
        min_length=2,
        max_length=500
    )


# ==========================================
# ROTAS PRINCIPAIS
# ==========================================

@app.get("/")
async def home():
    return {
        "name": "Smart Factory AIoT",
        "status": "online",
        "database": "postgresql",
        "ai_enabled": True,
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    rabbit_connected = (
        hasattr(app.state, "connection")
        and not app.state.connection.is_closed
    )

    if not rabbit_connected:
        raise HTTPException(
            503,
            "RabbitMQ desconectado"
        )

    try:
        async with app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        raise HTTPException(
            503,
            "PostgreSQL indisponivel"
        )

    return {
        "status": "ok",
        "rabbitmq": "connected",
        "postgresql": "connected"
    }


@app.get("/api/factory/state")
async def factory_state():
    return {
        "devices": latest_events,
        "predictions": latest_predictions,
        "total_devices": len(latest_events)
    }


# ==========================================
# ROTAS POSTGRESQL
# ==========================================

@app.get(
    "/api/devices",
    dependencies=[Depends(get_current_user)]
)
async def get_devices():
    result = await list_devices(
        app.state.db_pool
    )

    return {
        "devices": result,
        "total": len(result)
    }


@app.get("/api/alerts")
async def get_alerts():
    result = await list_alerts(
        app.state.db_pool
    )

    return {
        "alerts": result,
        "total": len(result)
    }


@app.get("/api/commands/history")
async def get_commands():
    result = await list_commands(
        app.state.db_pool
    )

    return {
        "commands": result,
        "total": len(result)
    }


# ==========================================
# ROTAS DA IA
# ==========================================

@app.get("/api/ai/predictions")
async def ai_predictions():
    return {
        "predictions": latest_predictions,
        "total": len(latest_predictions)
    }


@app.get("/api/ai/predictions/{device_id}")
async def ai_prediction_device(device_id: str):
    prediction = latest_predictions.get(
        device_id
    )

    if prediction is None:
        raise HTTPException(
            404,
            "Previsao nao encontrada"
        )

    return prediction


# ==========================================
# COMANDO DA ESTEIRA + POSTGRESQL
# ==========================================

async def send_device_command(device_id, action):
    """Registra o comando no PostgreSQL e o publica
    no RabbitMQ; o command-gateway leva ao MQTT."""

    event_id = uuid.uuid4()

    event = {
        "event_id": str(event_id),
        "device_id": device_id,
        "type": "command",
        "payload": {
            "action": action
        }
    }

    # Registra a tentativa de comando.
    try:
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_history (
                    event_id,
                    device_id,
                    action,
                    status
                )
                VALUES ($1, $2, $3, 'queued')
                """,
                event_id,
                device_id,
                action
            )

    except Exception:
        logger.exception(
            "Falha ao registrar comando no PostgreSQL"
        )

        raise HTTPException(
            503,
            "Nao foi possivel registrar o comando"
        )

    # Encaminha o comando ao RabbitMQ.
    try:
        await app.state.channel.ready()

        await app.state.exchange.publish(
            aio_pika.Message(
                body=json.dumps(
                    event
                ).encode("utf-8"),
                delivery_mode=(
                    aio_pika.DeliveryMode.PERSISTENT
                ),
                content_type="application/json",
                message_id=str(event_id)
            ),
            routing_key=(
                f"command.factory.actuator.{device_id}"
            ),
            mandatory=True
        )

    except Exception as error:
        logger.exception(
            "Falha ao publicar comando"
        )

        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE command_history
                SET status = 'failed',
                    error_message = $2
                WHERE event_id = $1
                """,
                event_id,
                str(error)[:1000]
            )

        raise HTTPException(
            503,
            "Nao foi possivel encaminhar o comando"
        )

    logger.info(
        "Comando registrado | %s | %s | %s",
        event_id,
        device_id,
        action
    )

    return {
        "status": "queued",
        "action": action,
        "event_id": str(event_id)
    }


@app.post(
    "/api/conveyor/command",
    dependencies=[
        Depends(require_roles("admin", "operator"))
    ]
)
async def conveyor_command(
    command: ConveyorCommand
):
    return await send_device_command(
        "conveyor-01",
        command.action
    )


# Demonstracao de manutencao preditiva:
# INJECT_FAULT acelera o desgaste do motor no simulador;
# MAINTENANCE zera o desgaste e encerra a falha.
@app.post(
    "/api/motor/command",
    dependencies=[
        Depends(require_roles("admin", "operator"))
    ]
)
async def motor_command(
    command: MotorCommand
):
    return await send_device_command(
        "motor-01",
        command.action
    )


# ==========================================
# ASSISTENTE COM LLM LOCAL
# ==========================================

@app.get(
    "/api/assistant/status",
    dependencies=[Depends(get_current_user)],
    tags=["Assistente"]
)
async def assistant_status():
    return assistant.status


@app.post(
    "/api/assistant/chat",
    tags=["Assistente"]
)
async def assistant_chat(
    body: AssistantQuestion,
    user=Depends(get_current_user)
):
    if not assistant.is_ready():
        raise HTTPException(
            503,
            "O modelo ainda esta carregando"
        )

    # Limite de perguntas por minuto, por usuario.
    username = user["username"]

    if not assistant.allow_request(username):
        raise HTTPException(
            429,
            "Limite de perguntas por minuto atingido"
        )

    question = body.question.strip()
    pool = app.state.db_pool

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_logs (
                    action,
                    entity_type,
                    details
                )
                VALUES (
                    'assistant_question',
                    'assistant',
                    $1::jsonb
                )
                """,
                json.dumps({
                    "question": question,
                    "username": username,
                    "role": user["role"],
                    "model": assistant.OLLAMA_MODEL
                })
            )

        devices = await list_devices(pool)
        alerts = await list_alerts(pool)

    except Exception:
        logger.exception(
            "Falha ao preparar pergunta do assistente"
        )
        raise HTTPException(
            503,
            "PostgreSQL indisponivel"
        )

    context = assistant.build_context(
        latest_events,
        latest_predictions,
        alerts,
        devices
    )

    return StreamingResponse(
        assistant.stream_answer(context, question),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ==========================================
# WEBSOCKET
# ==========================================

@app.websocket("/ws/factory")
async def factory_websocket(
    websocket: WebSocket
):
    if not await authorize_websocket(websocket):
        return

    await websocket.accept()
    websocket_clients.add(websocket)

    try:
        await websocket.send_json({
            "type": "snapshot",
            "devices": latest_events,
            "predictions": latest_predictions
        })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    finally:
        websocket_clients.discard(
            websocket
        )


# ==========================================
# MENSAGERIA - RABBITMQ
# ==========================================

@app.get(
    "/api/messaging/queues",
    dependencies=[Depends(get_current_user)],
    tags=["Mensageria"]
)
async def get_messaging_queues():

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "http://rabbitmq:15672/api/queues/%2F",
                auth=(
                    RABBITMQ_USER,
                    RABBITMQ_PASSWORD
                )
            )

            response.raise_for_status()
            queues_data = response.json()

    except (httpx.HTTPError, ValueError):
        logger.exception(
            "Falha ao consultar RabbitMQ Management"
        )

        raise HTTPException(
            status_code=503,
            detail="Nao foi possivel consultar as filas"
        )

    queues = []

    for queue in queues_data:
        queues.append({
            "name": queue.get("name"),
            "state": queue.get("state", "unknown"),
            "messages": queue.get("messages", 0),
            "messages_ready": queue.get(
                "messages_ready", 0
            ),
            "messages_unacknowledged": queue.get(
                "messages_unacknowledged", 0
            ),
            "consumers": queue.get("consumers", 0)
        })

    queues.sort(key=lambda item: item["name"] or "")

    return {
        "total": len(queues),
        "queues": queues
    }
