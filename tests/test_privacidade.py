"""LGPD: retenção, anonimização, exclusão de aluno e trilha de auditoria (banco/retencao.py e banco/auditoria.py)."""
import pytest

import servico
from banco import auditoria, database, retencao
from conftest import ESCALA_DEMO

ADM = {"id_usuario": 1, "login": "adm", "nome": "Administrador", "perfil": "admin"}


def _envelhecer_resolucoes(caminho, meses):
    """Faz as resoluções existentes parecerem antigas (o prazo é contado desde a confirmação)."""
    with database.conectar(caminho) as c:
        c.execute("UPDATE divergencias_resolvidas SET resolvido_em = datetime('now', ?)", (f"-{meses} months",))


@pytest.fixture
def banco_com_saida(banco_com_envio, planilha, modelo_config):
    """T-003 saiu da escola (ausente no 2º envio, conferido como 'Saiu da escola'), com ação pedagógica e registro na trilha."""
    caminho = banco_com_envio
    modelo, config = modelo_config
    ids = {v["matricula"]: v["id_aluno"] for v in database.buscar_visao_geral(caminho)}
    database.registrar_acao(ids["T-003"], "2026-09-01", "Conversa", "Texto sensível.", "Ana (prof.ana)", caminho)
    auditoria.registrar("ficha_aluno", ADM, aluno={"id_aluno": ids["T-003"], "matricula": "T-003", "nome": "Aluno Três"}, caminho=caminho)
    servico.processar_e_gravar(planilha.iloc[:2], "t2.csv", modelo, config, caminho=caminho, escala_nota_admissao=ESCALA_DEMO)
    database.resolver_divergencias([ids["T-003"]], "Saiu da escola", "Coord (coord)", caminho)
    return caminho, ids


def test_aluno_dentro_do_prazo_nao_e_elegivel(banco_com_saida):
    caminho, _ = banco_com_saida
    assert retencao.listar_elegiveis(caminho=caminho) == []
    assert retencao.anonimizar_alunos(caminho=caminho) == 0


def test_so_quem_saiu_ha_mais_de_12_meses_e_elegivel(banco_com_saida):
    caminho, ids = banco_com_saida
    _envelhecer_resolucoes(caminho, 13)
    elegiveis = retencao.listar_elegiveis(caminho=caminho)
    assert [e["matricula"] for e in elegiveis] == ["T-003"] and "nome" not in elegiveis[0]
    assert retencao.resumo(caminho=caminho)["elegiveis"] == 1


def test_anonimizacao_remove_identificacao_e_mantem_as_avaliacoes(banco_com_saida):
    caminho, ids = banco_com_saida
    _envelhecer_resolucoes(caminho, 13)
    assert retencao.anonimizar_alunos(caminho=caminho, usuario=ADM) == 1
    ficha = database.buscar_ficha_aluno(ids["T-003"], caminho)
    assert ficha["aluno"]["nome"] == retencao.ROTULO_ANONIMO
    assert ficha["aluno"]["matricula"].startswith("ANON-") and ficha["aluno"]["turma"] is None
    assert len(ficha["historico"]) == 1                          # notas e risco ficam, sem identificação
    assert database.buscar_acoes(ids["T-003"], caminho) == []    # texto livre apagado
    trilha = auditoria.listar(caminho=caminho)
    assert all("Aluno Três" not in str(l["nome_aluno"]) and l["matricula"] != "T-003" for l in trilha)
    assert any(l["evento"] == "retencao_anonimizacao" for l in trilha)
    assert retencao.anonimizar_alunos(caminho=caminho) == 0      # não anonimiza duas vezes


def test_anonimizar_respeita_a_lista_de_ids(banco_com_saida):
    caminho, ids = banco_com_saida
    _envelhecer_resolucoes(caminho, 13)
    assert retencao.anonimizar_alunos(ids_aluno=[ids["T-001"]], caminho=caminho) == 0   # T-001 não é elegível
    assert retencao.anonimizar_alunos(ids_aluno=[ids["T-003"]], caminho=caminho) == 1


def test_excluir_aluno_apaga_tudo_e_limpa_a_trilha(banco_com_saida):
    caminho, ids = banco_com_saida
    with pytest.raises(ValueError, match="motivo"):
        retencao.excluir_aluno(ids["T-003"], "  ", ADM, caminho)
    assert retencao.excluir_aluno(ids["T-003"], "Pedido do responsável nº 12", ADM, caminho) is True
    assert database.contar_alunos(caminho) == 2
    ficha = database.buscar_ficha_aluno(ids["T-003"], caminho)
    assert ficha["aluno"] is None and ficha["historico"] == []
    trilha = auditoria.listar(caminho=caminho)
    assert all(l["matricula"] != "T-003" and l["nome_aluno"] != "Aluno Três" for l in trilha)
    assert any(l["evento"] == "aluno_excluido" for l in trilha)
    assert retencao.excluir_aluno(ids["T-003"], "de novo", ADM, caminho) is False


def test_trilha_guarda_quem_fez_o_que_e_quando(caminho):
    auditoria.registrar("login", ADM, caminho=caminho)
    auditoria.registrar("login_falha", login="intruso", detalhe="primeira linha\nsegunda linha", caminho=caminho)
    eventos = auditoria.listar(caminho=caminho)
    assert [e["evento"] for e in eventos] == ["login_falha", "login"]     # do mais recente para o mais antigo
    assert eventos[1]["perfil"] == "admin" and eventos[0]["login"] == "intruso"
    assert eventos[0]["detalhe"] == "primeira linha segunda linha"     # sem quebras de linha
    assert auditoria.contar(login="ADM", caminho=caminho) == 1               # filtro sem diferenciar maiúsculas
    assert auditoria.contar(eventos=["login"], caminho=caminho) == 1
    assert set(auditoria.logins_registrados(caminho)) == {"adm", "intruso"}


def test_limpeza_da_trilha_por_prazo(caminho):
    auditoria.registrar("login", ADM, caminho=caminho)
    with database.conectar(caminho) as c:
        c.execute("UPDATE auditoria SET data_hora = datetime('now', '-13 months')")
    auditoria.registrar("login", ADM, caminho=caminho)
    assert auditoria.resumo_retencao(caminho=caminho)["vencidos"] == 1
    assert auditoria.apagar_anteriores_a(usuario=ADM, caminho=caminho) == 1
    eventos = [e["evento"] for e in auditoria.listar(caminho=caminho)]
    assert eventos == ["auditoria_limpeza", "login"]       # a própria limpeza fica registrada


def test_o_texto_da_trilha_e_limitado(caminho):
    auditoria.registrar("login", ADM, detalhe="x" * 1000, caminho=caminho)
    assert len(auditoria.listar(caminho=caminho)[0]["detalhe"]) == 300
