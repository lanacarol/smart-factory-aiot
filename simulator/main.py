
import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from fan_rules import atualizar_ventilador


# ==========================================
# CONFIGURACOES MQTT
# ==========================================

HOST = os.getenv("MQTT_HOST", "mosquitto")
PASSWORD = os.environ["MQTT_SIMULATOR_PASSWORD"]

MOTOR_TOPIC = "factory/motor/01/telemetry"
ENV_TOPIC = "factory/environment/01/telemetry"
CONVEYOR_COMMAND = "factory/conveyor/01/command"
CONVEYOR_STATE = "factory/conveyor/01/state"
FAN_STATE = "factory/fan/01/state"


# ==========================================
# ESTADO INICIAL DA FABRICA
# ==========================================

conveyor_on = True
fan_on = False

temperature = 32.0
wear = 0.0
cycle_count = 0


# ==========================================
# PUBLICACAO MQTT
# ==========================================

def send(client, topic, device_id, event_type, payload):
    message = {
        "event_id": f"{device_id}-{time.time_ns()}",
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }

    result = client.publish(
        topic,
        json.dumps(message),
        qos=1
    )

    result.wait_for_publish()

    print(
        json.dumps(message),
        flush=True
    )


# ==========================================
# CONEXAO MQTT
# ==========================================

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(
            "Conectado ao Mosquitto!",
            flush=True
        )

        client.subscribe(
            CONVEYOR_COMMAND,
            qos=1
        )

    else:
        print(
            f"Falha na conexao MQTT: {reason_code}",
            flush=True
        )


# ==========================================
# RECEBIMENTO DE COMANDOS
# ==========================================

def on_message(client, userdata, msg):
    global conveyor_on

    try:
        command = json.loads(
            msg.payload.decode("utf-8")
        )

        action = command.get("action")

        if action not in ["ON", "OFF"]:
            print(
                "Comando invalido recebido",
                flush=True
            )
            return

        conveyor_on = action == "ON"

        print(
            f"ESTEIRA: {'LIGADA' if conveyor_on else 'DESLIGADA'}",
            flush=True
        )

    except (ValueError, UnicodeDecodeError) as error:
        print(
            f"Erro no comando: {error}",
            flush=True
        )


# ==========================================
# SIMULACAO PRINCIPAL
# ==========================================

def main():
    global temperature
    global fan_on
    global wear
    global cycle_count

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-simulator-01"
    )

    client.username_pw_set(
        "simulator",
        PASSWORD
    )

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(
        HOST,
        1883,
        60
    )

    client.loop_start()

    try:
        while True:

            # ----------------------------------
            # 1. TEMPERATURA AMBIENTE
            # ----------------------------------

            temperature += random.uniform(
                -0.7,
                0.9
            )

            temperature = max(
                25,
                min(42, temperature)
            )

            # ----------------------------------
            # 2. UMIDADE AMBIENTE
            # ----------------------------------

            # A umidade e gerada apenas uma vez
            # por ciclo e compartilhada entre
            # a telemetria do ambiente e do motor.

            humidity = round(
                max(
                    20,
                    min(
                        90,
                        55 + random.uniform(-5, 5)
                    )
                ),
                2
            )

            # ----------------------------------
            # 3. CONTROLE AUTOMATICO DO VENTILADOR
            # ----------------------------------

            fan_on = atualizar_ventilador(
                temperature,
                fan_on
            )

            # ----------------------------------
            # 4. CICLOS E DESGASTE DO MOTOR
            # ----------------------------------

            # Cada iteracao com a esteira ligada
            # representa um ciclo sintetico.

            if conveyor_on:
                cycle_count += 1

                wear = min(
                    1.0,
                    cycle_count / 4600
                )

            # ----------------------------------
            # 5. TEMPERATURA DO MOTOR
            # ----------------------------------

            motor_temp = (
                temperature
                + (30 if conveyor_on else 4)
                + wear * 18
                + random.uniform(-1, 1)
            )

            # ----------------------------------
            # 6. VIBRACAO DO MOTOR
            # ----------------------------------

            vibration = (
                (
                    1.5
                    + wear * 6
                    + random.uniform(-0.3, 0.3)
                )
                if conveyor_on
                else 0.1
            )

            # ----------------------------------
            # 7. CORRENTE ELETRICA
            # ----------------------------------

            current = (
                (
                    7.5
                    + wear * 3
                    + random.uniform(-0.3, 0.3)
                )
                if conveyor_on
                else 0.0
            )

            # ----------------------------------
            # 8. TELEMETRIA DO MOTOR
            # ----------------------------------

            # Inclui as sete variaveis utilizadas
            # durante o treinamento da IA.

            send(
                client,
                MOTOR_TOPIC,
                "motor-01",
                "telemetry",
                {
                    "temperature_c": round(
                        motor_temp, 2
                    ),
                    "vibration_mm_s": round(
                        max(0, vibration), 2
                    ),
                    "current_a": round(
                        max(0, current), 2
                    ),
                    "running": conveyor_on,
                    "cycle": cycle_count,
                    "ambient_temperature_c": round(
                        temperature, 2
                    ),
                    "humidity_percent": humidity,
                }
            )

            # ----------------------------------
            # 9. TELEMETRIA DO AMBIENTE
            # ----------------------------------

            send(
                client,
                ENV_TOPIC,
                "environment-01",
                "telemetry",
                {
                    "temperature_c": round(
                        temperature, 2
                    ),
                    "humidity_percent": humidity,
                }
            )

            # ----------------------------------
            # 10. ESTADO DA ESTEIRA
            # ----------------------------------

            send(
                client,
                CONVEYOR_STATE,
                "conveyor-01",
                "state",
                {
                    "running": conveyor_on
                }
            )

            # ----------------------------------
            # 11. ESTADO DO VENTILADOR
            # ----------------------------------

            send(
                client,
                FAN_STATE,
                "fan-01",
                "state",
                {
                    "running": fan_on
                }
            )

            # ----------------------------------
            # 12. LOG DA FABRICA
            # ----------------------------------

            print(
                f"FABRICA "
                f"| Esteira: {'ON' if conveyor_on else 'OFF'} "
                f"| Ventilador: {'ON' if fan_on else 'OFF'} "
                f"| Temperatura: {temperature:.2f} C "
                f"| Umidade: {humidity:.2f}% "
                f"| Ciclos: {cycle_count} "
                f"| Desgaste: {wear:.3f}",
                flush=True
            )

            # Atualizacao a cada 3 segundos.
            time.sleep(3)

    finally:
        client.loop_stop()
        client.disconnect()


# ==========================================
# INICIALIZACAO
# ==========================================

if __name__ == "__main__":
    main()
