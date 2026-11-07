
import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


HOST = os.getenv("MQTT_HOST", "mosquitto")
PORT = 1883
PASSWORD = os.environ["MQTT_SIMULATOR_PASSWORD"]

MOTOR_TOPIC = "factory/motor/01/telemetry"
ENVIRONMENT_TOPIC = "factory/environment/01/telemetry"


def main():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-simulator-01",
    )

    client.username_pw_set("simulator", PASSWORD)
    client.connect(HOST, PORT, keepalive=60)
    client.loop_start()

    print("Simulador conectado ao Mosquitto!", flush=True)

    try:
        while True:
            timestamp = datetime.now(timezone.utc).isoformat()

            # Sensores do motor
            motor = {
                "event_id": f"motor-{time.time_ns()}",
                "device_id": "motor-01",
                "timestamp": timestamp,
                "type": "telemetry",
                "payload": {
                    "temperature_c": round(
                        random.uniform(58, 65), 2
                    ),
                    "vibration_mm_s": round(
                        random.uniform(1.5, 3.5), 2
                    ),
                    "current_a": round(
                        random.uniform(7.5, 9.0), 2
                    ),
                    "running": True,
                },
            }

            client.publish(
                MOTOR_TOPIC,
                json.dumps(motor),
                qos=1,
            ).wait_for_publish()

            print(json.dumps(motor), flush=True)

            # Sensores ambientais
            environment = {
                "event_id": f"env-{time.time_ns()}",
                "device_id": "environment-01",
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                "type": "telemetry",
                "payload": {
                    "temperature_c": round(
                        random.uniform(28, 38), 2
                    ),
                    "humidity_percent": round(
                        random.uniform(40, 70), 2
                    ),
                },
            }

            client.publish(
                ENVIRONMENT_TOPIC,
                json.dumps(environment),
                qos=1,
            ).wait_for_publish()

            print(json.dumps(environment), flush=True)

            time.sleep(3)

    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
