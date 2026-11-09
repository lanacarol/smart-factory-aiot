
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "datasets"
OUTPUT_FILE = OUTPUT_DIR / "factory_synthetic.csv"
INFO_FILE = OUTPUT_DIR / "factory_synthetic.json"

# Quanto cada sinal cresce com o desgaste (0 -> 1), por modo de falha.
FAILURE_MODES = {
    # Todos os sinais pioram juntos (comportamento original).
    "geral": {"temperature": 22, "vibration": 6.0, "current": 3.0},
    # Rolamento: vibracao domina.
    "rolamento": {"temperature": 10, "vibration": 9.0, "current": 1.5},
    # Superaquecimento: temperatura domina.
    "superaquecimento": {"temperature": 35, "vibration": 3.0, "current": 2.0},
    # Falha eletrica: corrente domina.
    "eletrica": {"temperature": 15, "vibration": 3.0, "current": 6.0},
}

SENSOR_COLUMNS = [
    "temperature_c",
    "vibration_mm_s",
    "current_a",
    "ambient_temperature_c",
    "humidity_percent",
]


def gerar_dados(
    quantidade_motores=200,
    ciclos_por_motor=5000,
    seed=42,
    failure_rate=70.0,
    failure_modes=("geral",),
    noise=1.0,
    missing_percent=0.0,
    outlier_percent=0.8,
    days=30,
):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    total = quantidade_motores * ciclos_por_motor
    failure_modes = list(failure_modes)

    # Cada ciclo corresponde a um intervalo de tempo: o periodo
    # escolhido em dias e distribuido pelos ciclos de cada motor.
    segundos_por_ciclo = days * 86400 / ciclos_por_motor
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)

    print("=" * 55)
    print("SMART FACTORY AIoT - GERADOR DE DADOS")
    print("=" * 55)
    print(f"Motores: {quantidade_motores}")
    print(f"Ciclos por motor: {ciclos_por_motor}")
    print(f"Total previsto: {total:,}")
    print(f"Seed: {seed}")
    print(f"Motores que falham: {failure_rate:.0f}%")
    print(f"Modos de falha: {', '.join(failure_modes)}")
    print(f"Ruido: x{noise:.2f} | Faltantes: {missing_percent:.1f}% "
          f"| Outliers: {outlier_percent:.1f}% | Periodo: {days} dias")
    print(flush=True)

    tmp_file = OUTPUT_FILE.with_suffix(".csv.tmp")

    if tmp_file.exists():
        tmp_file.unlink()

    registros_gerados = 0
    motores_com_falha = 0
    contagem_modos = {mode: 0 for mode in failure_modes}

    for motor_id in range(1, quantidade_motores + 1):

        ciclos = np.arange(
            1,
            ciclos_por_motor + 1,
            dtype=np.int32
        )

        # Parte dos motores chega a falha dentro do periodo
        # simulado; os demais terminam ainda funcionando.
        falha_no_periodo = rng.random() < failure_rate / 100

        if falha_no_periodo:
            motores_com_falha += 1
            vida_util = int(ciclos_por_motor * rng.uniform(0.55, 0.98))
        else:
            vida_util = int(ciclos_por_motor * rng.uniform(1.02, 1.6))

        modo = failure_modes[int(rng.integers(len(failure_modes)))]
        contagem_modos[modo] += 1
        efeito = FAILURE_MODES[modo]

        # Desgaste latente: usado para gerar leituras e rotulos.
        # Nao e uma entrada do modelo de IA.
        desgaste = np.clip(
            ciclos / vida_util,
            0,
            1
        )

        # Ciclo dia/noite: ambiente mais quente a tarde.
        horas = (ciclos * segundos_por_ciclo / 3600) % 24
        dia_noite = 4 * np.sin((horas - 9) / 24 * 2 * np.pi)

        # Ambiente varia periodicamente e contem ruido.
        temperatura_ambiente = (
            29
            + 5 * np.sin(ciclos / 180)
            + dia_noite
            + rng.normal(0, 1.5 * noise, len(ciclos))
        )

        umidade = np.clip(
            55
            - 0.5 * (temperatura_ambiente - 29)
            + rng.normal(0, 5 * noise, len(ciclos)),
            20,
            90
        )

        # Paradas ocasionais da producao.
        ligado = (
            (ciclos % 230) < 210
        )

        # Variacao individual de cada motor.
        fator_motor = rng.normal(0, 1)

        # Temperatura, vibracao e corrente crescem
        # conforme o equipamento se desgasta.
        temperatura_motor = np.where(
            ligado,
            temperatura_ambiente
            + 30
            + desgaste * efeito["temperature"]
            + fator_motor
            + rng.normal(0, 1.5 * noise, len(ciclos)),
            temperatura_ambiente
            + 4
            + desgaste * 5
            + rng.normal(0, 0.8 * noise, len(ciclos))
        )

        vibracao = np.where(
            ligado,
            1.5
            + desgaste * efeito["vibration"]
            + fator_motor * 0.08
            + rng.normal(0, 0.35 * noise, len(ciclos)),
            0.1
        )

        corrente = np.where(
            ligado,
            7.5
            + desgaste * efeito["current"]
            + fator_motor * 0.1
            + rng.normal(0, 0.25 * noise, len(ciclos)),
            0.0
        )

        # Algumas leituras apresentam anomalias (outliers).
        anomalias = (
            rng.random(len(ciclos)) < outlier_percent / 100
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

        # Rotulos reais dentro da simulacao.
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

        instantes = [
            (inicio + timedelta(seconds=float(c * segundos_por_ciclo)))
            .isoformat(timespec="seconds")
            for c in ciclos
        ] if motor_id == 1 else None

        bloco = pd.DataFrame({
            "device_id": f"motor-{motor_id:03d}",
            "cycle": ciclos,
            "hour_of_day": np.round(horas, 2),
            "failure_mode": modo,
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

        # Leituras faltantes (sensor sem resposta).
        if missing_percent > 0:
            for column in SENSOR_COLUMNS:
                faltando = rng.random(len(bloco)) < missing_percent / 100
                bloco.loc[faltando, column] = np.nan

        # Salva em blocos para nao acumular
        # um milhao de linhas na memoria.
        bloco.to_csv(
            tmp_file,
            mode="a",
            index=False,
            header=(motor_id == 1)
        )

        registros_gerados += len(bloco)

        if instantes is not None:
            periodo = f"{instantes[0]} a {instantes[-1]}"

        if (
            motor_id % 10 == 0
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

    # Troca o arquivo so no final: um job interrompido
    # nao deixa um dataset pela metade.
    tmp_file.replace(OUTPUT_FILE)

    info = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": registros_gerados,
        "motors": quantidade_motores,
        "cycles_per_motor": ciclos_por_motor,
        "seed": seed,
        "failure_rate_percent": failure_rate,
        "motors_failed_in_period": motores_com_falha,
        "failure_modes": contagem_modos,
        "noise": noise,
        "missing_percent": missing_percent,
        "outlier_percent": outlier_percent,
        "days": days,
        "period": periodo,
        "file_size_mb": round(OUTPUT_FILE.stat().st_size / 1e6, 1),
    }

    INFO_FILE.write_text(
        json.dumps(info, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print()
    print("BASE GERADA COM SUCESSO!")
    print(f"Arquivo: {OUTPUT_FILE}")
    print(f"Total: {registros_gerados:,} registros")
    print(f"Motores que falharam no periodo: {motores_com_falha}")
    print(f"RESULTADO_JSON: {json.dumps(info)}", flush=True)

    return OUTPUT_FILE


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--motors", type=int, default=200)
    parser.add_argument("--cycles", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--failure-rate", type=float, default=70.0,
        help="Percentual de motores que falham no periodo (0-100)"
    )
    parser.add_argument(
        "--failure-modes", default="geral",
        help="Lista separada por virgula: " + ", ".join(FAILURE_MODES)
    )
    parser.add_argument(
        "--noise", type=float, default=1.0,
        help="Multiplicador do ruido dos sensores"
    )
    parser.add_argument(
        "--missing", type=float, default=0.0,
        help="Percentual de leituras faltantes por sensor"
    )
    parser.add_argument(
        "--outliers", type=float, default=0.8,
        help="Percentual de leituras com anomalia"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Periodo simulado em dias (ciclo dia/noite)"
    )

    args = parser.parse_args()

    modes = [m.strip() for m in args.failure_modes.split(",") if m.strip()]

    if args.motors < 1 or args.cycles < 200:
        parser.error("Use ao menos 1 motor e 200 ciclos.")

    if not modes or any(m not in FAILURE_MODES for m in modes):
        parser.error("Modo de falha invalido.")

    if not (0 <= args.failure_rate <= 100):
        parser.error("--failure-rate deve estar entre 0 e 100.")

    gerar_dados(
        quantidade_motores=args.motors,
        ciclos_por_motor=args.cycles,
        seed=args.seed,
        failure_rate=args.failure_rate,
        failure_modes=modes,
        noise=args.noise,
        missing_percent=args.missing,
        outlier_percent=args.outliers,
        days=args.days,
    )
