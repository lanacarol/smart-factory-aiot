
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "datasets"
OUTPUT_FILE = OUTPUT_DIR / "factory_synthetic.csv"


def gerar_dados(
    quantidade_motores=200,
    ciclos_por_motor=5000,
    seed=42
):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    total = quantidade_motores * ciclos_por_motor

    print("=" * 55)
    print("SMART FACTORY AIoT - GERADOR DE DADOS")
    print("=" * 55)
    print(f"Motores: {quantidade_motores}")
    print(f"Ciclos por motor: {ciclos_por_motor}")
    print(f"Total previsto: {total:,}")
    print(f"Seed: {seed}")
    print()

    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    registros_gerados = 0

    for motor_id in range(1, quantidade_motores + 1):

        ciclos = np.arange(
            1,
            ciclos_por_motor + 1,
            dtype=np.int32
        )

        # Cada motor possui uma vida útil diferente.
        # Alguns chegam à falha durante a simulação.
        vida_util = int(
            rng.integers(
                max(100, int(ciclos_por_motor * 0.82)),
                max(101, int(ciclos_por_motor * 1.08))
            )
        )

        # Desgaste latente: usado para gerar leituras e rótulos.
        # Não será uma entrada do modelo de IA.
        desgaste = np.clip(
            ciclos / vida_util,
            0,
            1
        )

        # Ambiente varia periodicamente e contém ruído.
        temperatura_ambiente = (
            29
            + 7 * np.sin(ciclos / 180)
            + rng.normal(0, 1.5, len(ciclos))
        )

        umidade = np.clip(
            55
            - 0.5 * (temperatura_ambiente - 29)
            + rng.normal(0, 5, len(ciclos)),
            20,
            90
        )

        # Paradas ocasionais da produção.
        ligado = (
            (ciclos % 230) < 210
        )

        # Variação individual de cada motor.
        fator_motor = rng.normal(0, 1)

        # Temperatura, vibração e corrente crescem
        # conforme o equipamento se desgasta.
        temperatura_motor = np.where(
            ligado,
            temperatura_ambiente
            + 30
            + desgaste * 22
            + fator_motor
            + rng.normal(0, 1.5, len(ciclos)),
            temperatura_ambiente
            + 4
            + desgaste * 5
            + rng.normal(0, 0.8, len(ciclos))
        )

        vibracao = np.where(
            ligado,
            1.5
            + desgaste * 6
            + fator_motor * 0.08
            + rng.normal(0, 0.35, len(ciclos)),
            0.1
        )

        corrente = np.where(
            ligado,
            7.5
            + desgaste * 3
            + fator_motor * 0.1
            + rng.normal(0, 0.25, len(ciclos)),
            0.0
        )

        # Algumas leituras apresentam anomalias.
        anomalias = (
            rng.random(len(ciclos)) < 0.008
        ) & ligado

        vibracao[anomalias] += rng.uniform(
            1.5,
            4,
            anomalias.sum()
        )

        temperatura_motor[anomalias] += rng.uniform(
            3,
            8,
            anomalias.sum()
        )

        # Rótulos reais dentro da simulação.
        rul = np.maximum(
            vida_util - ciclos,
            0
        )

        saude = np.clip(
            (1 - desgaste) * 100,
            0,
            100
        )

        falhou = ciclos >= vida_util

        bloco = pd.DataFrame({
            "device_id": f"motor-{motor_id:03d}",
            "cycle": ciclos,
            "temperature_c": np.round(
                temperatura_motor, 2
            ),
            "vibration_mm_s": np.round(
                np.maximum(vibracao, 0), 2
            ),
            "current_a": np.round(
                np.maximum(corrente, 0), 2
            ),
            "ambient_temperature_c": np.round(
                temperatura_ambiente, 2
            ),
            "humidity_percent": np.round(
                umidade, 2
            ),
            "running": ligado,
            "health_percent": np.round(
                saude, 2
            ),
            "rul_cycles": rul,
            "failure": falhou.astype(int)
        })

        # Salva em blocos para não acumular
        # um milhão de linhas na memória.
        bloco.to_csv(
            OUTPUT_FILE,
            mode="a",
            index=False,
            header=(motor_id == 1)
        )

        registros_gerados += len(bloco)

        if (
            motor_id % 20 == 0
            or motor_id == quantidade_motores
        ):
            progresso = (
                registros_gerados / total
            ) * 100

            print(
                f"Progresso: {progresso:.0f}% | "
                f"{registros_gerados:,} registros",
                flush=True
            )

    print()
    print("BASE GERADA COM SUCESSO!")
    print(f"Arquivo: {OUTPUT_FILE}")
    print(f"Total: {registros_gerados:,} registros")

    return OUTPUT_FILE


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--motors",
        type=int,
        default=200
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=5000
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42
    )

    args = parser.parse_args()

    if args.motors < 1 or args.cycles < 200:
        parser.error(
            "Use ao menos 1 motor e 200 ciclos."
        )

    gerar_dados(
        quantidade_motores=args.motors,
        ciclos_por_motor=args.cycles,
        seed=args.seed
    )
