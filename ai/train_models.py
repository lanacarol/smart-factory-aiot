
import argparse
import json
import os
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

# Codigo unico de atributos, compartilhado com a inferencia.
from features import FEATURE_SETS, WINDOW, build_features, clip_prediction


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "datasets" / "factory_synthetic.csv"
DATASET_INFO = BASE_DIR / "datasets" / "factory_synthetic.json"
MODEL_DIR = BASE_DIR / "models"

SEED = 42

TARGETS = {
    "rul": "rul_cycles",
    "health": "health_percent"
}


def progresso(valor, etapa):
    print(f"Progresso: {valor:.0f}% | {etapa}", flush=True)


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


def amostrar(df, limite, seed):
    if len(df) <= limite:
        return df

    return df.sample(
        n=limite,
        random_state=seed
    )


def proxima_versao():
    """1.0.0 -> 1.1.0 -> 1.2.0 ..."""

    try:
        atual = json.loads(
            (MODEL_DIR / "metadata.json").read_text(encoding="utf-8")
        ).get("model_version", "1.0.0")
        major, minor, _ = (int(p) for p in atual.split("."))
        return f"{major}.{minor + 1}.0"
    except (OSError, ValueError):
        return "1.0.0"


def salvar_atomico(path, escrever):
    """Escreve em arquivo temporario e troca no final, para a
    inferencia nunca ler um arquivo pela metade."""

    tmp = path.with_name(path.name + ".tmp")
    escrever(tmp)
    os.replace(tmp, path)


