
import json
import os
import random
import time
from fan_rules import atualizar_ventilador
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


HOST = os.getenv("MQTT_HOST", "mosquitto")
PASSWORD = os.environ["MQTT_SIMULATOR_PASSWORD"]

MOTOR_TOPIC = "factory/motor/01/telemetry"
ENV_TOPIC = "factory/environment/01/telemetry"
CONVEYOR_COMMAND = "factory/conveyor/01/command"
CONVEYOR_STATE = "factory/conveyor/01/state"
FAN_STATE = "factory/fan/01/state"

conveyor_on = True
fan_on = False
temperature = 32.0
wear = 0.0


def send(client, topic, device_id, event_type, payload):
    message = {
        "event_id": f"{device_id}-{time.time_ns()}",
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }

    client.publish(
        topic,
        json.dumps(message),
        qos=1
    ).wait_for_publish()

    print(json.dumps(message), flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Conectado ao Mosquitto!", flush=True)
        client.subscribe(CONVEYOR_COMMAND, qos=1)
    else:
        print(f"Falha na conexao MQTT: {reason_code}", flush=True)


def on_message(client, userdata, msg):
    global conveyor_on

    try:
        command = json.loads(msg.payload.decode())
        action = command.get("action")

        if action not in ["ON", "OFF"]:
            print("Comando invalido recebido", flush=True)
            return

        conveyor_on = action == "ON"

        print(
            f"ESTEIRA: {'LIGADA' if conveyor_on else 'DESLIGADA'}",
            flush=True
        )

    except (ValueError, UnicodeDecodeError) as error:
        print(f"Erro no comando: {error}", flush=True)


def main():
    global temperature, fan_on, wear

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-simulator-01"
    )

    client.username_pw_set("simulator", PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(HOST, 1883, 60)
    client.loop_start()

    try:
        while True:
            # Temperatura ambiente muda gradualmente.
            temperature += random.uniform(-0.7, 0.9)
            temperature = max(25, min(42, temperature))

            # Regra automatica do ventilador.
            fan_on = atualizar_ventilador(temperature, fan_on)

            # Desgaste progressivo do motor.
            if conveyor_on:
                wear = min(1.0, wear + 0.001)

            motor_temp = (
                temperature + (30 if conveyor_on else 4)
                + wear * 18
                + random.uniform(-1, 1)
            )

            vibration = (
                (1.5 + wear * 6 + random.uniform(-0.3, 0.3))
                if conveyor_on else 0.1
            )

            current = (
                (7.5 + wear * 3 + random.uniform(-0.3, 0.3))
                if conveyor_on else 0.0
            )

            send(client, MOTOR_TOPIC, "motor-01", "telemetry", {
                "temperature_c": round(motor_temp, 2),
                "vibration_mm_s": round(max(0, vibration), 2),
                "current_a": round(max(0, current), 2),
                "running": conveyor_on,
            })

            send(client, ENV_TOPIC, "environment-01", "telemetry", {
                "temperature_c": round(temperature, 2),
                "humidity_percent": round(
                    max(20, min(90, 55 + random.uniform(-5, 5))), 2
                ),
            })

            send(client, CONVEYOR_STATE, "conveyor-01", "state", {
                "running": conveyor_on
            })

            send(client, FAN_STATE, "fan-01", "state", {
                "running": fan_on
            })

            print(
                f"FABRICA | Esteira: {'ON' if conveyor_on else 'OFF'} "
                f"| Ventilador: {'ON' if fan_on else 'OFF'} "
                f"| Temperatura: {temperature:.2f} C "
                f"| Desgaste: {wear:.3f}",
                flush=True
            )

            time.sleep(3)

    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
