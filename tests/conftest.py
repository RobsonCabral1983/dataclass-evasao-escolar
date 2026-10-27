"""Configuração comum dos testes: caminhos do projeto e um banco SQLite novo (temporário) para cada teste."""
import os
import sys

import pandas as pd
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for pasta in (RAIZ, os.path.join(RAIZ, "app")):
    if pasta not in sys.path:
        sys.path.insert(0, pasta)

DEMO = os.path.join(RAIZ, "dados", "demo")
ESCALA_DEMO = 100.0   # escala da nota de admissão nos CSVs de demonstração


@pytest.fixture
def caminho(tmp_path):
    """Caminho de um banco novo e vazio (criado sozinho na primeira conexão)."""
    return str(tmp_path / "teste.db")


@pytest.fixture(scope="session")
def modelo_config():
    import pipeline
    return pipeline.carregar_modelo()


@pytest.fixture
def planilha():
    """Planilha mínima válida (nomes em português), com 3 alunos e dois professores."""
    return pd.DataFrame({
        "matricula": ["T-001", "T-002", "T-003"],
        "nome": ["Aluno Um", "Aluno Dois", "Aluno Três"],
        "turma": ["1º A", "1º A", "2º B"],
        "curso": ["Técnico em Informática"] * 3,
        "nota_admissao": [70.0, 55.0, 90.0],
        "nota_media_1sem": [14.0, 8.0, 0.0],
        "nota_media_2sem": [13.5, 0.0, 0.0],
        "disciplinas_aprovadas_1sem": [6, 2, 0],
        "disciplinas_cursadas_1sem": [6, 6, 0],
        "disciplinas_aprovadas_2sem": [6, 0, 0],
        "disciplinas_cursadas_2sem": [6, 6, 0],
        "inadimplente": [0, 1, 0],
        "mensalidade_em_dia": [1, 0, 1],
        "bolsista": [0, 0, 1],
        "frequencia_pct": [92.0, 60.0, 80.0],
        "professores": ["prof.ana", "prof.ana;prof.bruno", "prof.bruno"],
    })


@pytest.fixture
def banco_com_envio(caminho, planilha, modelo_config):
    """Banco com a planilha mínima já processada."""
    import servico
    modelo, config = modelo_config
    qtd, erros = servico.processar_e_gravar(planilha, "t1.csv", modelo, config, caminho=caminho, escala_nota_admissao=ESCALA_DEMO)
    assert erros == [] and qtd == 3
    return caminho
