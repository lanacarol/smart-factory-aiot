
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

# Codigo de atributos compartilhado com o treino
# (ai/features.py, montado no container).
from features import FEATURE_SETS, WINDOW, latest_features

RAW_FIELDS = [
    "cycle",
    "temperature_c",
    "vibration_mm_s",
    "current_a",
    "ambient_temperature_c",
    "humidity_percent",
    "running"
]


# ==========================================
# CARREGAMENTO E RECARGA DOS MODELOS
# ==========================================

class Modelos:
    """Carrega os modelos e os recarrega sozinho quando o
    metadata.json muda (novo treino), sem reiniciar o servico."""

    def __init__(self):
        self.metadata_mtime = None
        self.version = "desconhecida"
        self.feature_set = "instant"
        self.rul = None
        self.health = None
        # Ultimas leituras por motor, para as janelas do passado.
        self.buffers = {}
        self.ultima_verificacao = 0.0
        self.carregar()

    def carregar(self):
        metadata_path = MODEL_DIR / "metadata.json"

        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            mtime = metadata_path.stat().st_mtime
        except (OSError, ValueError):
            metadata, mtime = {}, None

        rul_model = joblib.load(MODEL_DIR / "rul_model.joblib")
        health_model = joblib.load(MODEL_DIR / "health_model.joblib")

        feature_set = metadata.get("feature_set", "instant")

        if feature_set not in FEATURE_SETS:
            raise ValueError(f"Conjunto de atributos invalido: {feature_set}")

        self.rul = rul_model
        self.health = health_model
        self.version = metadata.get("model_version", "1.0.0")
        self.feature_set = feature_set
        self.metadata_mtime = mtime

        logging.info(
            "Modelos carregados | versao %s | atributos %s",
            self.version,
            self.feature_set
        )

    def recarregar_se_mudou(self):
        agora = time.monotonic()

        if agora - self.ultima_verificacao < 5:
            return

        self.ultima_verificacao = agora

        try:
            mtime = (MODEL_DIR / "metadata.json").stat().st_mtime
        except OSError:
            return

        if mtime == self.metadata_mtime:
            return

        try:
            self.carregar()
            logging.info("Novo modelo em uso: %s", self.version)
        except Exception:
            # Mantem o modelo anterior se o novo nao carregar.
            logging.exception("Falha ao recarregar modelos")
            self.metadata_mtime = mtime


# ==========================================
# VALIDACAO DA TELEMETRIA
# ==========================================

def validar_leitura(evento):
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
        for campo in RAW_FIELDS
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

    leitura = {
        campo: payload[campo]
        for campo in RAW_FIELDS
    }

    leitura["running"] = int(
        leitura["running"]
    )

    for campo, valor in leitura.items():
        if (
            not isinstance(valor, (int, float))
            or not (-float("inf") < float(valor) < float("inf"))
        ):
            raise ValueError(
                f"Valor numerico invalido: {campo}"
            )

    return leitura


# ==========================================
# INFERENCIA
# ==========================================

def prever(evento, modelos):
    leitura = validar_leitura(evento)

    if leitura is None:
        return None

    modelos.recarregar_se_mudou()

    device_id = evento["device_id"]
    buffer = modelos.buffers.setdefault(device_id, [])
    buffer.append(leitura)
    del buffer[:-WINDOW]

    entradas = latest_features(buffer, modelos.feature_set)

    rul = float(
        modelos.rul.predict(entradas)[0]
    )

    health = float(
        modelos.health.predict(entradas)[0]
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
        "device_id": device_id,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "type": "prediction",
        "source_event_id": evento.get("event_id"),
        "payload": {
            "rul_cycles": round(rul, 2),
            "health_percent": round(health, 2),
            "maintenance_status": status,
            "model_version": modelos.version,
            "feature_set": modelos.feature_set,
            "cycle": int(leitura["cycle"])
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
    # Na primeira execucao o worker ai-jobs ainda esta treinando:
    # aguarda os modelos em vez de encerrar com erro.
    while not all(
        (MODEL_DIR / name).is_file()
        for name in ("rul_model.joblib", "health_model.joblib", "metadata.json")
    ):
        logging.info("Aguardando modelos treinados em %s ...", MODEL_DIR)
        time.sleep(10)

    modelos = Modelos()

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
                        modelos
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
