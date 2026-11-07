
import json
import logging
import os
import uuid

from contextlib import asynccontextmanager
from typing import Literal

import aio_pika

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ==========================================
# CONFIGURACOES
# ==========================================

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("smart-factory-api")

RABBITMQ_HOST = os.getenv(
    "RABBITMQ_HOST",
    "rabbitmq"
)

RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

EXCHANGE = "factory.topic"
QUEUE = "q.telemetry.websocket"


# ==========================================
# ESTADO ATUAL DA FABRICA
# ==========================================

latest_events = {}
latest_predictions = {}

websocket_clients = set()


# ==========================================
# ENVIO EM TEMPO REAL
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
# PROCESSAMENTO DE EVENTOS
# ==========================================

async def process_event(message):
    async with message.process():
        try:
            event = json.loads(
                message.body.decode("utf-8")
            )

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

                latest_predictions[device_id] = event

                logger.info(
                    "Previsao recebida | %s | "
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

        except (
            ValueError,
            UnicodeDecodeError,
            TypeError
        ) as error:
            logger.warning(
                "Mensagem invalida: %s",
                error
            )


# ==========================================
# INICIALIZACAO DO RABBITMQ
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
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

    await channel.set_qos(prefetch_count=50)

    exchange = await channel.declare_exchange(
        EXCHANGE,
        aio_pika.ExchangeType.TOPIC,
        durable=True
    )

    queue = await channel.declare_queue(
        QUEUE,
        durable=True
    )

    # Leituras dos sensores.
    await queue.bind(
        exchange,
        routing_key="telemetry.#"
    )

    # Estados dos equipamentos.
    await queue.bind(
        exchange,
        routing_key="state.#"
    )

    # Previsoes produzidas pela IA.
    await queue.bind(
        exchange,
        routing_key="prediction.#"
    )

    await queue.consume(process_event)

    app.state.connection = connection
    app.state.channel = channel
    app.state.exchange = exchange

    logger.info("API conectada ao RabbitMQ")
    logger.info("Consumindo %s", QUEUE)
    logger.info(
        "Telemetria, estados e previsoes habilitados"
    )

    try:
        yield

    finally:
        await connection.close()


# ==========================================
# FASTAPI
# ==========================================

app = FastAPI(
    title="Smart Factory AIoT",
    version="0.2.0",
    description=(
        "API da fabrica inteligente com "
        "manutencao preditiva"
    ),
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"]
)


class ConveyorCommand(BaseModel):
    action: Literal["ON", "OFF"]


# ==========================================
# ROTAS REST
# ==========================================

@app.get("/")
async def home():
    return {
        "name": "Smart Factory AIoT",
        "status": "online",
        "docs": "/docs",
        "ai_enabled": True
    }


@app.get("/health")
async def health():
    connected = (
        hasattr(app.state, "connection")
        and not app.state.connection.is_closed
    )

    if not connected:
        raise HTTPException(
            503,
            "RabbitMQ desconectado"
        )

    return {
        "status": "ok",
        "rabbitmq": "connected"
    }


@app.get("/api/factory/state")
async def factory_state():
    return {
        "devices": latest_events,
        "predictions": latest_predictions,
        "total_devices": len(latest_events)
    }


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
            status_code=404,
            detail="Previsao nao encontrada"
        )

    return prediction


# ==========================================
# COMANDO DA ESTEIRA
# ==========================================

@app.post("/api/conveyor/command")
async def conveyor_command(
    command: ConveyorCommand
):
    event = {
        "event_id": str(uuid.uuid4()),
        "device_id": "conveyor-01",
        "type": "command",
        "payload": {
            "action": command.action
        }
    }

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
                message_id=event["event_id"]
            ),
            routing_key=(
                "command.factory.actuator.conveyor-01"
            ),
            mandatory=True
        )

    except Exception:
        logger.exception(
            "Erro ao publicar comando"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Nao foi possivel encaminhar "
                "o comando"
            )
        )

    return {
        "status": "queued",
        "action": command.action,
        "event_id": event["event_id"]
    }


# ==========================================
# WEBSOCKET
# ==========================================

@app.websocket("/ws/factory")
async def factory_websocket(
    websocket: WebSocket
):
    await websocket.accept()

    websocket_clients.add(websocket)

    try:
        # Envia estado completo para quem
        # acabou de abrir o dashboard.
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
