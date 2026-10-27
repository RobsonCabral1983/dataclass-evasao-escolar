"""Validação de planilhas, engenharia de atributos e previsão (app/pipeline.py)."""
import os

import numpy as np
import pandas as pd
import pytest

import pipeline
from conftest import DEMO, ESCALA_DEMO, RAIZ

ROTULOS = {"Risco Alto", "Risco Médio", "Risco Baixo"}


def test_planilha_valida_passa_e_converte_a_escala(planilha):
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert erros == []
    # 0-100 -> 0-200 (escala do modelo)
    assert df["Admission grade"].tolist() == [140.0, 110.0, 180.0]


def test_cabecalhos_em_ingles_e_com_acento_sao_aceitos(planilha):
    ingles = planilha.rename(columns=pipeline.NOME_PT).rename(columns={"matricula": " Matrícula "})
    df, erros = pipeline.validar_planilha(ingles, escala_nota_admissao=100.0)
    assert erros == [] and len(df) == 3


def test_coluna_em_portugues_e_ingles_ao_mesmo_tempo_e_erro(planilha):
    planilha["Admission grade"] = 100.0
    df, erros = pipeline.validar_planilha(planilha)
    assert df is None and "mais de uma vez" in erros[0]


def test_colunas_ausentes_sao_listadas(planilha):
    df, erros = pipeline.validar_planilha(planilha.drop(columns=["bolsista", "nota_media_1sem"]))
    assert df is None
    assert "bolsista" in erros[0] and "nota_media_1sem" in erros[0]


@pytest.mark.parametrize("coluna,valor,trecho", [
    ("matricula", "", "sem matrícula"),
    ("nome", "", "sem nome"),
    ("nota_media_1sem", "abc", "não numéricos"),
    ("inadimplente", 2, "apenas 0 ou 1"),
    ("disciplinas_aprovadas_1sem", -1, "negativos"),
    ("frequencia_pct", 130, "entre 0 e 100"),
    ("professores", "Prof Ana!", "logins inválidos"),
])
def test_valores_invalidos_geram_erro_e_nada_e_devolvido(planilha, coluna, valor, trecho):
    planilha[coluna] = planilha[coluna].astype(object)
    planilha.loc[0, coluna] = valor
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert df is None
    assert any(trecho in e for e in erros), erros


def test_matriculas_duplicadas_sao_recusadas(planilha):
    planilha.loc[1, "matricula"] = "T-001"
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert df is None and any("duplicadas" in e for e in erros)


def test_nota_de_admissao_fora_da_escala_e_recusada(planilha):
    planilha.loc[0, "nota_admissao"] = 150.0   # escala 0-100
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert df is None and any("nota_admissao" in e for e in erros)


def test_sugestao_de_escala():
    df = pd.DataFrame({"Admission grade": [120.0, 190.0]})
    assert pipeline.sugerir_escala(df, 100.0) == 200.0
    assert pipeline.sugerir_escala(df, 200.0) is None
    assert pipeline.sugerir_escala(pd.DataFrame({"Admission grade": [5.0, 9.5]}), 5.0) == 10.0


def test_frequencia_aceita_virgula_e_porcentagem(planilha):
    planilha["frequencia_pct"] = ["85,5", "60%", ""]
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert erros == []
    assert df["frequencia_pct"].iloc[:2].tolist() == [85.5, 60.0] and np.isnan(df["frequencia_pct"].iloc[2])


def test_professores_sao_normalizados(planilha):
    planilha["professores"] = [" Prof.Ana , prof.bruno", "", None]
    df, erros = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    assert erros == []
    assert df["professores"].tolist() == ["prof.ana;prof.bruno", "", ""]


def test_avisos_de_planilha_sem_turma_curso_e_frequencia(planilha):
    df, _ = pipeline.validar_planilha(planilha.drop(columns=["turma", "curso", "frequencia_pct"]), escala_nota_admissao=100.0)
    avisos = " ".join(pipeline.avisos_planilha(pipeline.normalizar_colunas(planilha.drop(columns=["turma", "curso", "frequencia_pct"]))[0], 100.0))
    assert "turma" in avisos and "curso" in avisos and "frequencia_pct" in avisos


