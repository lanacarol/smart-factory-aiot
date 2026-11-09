
import json
import os
import time
import threading

import pika
import paho.mqtt.client as mqtt


MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PASSWORD = os.environ["MQTT_GATEWAY_PASSWORD"]

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

QUEUE = "q.commands.device"
# Dispositivo -> (topico MQTT, acoes aceitas)
DEVICES = {
    "conveyor-01": (
        "factory/conveyor/01/command",
        ("ON", "OFF")
    ),
    "motor-01": (
        "factory/motor/01/command",
        ("INJECT_FAULT", "MAINTENANCE")
    ),
}


def conectar_mqtt():
    conectado = threading.Event()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-command-gateway"
    )

    client.username_pw_set("gateway", MQTT_PASSWORD)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            conectado.set()
            print("Command Gateway conectado ao Mosquitto!", flush=True)
        else:
            print(f"Erro MQTT: {reason_code}", flush=True)

    client.on_connect = on_connect
    client.connect(MQTT_HOST, 1883, 60)
    client.loop_start()

    if not conectado.wait(timeout=15):
        client.loop_stop()
        raise RuntimeError("Falha ao conectar no Mosquitto")

    return client


def main():
    while True:
        connection = None
        client = None

        try:
            client = conectar_mqtt()

            credentials = pika.PlainCredentials(
                RABBITMQ_USER,
                RABBITMQ_PASSWORD
            )

            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    credentials=credentials,
                    heartbeat=60
                )
            )

            channel = connection.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)

            print("Aguardando comandos do RabbitMQ...", flush=True)

            def processar(ch, method, properties, body):
                try:
                    mensagem = json.loads(body.decode("utf-8"))

                    device_id = mensagem.get("device_id")

                    if (
                        mensagem.get("type") != "command"
                        or device_id not in DEVICES
                    ):
                        raise ValueError("Comando para dispositivo invalido")

                    topic, allowed = DEVICES[device_id]

                    action = mensagem["payload"]["action"]

                    if action not in allowed:
                        raise ValueError("Acao invalida")

                    if not client.is_connected():
                        raise RuntimeError("MQTT desconectado")

                    comando = json.dumps({"action": action})

                    result = client.publish(
                        topic,
                        comando,
                        qos=1
                    )

                    result.wait_for_publish(timeout=10)

                    if result.rc != mqtt.MQTT_ERR_SUCCESS:
                        raise RuntimeError("Falha na publicacao MQTT")

                    print(
                        f"RabbitMQ -> MQTT | {device_id}: {action}",
                        flush=True
                    )

                    ch.basic_ack(
                        delivery_tag=method.delivery_tag
                    )

                except (ValueError, KeyError, TypeError) as erro:
                    print(f"Comando invalido: {erro}", flush=True)
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag,
                        requeue=False
                    )

                except Exception as erro:
                    print(f"Falha de comunicacao: {erro}", flush=True)
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

        except Exception as erro:
            print(f"Gateway reiniciando: {erro}", flush=True)
            time.sleep(5)

        finally:
            if connection and connection.is_open:
                connection.close()

            if client:
                client.disconnect()
                client.loop_stop()


if __name__ == "__main__":
    main()
