
import json
import os
import sys
import threading
import uuid

import paho.mqtt.client as mqtt

action = sys.argv[1].upper() if len(sys.argv) > 1 else "OFF"

if action not in ("ON", "OFF"):
    raise ValueError("Use ON ou OFF")

connected = threading.Event()

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"factory-test-{uuid.uuid4().hex[:8]}"
)

client.username_pw_set(
    "gateway",
    os.environ["MQTT_GATEWAY_PASSWORD"]
)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        connected.set()
    else:
        print(f"Falha de autenticacao: {reason_code}", flush=True)


client.on_connect = on_connect

try:
    client.connect(
        os.getenv("MQTT_HOST", "mosquitto"),
        1883,
        60
    )

    client.loop_start()

    if not connected.wait(timeout=10):
        raise RuntimeError("Nao foi possivel conectar ao MQTT")

    message = json.dumps({"action": action})

    result = client.publish(
        "factory/conveyor/01/command",
        message,
        qos=1
    )

    result.wait_for_publish(timeout=10)

    print(f"Comando MQTT publicado: {action}")

finally:
    client.disconnect()
    client.loop_stop()
