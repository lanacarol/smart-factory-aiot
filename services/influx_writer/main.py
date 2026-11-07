
import json
import os
import time
import logging
from datetime import datetime, timezone

import pika
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

QUEUE = "q.telemetry.influx"
DLQ = "q.dead-letter"


def converter_ponto(mensagem):
    if mensagem.get("type") != "telemetry":
        raise ValueError("Evento nao e telemetria")

    device_id = mensagem["device_id"]
    timestamp = datetime.fromisoformat(
        mensagem["timestamp"].replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError("Timestamp sem fuso horario")

    timestamp = timestamp.astimezone(timezone.utc)

    payload = mensagem["payload"]

    if not isinstance(payload, dict):
        raise ValueError("Payload invalido")

    point = (
        Point("sensor_readings")
        .tag("device_id", device_id)
        .time(timestamp, WritePrecision.NS)
    )

    quantidade = 0

    for nome, valor in payload.items():
        if isinstance(valor, bool):
            point.field(nome, valor)
            quantidade += 1
        elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
            point.field(nome, float(valor))
            quantidade += 1

    if quantidade == 0:
        raise ValueError("Mensagem sem campos de sensor")

    return point, device_id


def main():
    while True:
        connection = None
        influx_client = None

        try:
            influx_client = InfluxDBClient(
                url=INFLUXDB_URL,
                token=INFLUXDB_TOKEN,
                org=INFLUXDB_ORG,
                timeout=15000
            )

            write_api = influx_client.write_api(
                write_options=SYNCHRONOUS
            )

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

            channel.queue_declare(queue=DLQ, durable=True)
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.basic_qos(prefetch_count=10)

            logging.info("Conectado ao RabbitMQ e InfluxDB!")
            logging.info("Aguardando telemetria na fila %s", QUEUE)

            def processar(ch, method, properties, body):
                try:
                    mensagem = json.loads(body.decode("utf-8"))
                    ponto, device_id = converter_ponto(mensagem)

                except (ValueError, KeyError, TypeError) as erro:
                    logging.error("Mensagem invalida: %s", erro)

                    ch.basic_publish(
                        exchange="",
                        routing_key=DLQ,
                        body=body,
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type="application/json"
                        )
                    )

                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                try:
                    write_api.write(
                        bucket=INFLUXDB_BUCKET,
                        org=INFLUXDB_ORG,
                        record=ponto
                    )

                    logging.info(
                        "Gravado no InfluxDB | dispositivo: %s",
                        device_id
                    )

                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except Exception as erro:
                    logging.error("Falha na gravacao: %s", erro)

                    # Mantem a mensagem para nova tentativa.
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=True
                    )

                    # Reconecta em vez de repetir a falha
                    # indefinidamente no mesmo consumidor.
                    raise RuntimeError(
                        "Erro de gravacao: reconectando consumidor"
                    ) from erro

            channel.basic_consume(
                queue=QUEUE,
                on_message_callback=processar,
                auto_ack=False
            )

            channel.start_consuming()

        except Exception as erro:
            logging.error("Influx Writer: %s", erro)
            time.sleep(5)

        finally:
            if connection and connection.is_open:
                connection.close()
            if influx_client:
                influx_client.close()


if __name__ == "__main__":
    main()
