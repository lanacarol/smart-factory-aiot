
import json
import os
import time

import pika
import paho.mqtt.client as mqtt


MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PASSWORD = os.environ["MQTT_GATEWAY_PASSWORD"]

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

EXCHANGE = "factory.topic"

rabbit_connection = None
rabbit_channel = None


def conectar_rabbitmq():
    global rabbit_connection, rabbit_channel

    credentials = pika.PlainCredentials(
        RABBITMQ_USER,
        RABBITMQ_PASSWORD
    )

    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=60
    )

    while True:
        try:
            rabbit_connection = pika.BlockingConnection(parameters)
            rabbit_channel = rabbit_connection.channel()

            rabbit_channel.exchange_declare(
                exchange=EXCHANGE,
                exchange_type="topic",
                durable=True
            )

            filas = {
                "q.telemetry.influx": "telemetry.#",
                "q.telemetry.ai": "telemetry.#",
                "q.telemetry.websocket": "telemetry.#",
                "q.commands.device": "command.#",
            }

            for fila, rota in filas.items():
                rabbit_channel.queue_declare(
                    queue=fila,
                    durable=True
                )

                rabbit_channel.queue_bind(
                    exchange=EXCHANGE,
                    queue=fila,
                    routing_key=rota
                )


            rabbit_channel.queue_bind(
                exchange=EXCHANGE,
                queue="q.telemetry.websocket",
                routing_key="state.#"
            )


            rabbit_channel.queue_declare(
                queue="q.dead-letter",
                durable=True
            )

            print("Conectado ao RabbitMQ!", flush=True)
            print("Exchange e filas criadas!", flush=True)
            break

        except pika.exceptions.AMQPConnectionError as error:
            print(f"RabbitMQ indisponivel: {error}", flush=True)
            time.sleep(5)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Gateway conectado ao Mosquitto!", flush=True)

        client.subscribe(
            "factory/+/+/telemetry",
            qos=1
        )

        client.subscribe(
            "factory/+/+/state",
            qos=1
        )
    else:
        print(f"Erro MQTT: {reason_code}", flush=True)


def on_message(client, userdata, msg):
    global rabbit_connection, rabbit_channel

    try:
        dados = json.loads(msg.payload.decode("utf-8"))

        device_id = dados["device_id"]
        event_type = dados["type"]

        if event_type not in ("telemetry", "state"):
            print("Tipo de evento ignorado", flush=True)
            return

        partes = msg.topic.split("/")

        if len(partes) != 4:
            print("Topico invalido", flush=True)
            return

        categoria = partes[1]

        routing_key = (
            f"{event_type}.factory.{categoria}.{device_id}"
        )

        if rabbit_connection is None or rabbit_connection.is_closed:
            conectar_rabbitmq()

        rabbit_channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(dados).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                message_id=str(dados.get("event_id", ""))
            ),
            mandatory=False
        )

        print(
            f"MQTT -> RabbitMQ | {routing_key}",
            flush=True
        )

    except Exception as error:
        print(f"Erro ao encaminhar mensagem: {error}", flush=True)
        raise


def main():
    conectar_rabbitmq()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-mqtt-gateway"
    )

    client.username_pw_set(
        "gateway",
        MQTT_PASSWORD
    )

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, 1883, 60)

    print("Gateway iniciado!", flush=True)

    client.loop_forever()


if __name__ == "__main__":
    main()