def main(args):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    feature_set = "window" if args.window_features else "instant"
    features = FEATURE_SETS[feature_set]

    print("=" * 60)
    print("SMART FACTORY - TREINAMENTO DE IA")
    print("=" * 60)
    print(f"Atributos: {feature_set} ({len(features)})")
    print(f"max_iter={args.max_iter} learning_rate={args.learning_rate} "
          f"max_leaf_nodes={args.max_leaf_nodes} linhas={args.train_rows:,}")

    if not DATASET.exists():
        raise FileNotFoundError(
            f"Dataset nao encontrado: {DATASET}"
        )

    progresso(2, "Carregando dataset")

    df = pd.read_csv(
        DATASET,
        dtype={
            "device_id": "string",
            "cycle": "int32",
            "running": "bool",
            "failure": "int8"
        }
    )

    df = df.sort_values(["device_id", "cycle"], kind="stable")

    print(f"Registros carregados: {len(df):,}")
    print(f"Motores encontrados: {df['device_id'].nunique()}")

    progresso(10, "Calculando atributos")

    # As janelas sao calculadas por motor, em ordem de ciclo,
    # ANTES da amostragem (cada linha usa o passado do proprio motor).
    X_all = build_features(df, feature_set, group_column="device_id")

    # Separacao POR EQUIPAMENTO, nunca por linhas.
    rng = np.random.default_rng(SEED)

    motor_ids = df["device_id"].unique().to_numpy()
    rng.shuffle(motor_ids)

    total_motors = len(motor_ids)

    if total_motors < 10:
        raise ValueError(
            "Use pelo menos 10 motores para divisao por equipamento."
        )

    n_test = max(1, round(total_motors * 0.15))
    n_val = max(1, round(total_motors * 0.15))

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
    train_sample = amostrar(train_df, args.train_rows, SEED)
    val_sample = amostrar(val_df, 30_000, SEED + 1)
    test_sample = amostrar(test_df, 30_000, SEED + 2)

    X_train = X_all.loc[train_sample.index]
    X_val = X_all.loc[val_sample.index]
    X_test = X_all.loc[test_sample.index]

    version = proxima_versao()
    resultados = {}
    modelos = {}

    for indice, (name, target) in enumerate(TARGETS.items()):
        base = 20 + indice * 40

        print("\n" + "=" * 60)
        print(f"TREINANDO MODELO: {name.upper()}")
        print("=" * 60)
        progresso(base, f"Treinando modelo {name.upper()}")

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
            max_iter=args.max_iter,
            max_leaf_nodes=args.max_leaf_nodes,
            learning_rate=args.learning_rate,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=SEED
        )

        model.fit(X_train, y_train)

        progresso(base + 20, f"Avaliando modelo {name.upper()}")

        predictions_val = clip_prediction(name, model.predict(X_val))
        predictions_test = clip_prediction(name, model.predict(X_test))

        val_metrics = avaliar(y_val, predictions_val)
        test_metrics = avaliar(y_test, predictions_test)

        print("\nBASELINE - TESTE:")
        print(baseline_metrics)

        print("\nVALIDACAO:")
        print(val_metrics)

        print("\nTESTE FINAL:")
        print(test_metrics, flush=True)

        # Importancia das variaveis por permutacao.
        # Usa um pequeno subconjunto para ser rapido.
        importance_idx = test_sample.sample(
            n=min(1500, len(test_sample)),
            random_state=SEED
        ).index

        importance = permutation_importance(
            model,
            X_all.loc[importance_idx],
            test_sample.loc[importance_idx, target],
            n_repeats=3,
            scoring="neg_mean_absolute_error",
            random_state=SEED,
            n_jobs=1
        )

        importance_table = pd.DataFrame({
            "feature": features,
            "importance": importance.importances_mean
        }).sort_values(
            "importance",
            ascending=False
        )

        # Amostra previsto x real (conjunto de teste) para o grafico.
        amostra = np.random.default_rng(SEED).choice(
            len(y_test),
            size=min(300, len(y_test)),
            replace=False
        )

        modelos[name] = (model, importance_table)

        resultados[name] = {
            "target": target,
            "model_type": "HistGradientBoostingRegressor",
            "baseline_test": baseline_metrics,
            "validation": val_metrics,
            "test": test_metrics,
            "model_file": f"{name}_model.joblib",
            "importance": [
                {"feature": row.feature, "importance": round(float(row.importance), 4)}
                for row in importance_table.itertuples()
            ],
            "pred_vs_real": [
                [round(float(np.asarray(y_test)[i]), 2),
                 round(float(predictions_test[i]), 2)]
                for i in amostra
            ],
        }

    progresso(92, "Salvando modelos")

    # Salva tudo so depois que os dois modelos terminaram.
    for name, (model, importance_table) in modelos.items():
        salvar_atomico(
            MODEL_DIR / f"{name}_model.joblib",
            lambda tmp, m=model: joblib.dump(m, tmp)
        )

        salvar_atomico(
            MODEL_DIR / f"{name}_importance.csv",
            lambda tmp, t=importance_table: t.to_csv(tmp, index=False)
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
        plt.savefig(MODEL_DIR / f"{name}_importance.png", dpi=150)
        plt.close()

    try:
        dataset_info = json.loads(DATASET_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dataset_info = None

    metadata = {
        "model_version": version,
        "trained_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_rows": int(len(df)),
        "dataset": dataset_info,
        "feature_set": feature_set,
        "window": WINDOW if feature_set == "window" else None,
        "features": features,
        "seed": SEED,
        "params": {
            "max_iter": args.max_iter,
            "learning_rate": args.learning_rate,
            "max_leaf_nodes": args.max_leaf_nodes,
            "train_rows": args.train_rows,
        },
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

    # metadata.json por ultimo: a inferencia recarrega
    # os modelos quando este arquivo muda.
    salvar_atomico(
        MODEL_DIR / "metadata.json",
        lambda tmp: tmp.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    )

    progresso(100, "Concluido")

    print("\n" + "=" * 60)
    print("TREINAMENTO CONCLUIDO!")
    print("=" * 60)
    print(f"Versao: {version}")
    print("Modelos: rul_model.joblib e health_model.joblib")
    print("Metricas: metadata.json")
    print("Graficos: rul_importance.png e health_importance.png")
    print("RESULTADO_JSON: " + json.dumps({
        "model_version": version,
        "feature_set": feature_set,
        "metrics": {
            name: {"test": info["test"], "baseline_test": info["baseline_test"]}
            for name, info in resultados.items()
        },
    }), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-iter", type=int, default=120)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--max-leaf-nodes", type=int, default=20)
    parser.add_argument("--train-rows", type=int, default=160_000)
    parser.add_argument(
        "--window-features",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Usa janelas do passado em vez do contador de ciclos"
    )

    main(parser.parse_args())
