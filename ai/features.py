"""
Atributos da IA - codigo UNICO usado no treino (ai/train_models.py)
e na inferencia em tempo real (services/ai_inference).

Dois conjuntos:

- "instant": leituras do instante + contador de ciclos (modelo 1.0).
  O contador zera quando o simulador reinicia, entao o modelo acaba
  "lendo o relogio" em vez dos sintomas.

- "window": leituras do instante + janelas do passado (media, desvio
  e tendencia das ultimas WINDOW leituras) de temperatura, vibracao e
  corrente. Nao usa o contador de ciclos.
"""

import numpy as np
import pandas as pd


WINDOW = 20

SENSORS = [
    "temperature_c",
    "vibration_mm_s",
    "current_a",
]

BASE_COLUMNS = [
    "temperature_c",
    "vibration_mm_s",
    "current_a",
    "ambient_temperature_c",
    "humidity_percent",
    "running",
]

INSTANT_FEATURES = ["cycle"] + BASE_COLUMNS

WINDOW_FEATURES = BASE_COLUMNS + [
    f"{sensor}_{stat}"
    for sensor in SENSORS
    for stat in ("mean", "std", "trend")
]

FEATURE_SETS = {
    "instant": INSTANT_FEATURES,
    "window": WINDOW_FEATURES,
}


def _mean(series):
    return series.rolling(WINDOW, min_periods=1).mean()


def _std(series):
    return series.rolling(WINDOW, min_periods=2).std().fillna(0.0)


def _trend(series):
    """Media da metade recente da janela menos a media da
    metade anterior: positiva quando o sinal esta subindo."""

    half = WINDOW // 2
    recent = series.rolling(half, min_periods=1).mean()
    older = series.shift(half).rolling(half, min_periods=1).mean()
    return (recent - older).fillna(0.0)


STATS = {"mean": _mean, "std": _std, "trend": _trend}


def build_features(df, feature_set, group_column=None):
    """Recebe leituras em ordem cronologica e devolve a matriz
    de atributos (float32) na ordem de FEATURE_SETS[feature_set].

    - Treino: varios motores no mesmo DataFrame -> group_column.
    - Inferencia: as ultimas leituras de um motor, sem grupo.
    Valores ausentes ficam como NaN (o HistGradientBoosting
    trata NaN de forma nativa)."""

    columns = FEATURE_SETS[feature_set]
    out = pd.DataFrame(index=df.index)

    for column in BASE_COLUMNS + (["cycle"] if feature_set == "instant" else []):
        out[column] = pd.to_numeric(df[column], errors="coerce")

    if feature_set == "window":
        for sensor in SENSORS:
            values = pd.to_numeric(df[sensor], errors="coerce")

            for stat, function in STATS.items():
                if group_column:
                    result = values.groupby(
                        df[group_column], sort=False
                    ).transform(function)
                else:
                    result = function(values)

                out[f"{sensor}_{stat}"] = result

    return out[columns].astype("float32")


def latest_features(readings, feature_set):
    """Inferencia: atributos da leitura mais recente a partir
    das ultimas leituras de um motor (lista de dicionarios)."""

    df = pd.DataFrame(list(readings)[-WINDOW:])
    return build_features(df, feature_set).iloc[[-1]]


def clip_prediction(name, values):
    values = np.asarray(values, dtype="float64")

    if name == "health":
        return np.clip(values, 0, 100)

    return np.maximum(values, 0)
