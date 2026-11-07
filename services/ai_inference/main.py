
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import pika


# ==========================================
# CONFIGURACOES
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

RABBITMQ_HOST = os.getenv(
    "RABBITMQ_HOST",
    "rabbitmq"
)

RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

EXCHANGE = "factory.topic"
QUEUE = "q.telemetry.ai"
DLQ = "q.dead-letter"

MODEL_DIR = Path(
    os.getenv("MODEL_DIR", "/app/models")
)

FEATURES = [
    "cycle",
    "temperature_c",
    "vibration_mm_s",
    "current_a",
    "ambient_temperature_c",
    "humidity_percent",
    "running"
]


# ==========================================
# CARREGAMENTO DOS MODELOS
# ==========================================

def carregar_modelos():
    rul_path = MODEL_DIR / "rul_model.joblib"
    health_path = MODEL_DIR / "health_model.joblib"

    if not rul_path.is_file():
        raise FileNotFoundError(
            f"Modelo RUL nao encontrado: {rul_path}"
        )

    if not health_path.is_file():
        raise FileNotFoundError(
            f"Modelo HEALTH nao encontrado: {health_path}"
        )

    rul_model = joblib.load(rul_path)
    health_model = joblib.load(health_path)

    logging.info("Modelo RUL carregado!")
    logging.info("Modelo HEALTH carregado!")

    return rul_model, health_model


# ==========================================
# VALIDACAO DA TELEMETRIA
# ==========================================

def preparar_entradas(evento):
    if not isinstance(evento, dict):
        raise ValueError("Evento invalido")

    if evento.get("type") != "telemetry":
        return None

    if evento.get("device_id") != "motor-01":
        return None

    payload = evento.get("payload")

    if not isinstance(payload, dict):
        raise ValueError("Payload do motor invalido")

    faltantes = [
        campo
        for campo in FEATURES
        if campo not in payload
    ]

    if faltantes:
        raise ValueError(
            f"Campos ausentes: {faltantes}"
        )

    if not isinstance(payload["running"], bool):
        raise ValueError(
            "O campo running deve ser booleano"
        )

    entradas = {
        campo: payload[campo]
        for campo in FEATURES
    }

    entradas["running"] = int(
        entradas["running"]
    )

    for campo, valor in entradas.items():
        if (
            not isinstance(valor, (int, float))
            or not (-float("inf") < float(valor) < float("inf"))
        ):
            raise ValueError(
                f"Valor numerico invalido: {campo}"
            )

    return pd.DataFrame(
        [entradas],
        columns=FEATURES
    ).astype("float32")


# ==========================================
# INFERENCIA
# ==========================================

def prever(evento, rul_model, health_model):
    entradas = preparar_entradas(evento)

    if entradas is None:
        return None

    rul = float(
        rul_model.predict(entradas)[0]
    )

    health = float(
        health_model.predict(entradas)[0]
    )

    rul = max(0.0, rul)
    health = max(0.0, min(100.0, health))

    if health < 30 or rul < 500:
        status = "critical"
    elif health < 60 or rul < 1500:
        status = "warning"
    else:
        status = "healthy"

    resultado = {
        "event_id": str(uuid.uuid4()),
        "device_id": evento["device_id"],
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "type": "prediction",
        "source_event_id": evento.get("event_id"),
        "payload": {
            "rul_cycles": round(rul, 2),
            "health_percent": round(health, 2),
            "maintenance_status": status,
            "model_version": "1.0.0",
            "cycle": int(
                entradas["cycle"].iloc[0]
            )
        }
    }

    return resultado


# ==========================================
# RABBITMQ
# ==========================================

def conectar_rabbitmq():
    credentials = pika.PlainCredentials(
        RABBITMQ_USER,
        RABBITMQ_PASSWORD
    )

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            heartbeat=60,
            blocked_connection_timeout=30
        )
    )

    channel = connection.channel()

    channel.exchange_declare(
        exchange=EXCHANGE,
        exchange_type="topic",
        durable=True
    )

    channel.queue_declare(
        queue=QUEUE,
        durable=True
    )

    channel.queue_bind(
        exchange=EXCHANGE,
        queue=QUEUE,
        routing_key="telemetry.#"
    )

    channel.queue_declare(
        queue=DLQ,
        durable=True
    )

    channel.basic_qos(prefetch_count=10)

    # Aguarda confirmacao do RabbitMQ
    # antes de confirmar a leitura original.
    channel.confirm_delivery()

    return connection, channel


# ==========================================
# CONSUMIDOR PRINCIPAL
# ==========================================

def main():
    rul_model, health_model = carregar_modelos()

    while True:
        connection = None

        try:
            connection, channel = conectar_rabbitmq()

            logging.info(
                "IA conectada ao RabbitMQ!"
            )

            logging.info(
                "Consumindo fila: %s",
                QUEUE
            )

            def processar(ch, method, properties, body):
                try:
                    evento = json.loads(
                        body.decode("utf-8")
                    )

                    resultado = prever(
                        evento,
                        rul_model,
                        health_model
                    )

                except (
                    ValueError,
                    KeyError,
                    TypeError
                ) as error:
                    logging.warning(
                        "Telemetria invalida: %s",
                        error
                    )

                    # Encaminha mensagens invalidas
                    # para a fila de analise.
                    confirmado = ch.basic_publish(
                        exchange="",
                        routing_key=DLQ,
                        body=body,
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type="application/json"
                        ),
                        mandatory=True
                    )

                    if confirmado is False:
                        raise RuntimeError(
                            "Falha ao publicar na DLQ"
                        )

                    ch.basic_ack(
                        delivery_tag=method.delivery_tag
                    )
                    return

                if resultado is None:
                    # Eventos de outros sensores
                    # nao precisam de inferencia.
                    ch.basic_ack(
                        delivery_tag=method.delivery_tag
                    )
                    return

                try:
                    confirmado = ch.basic_publish(
                        exchange=EXCHANGE,
                        routing_key=(
                            "prediction.factory.motor.motor-01"
                        ),
                        body=json.dumps(
                            resultado
                        ).encode("utf-8"),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type="application/json",
                            message_id=resultado["event_id"]
                        ),
                        mandatory=True
                    )

                    if confirmado is False:
                        raise RuntimeError(
                            "Previsao nao confirmada"
                        )

                    logging.info(
                        "IA | Motor: %s | "
                        "RUL: %.2f ciclos | "
                        "Saude: %.2f%% | "
                        "Status: %s",
                        resultado["device_id"],
                        resultado["payload"]["rul_cycles"],
                        resultado["payload"]["health_percent"],
                        resultado["payload"]["maintenance_status"]
                    )

                    ch.basic_ack(
                        delivery_tag=method.delivery_tag
                    )

                except Exception:
                    logging.exception(
                        "Erro ao publicar previsao"
                    )

                    # Recoloca a telemetria na fila
                    # para nova tentativa.
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=True
                    )

                    raise

            channel.basic_consume(
                queue=QUEUE,
                on_message_callback=processar,
                auto_ack=False
            )

            channel.start_consuming()

        except Exception as error:
            logging.error(
                "Servico de IA: %s",
                error
            )

            time.sleep(5)

        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
