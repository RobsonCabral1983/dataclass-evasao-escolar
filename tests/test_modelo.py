"""O modelo salvo reproduz as métricas do relatório (mesma base, divisão 80/20 estratificada, semente 42)."""
import os

import pandas as pd
import pytest
from sklearn.metrics import f1_score, recall_score
from sklearn.model_selection import train_test_split

import pipeline
from conftest import RAIZ

ORDEM = ["Risco Alto", "Risco Médio", "Risco Baixo"]


@pytest.fixture(scope="module")
def base():
    df = pd.read_csv(os.path.join(RAIZ, "dados", "processado", "dataset_explorado.csv"))
    X = pipeline.montar_atributos(df)
    y = df["risco"]
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)


def test_divisao_treino_teste(base):
    X_train, X_test, _, _ = base
    assert (len(X_train), len(X_test)) == (3539, 885)


def test_o_app_replica_os_atributos_dos_notebooks(base, modelo_config):
    """montar_atributos (app) deve dar os mesmos 6 atributos usados no treino."""
    _, config = modelo_config
    df = pd.read_csv(os.path.join(RAIZ, "dados", "processado", "dataset_explorado.csv"))
    esperado = df[["taxa_aprovacao_1sem", "taxa_aprovacao_2sem"]].fillna(0)
    atributos = pipeline.montar_atributos(df)
    pd.testing.assert_frame_equal(atributos[esperado.columns], esperado, check_dtype=False)
    assert list(atributos[config["atributos"]].columns) == config["atributos"]


def test_recall_de_risco_alto_e_f1_macro_do_relatorio(base, modelo_config):
    modelo, config = modelo_config
    _, X_test, _, y_test = base
    pred = modelo.predict(X_test[config["atributos"]])
    recall = recall_score(y_test, pred, labels=["Risco Alto"], average="macro")
    f1 = f1_score(y_test, pred, labels=ORDEM, average="macro")
    assert round(recall, 3) == 0.662 == config["recall_risco_alto_teste"]
    assert round(f1, 3) == 0.638 == config["f1_macro_teste"]


def test_estrutura_do_modelo(modelo_config):
    modelo, config = modelo_config
    assert config["modelo"] == "Regressão Logística"
    assert list(modelo.named_steps) == ["scaler", "clf"]
    assert set(modelo.named_steps["clf"].classes_) == set(ORDEM)
    assert modelo.named_steps["clf"].class_weight == "balanced"
