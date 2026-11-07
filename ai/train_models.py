
import json
from pathlib import Path
from datetime import datetime, timezone

import joblib
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "datasets" / "factory_synthetic.csv"
MODEL_DIR = BASE_DIR / "models"

SEED = 42

FEATURES = [
    "cycle",
    "temperature_c",
    "vibration_mm_s",
    "current_a",
    "ambient_temperature_c",
    "humidity_percent",
    "running"
]

TARGETS = {
    "rul": "rul_cycles",
    "health": "health_percent"
}


def avaliar(y_true, y_pred):
    return {
        "MAE": round(float(
            mean_absolute_error(y_true, y_pred)
        ), 4),
        "RMSE": round(float(
            np.sqrt(mean_squared_error(y_true, y_pred))
        ), 4),
        "R2": round(float(
            r2_score(y_true, y_pred)
        ), 4)
    }


def limitar_previsao(name, values):
    values = np.asarray(values)

    if name == "health":
        return np.clip(values, 0, 100)

    return np.maximum(values, 0)


def amostrar(df, limite, seed):
    if len(df) <= limite:
        return df

    return df.sample(
        n=limite,
        random_state=seed
    )


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("SMART FACTORY - TREINAMENTO DE IA")
    print("=" * 60)

    if not DATASET.exists():
        raise FileNotFoundError(
            f"Dataset nao encontrado: {DATASET}"
        )

    print("\nCarregando dataset...")

    df = pd.read_csv(
        DATASET,
        dtype={
            "device_id": "string",
            "cycle": "int32",
            "running": "bool",
            "failure": "int8"
        }
    )

    print(f"Registros carregados: {len(df):,}")
    print(f"Motores encontrados: {df['device_id'].nunique()}")

    # Separacao POR EQUIPAMENTO, nunca por linhas.
    rng = np.random.default_rng(SEED)

    motor_ids = df["device_id"].unique().to_numpy()
    rng.shuffle(motor_ids)

    total_motors = len(motor_ids)

    n_test = max(1, round(total_motors * 0.15))
    n_val = max(1, round(total_motors * 0.15))

    if total_motors < 10:
        raise ValueError(
            "Use pelo menos 10 motores para divisao por equipamento."
        )

    test_ids = motor_ids[:n_test]
    val_ids = motor_ids[n_test:n_test + n_val]
    train_ids = motor_ids[n_test + n_val:]

    train_df = df[df["device_id"].isin(train_ids)]
    val_df = df[df["device_id"].isin(val_ids)]
    test_df = df[df["device_id"].isin(test_ids)]

    print("\nDivisao por motor:")
    print(f"Treinamento: {len(train_ids)} motores / {len(train_df):,} linhas")
    print(f"Validacao:   {len(val_ids)} motores / {len(val_df):,} linhas")
    print(f"Teste:       {len(test_ids)} motores / {len(test_df):,} linhas")

    assert not (set(train_ids) & set(val_ids))
    assert not (set(train_ids) & set(test_ids))
    assert not (set(val_ids) & set(test_ids))

    # Amostragem apenas para acelerar o treinamento.
    # A separacao por motores foi feita antes.
    train_sample = amostrar(train_df, 160_000, SEED)
    val_sample = amostrar(val_df, 30_000, SEED + 1)
    test_sample = amostrar(test_df, 30_000, SEED + 2)

    print("\nAmostras usadas na avaliacao:")
    print(f"Treino: {len(train_sample):,}")
    print(f"Validacao: {len(val_sample):,}")
    print(f"Teste: {len(test_sample):,}")

    X_train = train_sample[FEATURES].astype("float32")
    X_val = val_sample[FEATURES].astype("float32")
    X_test = test_sample[FEATURES].astype("float32")

    resultados = {}

    for name, target in TARGETS.items():
        print("\n" + "=" * 60)
        print(f"TREINANDO MODELO: {name.upper()}")
        print("=" * 60)

        y_train = train_sample[target]
        y_val = val_sample[target]
        y_test = test_sample[target]

        # Baseline: sempre prever a media do treino.
        baseline_value = float(y_train.mean())
        baseline_pred = np.full(
            len(y_test),
            baseline_value
        )

        baseline_metrics = avaliar(
            y_test,
            baseline_pred
        )

        model = HistGradientBoostingRegressor(
            max_iter=120,
            max_leaf_nodes=20,
            learning_rate=0.08,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=SEED
        )

        model.fit(X_train, y_train)

        predictions_val = limitar_previsao(
            name,
            model.predict(X_val)
        )

        predictions_test = limitar_previsao(
            name,
            model.predict(X_test)
        )

        val_metrics = avaliar(
            y_val,
            predictions_val
        )

        test_metrics = avaliar(
            y_test,
            predictions_test
        )

        print("\nBASELINE - TESTE:")
        print(baseline_metrics)

        print("\nVALIDACAO:")
        print(val_metrics)

        print("\nTESTE FINAL:")
        print(test_metrics)

        model_path = MODEL_DIR / f"{name}_model.joblib"

        joblib.dump(
            model,
            model_path
        )

        print(f"\nModelo salvo: {model_path}")

        # Importancia das variaveis por permutacao.
        # Usa um pequeno subconjunto para ser rapido.
        importance_df = test_sample.sample(
            n=min(1500, len(test_sample)),
            random_state=SEED
        )

        X_importance = (
            importance_df[FEATURES]
            .astype("float32")
        )

        y_importance = importance_df[target]

        importance = permutation_importance(
            model,
            X_importance,
            y_importance,
            n_repeats=3,
            scoring="neg_mean_absolute_error",
            random_state=SEED,
            n_jobs=1
        )

        importance_table = pd.DataFrame({
            "feature": FEATURES,
            "importance": importance.importances_mean
        }).sort_values(
            "importance",
            ascending=False
        )

        importance_table.to_csv(
            MODEL_DIR / f"{name}_importance.csv",
            index=False
        )

        # Grafico para a apresentacao.
        plt.figure(figsize=(9, 5))

        plt.barh(
            importance_table["feature"][::-1],
            importance_table["importance"][::-1]
        )

        plt.xlabel("Aumento no MAE ao embaralhar a variavel")
        plt.title(f"Importancia das variaveis - {name.upper()}")
        plt.tight_layout()

        plt.savefig(
            MODEL_DIR / f"{name}_importance.png",
            dpi=150
        )
        plt.close()

        resultados[name] = {
            "target": target,
            "model_type": "HistGradientBoostingRegressor",
            "baseline_test": baseline_metrics,
            "validation": val_metrics,
            "test": test_metrics,
            "model_file": model_path.name
        }

    metadata = {
        "model_version": "1.0.0",
        "trained_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_rows": int(len(df)),
        "features": FEATURES,
        "seed": SEED,
        "split": {
            "train_motors": len(train_ids),
            "validation_motors": len(val_ids),
            "test_motors": len(test_ids),
            "train_rows_used": len(train_sample),
            "validation_rows_used": len(val_sample),
            "test_rows_used": len(test_sample)
        },
        "targets": resultados
    }

    with open(
        MODEL_DIR / "metadata.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metadata,
            file,
            indent=2,
            ensure_ascii=False
        )

    print("\n" + "=" * 60)
    print("TREINAMENTO CONCLUIDO!")
    print("=" * 60)
    print("Modelos: rul_model.joblib e health_model.joblib")
    print("Metricas: metadata.json")
    print("Graficos: rul_importance.png e health_importance.png")


if __name__ == "__main__":
    main()
