
import asyncio
import json
import logging
import os
import uuid

from contextlib import asynccontextmanager

import aio_pika

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-factory-api")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

EXCHANGE = "factory.topic"
QUEUE = "q.telemetry.websocket"

latest_events = {}
websocket_clients = set()


async def broadcast(event):
    disconnected = []

    for websocket in list(websocket_clients):
        try:
            await websocket.send_json(event)
        except Exception:
            disconnected.append(websocket)

    for websocket in disconnected:
        websocket_clients.discard(websocket)


async def process_event(message):
    async with message.process():
        try:
            event = json.loads(message.body.decode("utf-8"))

            device_id = event.get("device_id")
            event_type = event.get("type")

            if not isinstance(device_id, str):
                logger.warning("Evento sem device_id")
                return

            if event_type not in ("telemetry", "state"):
                logger.warning("Tipo desconhecido: %s", event_type)
                return

            if not isinstance(event.get("payload"), dict):
                logger.warning("Payload invalido")
                return

            previous = latest_events.get(device_id)
            if previous and event.get("timestamp", "") < previous.get("timestamp", ""):
                return

            latest_events[device_id] = event

            if websocket_clients:
                await broadcast(event)

        except (ValueError, UnicodeDecodeError) as error:
            logger.warning("Mensagem invalida: %s", error)


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

    await queue.bind(exchange, routing_key="telemetry.#")
    await queue.bind(exchange, routing_key="state.#")

    await queue.consume(process_event)

    app.state.connection = connection
    app.state.channel = channel
    app.state.exchange = exchange

    logger.info("API conectada ao RabbitMQ")
    logger.info("Consumindo %s", QUEUE)

    try:
        yield
    finally:
        await connection.close()


app = FastAPI(
    title="Smart Factory AIoT",
    version="0.1.0",
    description="API de monitoramento da fabrica inteligente",
    lifespan=lifespan
)

# Acesso local durante o desenvolvimento.
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


@app.get("/")
async def home():
    return {
        "name": "Smart Factory AIoT",
        "status": "online",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    connected = not app.state.connection.is_closed

    if not connected:
        raise HTTPException(503, "RabbitMQ desconectado")

    return {
        "status": "ok",
        "rabbitmq": "connected"
    }


@app.get("/api/factory/state")
async def factory_state():
    return {
        "devices": latest_events,
        "total_devices": len(latest_events)
    }


@app.post("/api/conveyor/command")
async def conveyor_command(command: ConveyorCommand):
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
                body=json.dumps(event).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=event["event_id"]
            ),
            routing_key="command.factory.actuator.conveyor-01",
            mandatory=True
        )

    except Exception:
        logger.exception("Erro ao publicar comando")
        raise HTTPException(
            status_code=503,
            detail="Nao foi possivel encaminhar o comando"
        )

    return {
        "status": "queued",
        "action": command.action,
        "event_id": event["event_id"]
    }


@app.websocket("/ws/factory")
async def factory_websocket(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.add(websocket)

    try:
        await websocket.send_json({
            "type": "snapshot",
            "devices": latest_events
        })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    finally:
        websocket_clients.discard(websocket)