def test_aviso_de_frequencia_em_fracao(planilha):
    planilha["frequencia_pct"] = [0.9, 0.6, 0.8]
    df, _ = pipeline.normalizar_colunas(planilha)
    assert any("entre 0 e 1" in a for a in pipeline.avisos_planilha(df, 100.0))


def test_taxa_de_aprovacao_com_zero_matriculas_vira_zero(planilha):
    df, _ = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    atr = pipeline.montar_atributos(df)
    assert atr["taxa_aprovacao_1sem"].tolist() == [1.0, pytest.approx(2 / 6), 0.0]
    assert not atr.isna().any().any()


def test_indicador_socioeconomico_usa_pesos_3_2_1(planilha):
    df, _ = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    ind = pipeline.montar_atributos(df)["indicador_socioeconomico"].tolist()
    # aluno 1: nada pendente, sem bolsa -> 1; aluno 2: inadimplente(3) + mensalidade(2) + sem bolsa(1) = 6; aluno 3: bolsista -> 0
    assert ind == [1, 6, 0]


def test_previsao_devolve_so_os_tres_rotulos(planilha, modelo_config):
    modelo, config = modelo_config
    df, _ = pipeline.validar_planilha(planilha, escala_nota_admissao=100.0)
    atributos, riscos = pipeline.prever(df, modelo, config)
    assert list(atributos.columns) == config["atributos"]
    assert set(riscos) <= ROTULOS


def test_aluno_com_notas_altas_e_sem_pendencias_tem_risco_baixo_e_o_oposto_alto(modelo_config):
    modelo, config = modelo_config
    atr = pd.DataFrame([
        [150.0, 15.0, 15.0, 1.0, 1.0, 0],   # bom desempenho
        [110.0, 0.0, 0.0, 0.0, 0.0, 6],     # nada aprovado, pendências
    ], columns=config["atributos"])
    assert list(modelo.predict(atr)) == ["Risco Baixo", "Risco Alto"]


def test_probabilidades_somam_um(modelo_config):
    modelo, config = modelo_config
    atr = pd.DataFrame([[130.0, 12.0, 11.0, 0.8, 0.7, 1]], columns=config["atributos"])
    p = pipeline.probabilidades(atr, modelo)
    assert set(p.columns) == ROTULOS and p.sum(axis=1).iloc[0] == pytest.approx(1.0)


def test_contribuicoes_apontam_a_taxa_de_aprovacao_como_fator_dominante(modelo_config):
    modelo, config = modelo_config
    linha = [110.0, 0.0, 0.0, 0.0, 0.0, 6]
    tabela = pipeline.contribuicoes(linha, modelo, config)
    assert len(tabela) == 6 and tabela["contribuicao"].abs().is_monotonic_decreasing
    # a soma das contribuições mais o intercepto é o logit da classe
    clf = modelo.named_steps["clf"]
    idx = list(clf.classes_).index("Risco Alto")
    logit = tabela["contribuicao"].sum() + clf.intercept_[idx]
    esperado = modelo.decision_function(pd.DataFrame([linha], columns=config["atributos"]))[0][idx]
    assert logit == pytest.approx(esperado)


@pytest.mark.parametrize("arquivo", ["demo_1_base_inicial.csv", "demo_2_nova_avaliacao.csv",
                                     "demo_4_planilha_corrigida.csv", "modelo_planilha.csv"])
def test_planilhas_de_demonstracao_sao_validas(arquivo):
    df = pd.read_csv(os.path.join(DEMO, arquivo))
    ok, erros = pipeline.validar_planilha(df, ESCALA_DEMO)
    assert erros == [] and len(ok) == len(df)


def test_dados_de_demonstracao_sao_ficticios():
    df = pd.read_csv(os.path.join(DEMO, "demo_1_base_inicial.csv"))
    assert df["matricula"].str.startswith("DEMO-").all()
    assert len(df) == 4424
