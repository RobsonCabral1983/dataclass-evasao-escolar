"""Permissões por perfil (app/permissoes.py)."""
import pandas as pd
import pytest

import permissoes

ADMIN = {"perfil": "admin", "nome": "Adm", "login": "adm"}
COORD = {"perfil": "coordenacao", "nome": "Coord", "login": "coord"}
PROF = {"perfil": "professor", "nome": "Ana", "login": "prof.ana", "turmas": ["1º A"]}


def test_telas_por_perfil():
    assert set(permissoes.telas_permitidas(ADMIN)) == set(permissoes.TODAS_AS_TELAS)
    assert "Usuários" not in permissoes.telas_permitidas(COORD) and "Auditoria" not in permissoes.telas_permitidas(COORD)
    assert "Upload de dados" in permissoes.telas_permitidas(COORD)
    assert permissoes.telas_permitidas(PROF) == ["Visão geral", "Lista priorizada", "Ficha do aluno", "Relatórios", "Minha conta"]


@pytest.mark.parametrize("usuario", [None, {}, {"perfil": "desconhecido"}])
def test_sem_perfil_valido_nao_pode_nada(usuario):
    assert permissoes.telas_permitidas(usuario) == []
    assert not any(permissoes.pode(usuario, a) for a in permissoes._ACOES)


@pytest.mark.parametrize("acao,admin,coord,prof", [
    ("ver_todos_os_alunos", True, True, False),
    ("enviar_planilha", True, True, False),
    ("desfazer_envios", True, True, False),
    ("apagar_dados", True, False, False),
    ("configuracoes", True, False, False),
    ("gerenciar_usuarios", True, False, False),
    ("ver_auditoria", True, False, False),
    ("gerenciar_retencao", True, False, False),
    ("registrar_acao_pedagogica", True, True, True),
])
def test_acoes_por_perfil(acao, admin, coord, prof):
    assert (permissoes.pode(ADMIN, acao), permissoes.pode(COORD, acao), permissoes.pode(PROF, acao)) == (admin, coord, prof)


def test_acao_inexistente_e_negada():
    assert not permissoes.pode(ADMIN, "acao_que_nao_existe")


@pytest.fixture
def visao():
    return pd.DataFrame({"matricula": ["1", "2", "3"], "turma": ["1º A", "2º B", None]})


def test_professor_ve_so_as_proprias_turmas(visao):
    assert permissoes.restringir_alunos(visao, PROF)["matricula"].tolist() == ["1"]


def test_professor_sem_turmas_nao_ve_ninguem(visao):
    assert permissoes.restringir_alunos(visao, {**PROF, "turmas": []}).empty


def test_coordenacao_e_admin_veem_todos(visao):
    assert len(permissoes.restringir_alunos(visao, COORD)) == 3
    assert len(permissoes.restringir_alunos(visao, ADMIN)) == 3


def test_identificacao():
    assert permissoes.identificacao(PROF) == "Ana (prof.ana)"
