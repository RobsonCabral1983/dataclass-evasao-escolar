"""Envio de planilhas, histórico, repetição, desfazer e divergências (banco/database.py e app/servico.py)."""
import pandas as pd
import pytest

import servico
from banco import database
from conftest import ESCALA_DEMO


def enviar(df, nome, caminho, modelo_config):
    modelo, config = modelo_config
    return servico.processar_e_gravar(df, nome, modelo, config, caminho=caminho, escala_nota_admissao=ESCALA_DEMO)


def test_envio_grava_alunos_e_avaliacoes(banco_com_envio):
    visao = database.buscar_visao_geral(banco_com_envio)
    assert len(visao) == 3 and database.contar_alunos(banco_com_envio) == 3
    assert {v["risco"] for v in visao} <= {"Risco Alto", "Risco Médio", "Risco Baixo"}
    assert all("nome" not in v for v in visao)          # a visão geral nunca devolve o nome
    assert [p["nome_arquivo_origem"] for p in database.buscar_processamentos(caminho=banco_com_envio)] == ["t1.csv"]


def test_nome_so_aparece_na_ficha(banco_com_envio):
    id_aluno = database.buscar_visao_geral(banco_com_envio)[0]["id_aluno"]
    ficha = database.buscar_ficha_aluno(id_aluno, banco_com_envio)
    assert ficha["aluno"]["nome"].startswith("Aluno") and len(ficha["historico"]) == 1


def test_planilha_com_erro_nao_grava_nada(caminho, planilha, modelo_config):
    planilha.loc[0, "inadimplente"] = 5
    qtd, erros = enviar(planilha, "ruim.csv", caminho, modelo_config)
    assert qtd == 0 and erros and database.contar_alunos(caminho) == 0
    assert database.buscar_processamentos(caminho=caminho) == []


def test_planilha_vazia_e_recusada(caminho, planilha, modelo_config):
    assert enviar(planilha.iloc[0:0], "vazia.csv", caminho, modelo_config) == (0, ["A planilha não tem nenhum aluno."])


def test_mesma_planilha_e_detectada_mesmo_com_outra_ordem_ou_nome(banco_com_envio, planilha):
    caminho = banco_com_envio
    repetida = servico.verificar_repetida(planilha.iloc[::-1], caminho, ESCALA_DEMO)
    assert repetida and repetida["nome_arquivo_origem"] == "t1.csv" and repetida["eh_ultimo"] is True
    planilha.loc[0, "nota_media_1sem"] = 9.0
    assert servico.verificar_repetida(planilha, caminho, ESCALA_DEMO) is None


def test_nova_avaliacao_preserva_o_historico_e_mostra_o_risco_anterior(banco_com_envio, planilha, modelo_config):
    caminho = banco_com_envio
    planilha.loc[0, ["nota_media_2sem", "disciplinas_aprovadas_2sem"]] = [0.0, 0]   # o aluno 1 piora
    assert enviar(planilha, "t2.csv", caminho, modelo_config)[0] == 3
    visao = {v["matricula"]: v for v in database.buscar_visao_geral(caminho)}
    assert visao["T-001"]["risco_anterior"] is not None
    ficha = database.buscar_ficha_aluno(visao["T-001"]["id_aluno"], caminho)
    assert len(ficha["historico"]) == 2


def test_aluno_que_some_vira_divergencia_e_pode_ser_resolvido(banco_com_envio, planilha, modelo_config):
    caminho = banco_com_envio
    enviar(planilha.iloc[:2], "t2.csv", caminho, modelo_config)          # T-003 ficou de fora
    ordem = {"Risco Alto": 1, "Risco Médio": 2, "Risco Baixo": 3}
    riscos = [ordem[v["risco"]] for v in database.buscar_visao_geral(caminho)]
    assert riscos == sorted(riscos)       # a lista vem priorizada: Alto, Médio, Baixo
    assert len(database.buscar_visao_geral(caminho)) == 2
    pendentes = database.buscar_divergencias(caminho)
    assert [d["matricula"] for d in pendentes] == ["T-003"] and "nome" not in pendentes[0]
    ids = [pendentes[0]["id_aluno"]]
    with pytest.raises(ValueError, match="Motivo"):
        database.resolver_divergencias(ids, "porque sim", "Fulano", caminho)
    with pytest.raises(ValueError, match="responsável"):
        database.resolver_divergencias(ids, "Saiu da escola", "  ", caminho)
    assert database.resolver_divergencias(ids, "Saiu da escola", "Coord (coord)", caminho) == 1
    assert database.buscar_divergencias(caminho) == []
    assert database.buscar_divergencias(caminho, incluir_resolvidas=True)[0]["motivo"] == "Saiu da escola"
    assert database.reabrir_divergencias(ids, caminho) == 1 and len(database.buscar_divergencias(caminho)) == 1


def test_aluno_que_volta_reaparece_sozinho(banco_com_envio, planilha, modelo_config):
    caminho = banco_com_envio
    enviar(planilha.iloc[:2], "t2.csv", caminho, modelo_config)
    enviar(planilha, "t3.csv", caminho, modelo_config)
    assert database.buscar_divergencias(caminho) == [] and len(database.buscar_visao_geral(caminho)) == 3


def test_desfazer_ultimo_envio_restaura_o_estado_anterior(banco_com_envio, planilha, modelo_config):
    caminho = banco_com_envio
    novo = planilha.copy()
    novo["nome"] = ["Aluno Um Renomeado", "Aluno Dois", "Aluno Três"]
    extra = planilha.iloc[[0]].assign(matricula="T-999", nome="Aluno Novo")
    novo = pd.concat([novo, extra], ignore_index=True)
    enviar(novo, "t2.csv", caminho, modelo_config)
    assert database.contar_alunos(caminho) == 4
    resumo = database.desfazer_ultimo_processamento(caminho)
    assert resumo["alunos_novos"] == 1 and resumo["alunos_restaurados"] == 1
    assert database.contar_alunos(caminho) == 3
    ids = {v["matricula"]: v["id_aluno"] for v in database.buscar_visao_geral(caminho)}
    assert database.buscar_ficha_aluno(ids["T-001"], caminho)["aluno"]["nome"] == "Aluno Um"   # nome antigo de volta
    assert [p["nome_arquivo_origem"] for p in database.buscar_processamentos(caminho=caminho)] == ["t1.csv"]


def test_desfazer_sem_envios_devolve_none(caminho):
    assert database.desfazer_ultimo_processamento(caminho) is None


def test_atribuicao_de_professores_vale_a_do_ultimo_envio_que_trouxe_a_coluna(banco_com_envio, planilha, modelo_config):
    from banco import usuarios
    caminho = banco_com_envio
    planilha["professores"] = ["prof.carla"] * 3
    enviar(planilha, "t2.csv", caminho, modelo_config)
    assert usuarios.turmas_do_professor("prof.ana", caminho) == [] and usuarios.turmas_do_professor("prof.carla", caminho) == ["1º A", "2º B"]
    database.desfazer_ultimo_processamento(caminho)       # desfeito: voltam as atribuições anteriores
    assert usuarios.turmas_do_professor("prof.ana", caminho) == ["1º A"]


def test_planilha_sem_coluna_de_professores_mantem_as_atribuicoes(banco_com_envio, planilha, modelo_config):
    from banco import usuarios
    enviar(planilha.drop(columns=["professores"]).assign(nota_media_1sem=1.0), "t2.csv", banco_com_envio, modelo_config)
    assert usuarios.turmas_do_professor("prof.ana", banco_com_envio) == ["1º A"]


def test_limpar_dados_mantem_usuarios_e_configuracoes(banco_com_envio):
    from banco import usuarios
    caminho = banco_com_envio
    usuarios.criar_usuario("adm", "Adm", "admin", "senha-forte-123", caminho=caminho)
    database.salvar_limite_frequencia(70, caminho)
    database.limpar_dados(caminho)
    assert database.contar_alunos(caminho) == 0 and database.buscar_processamentos(caminho=caminho) == []
    assert usuarios.contar_usuarios(caminho) == 1 and database.obter_limite_frequencia(caminho) == 70.0


def test_acoes_pedagogicas(banco_com_envio):
    caminho = banco_com_envio
    id_aluno = database.buscar_visao_geral(caminho)[0]["id_aluno"]
    database.registrar_acao(id_aluno, "2026-10-01", "Conversa com a família", "Combinado reforço.", "Ana (prof.ana)", caminho)
    acoes = database.buscar_acoes(id_aluno, caminho)
    assert len(acoes) == 1 and acoes[0]["responsavel"] == "Ana (prof.ana)"
    assert database.buscar_visao_geral(caminho)[0]["ultima_acao"] == "2026-10-01"
    database.excluir_acao(acoes[0]["id_acao"], caminho)
    assert database.buscar_acoes(id_aluno, caminho) == []


def test_configuracoes_com_limites(caminho):
    assert database.obter_limite_frequencia(caminho) == 75.0 and database.obter_escala_nota_admissao(caminho) == 100.0
    assert database.salvar_limite_frequencia("80", caminho) == 80.0 and database.obter_limite_frequencia(caminho) == 80.0
    assert database.salvar_escala_nota_admissao(200, caminho) == 200.0
    for valor in (0, 101):
        with pytest.raises(ValueError):
            database.salvar_limite_frequencia(valor, caminho)
    for valor in (0, 1001):
        with pytest.raises(ValueError):
            database.salvar_escala_nota_admissao(valor, caminho)


def test_frequencias_por_avaliacao(banco_com_envio, planilha, modelo_config):
    caminho = banco_com_envio
    planilha["frequencia_pct"] = [70.0, 65.0, None]
    enviar(planilha, "t2.csv", caminho, modelo_config)
    por_aluno = database.buscar_frequencias(caminho)
    ids = {v["matricula"]: v["id_aluno"] for v in database.buscar_visao_geral(caminho)}
    assert por_aluno[ids["T-001"]] == [92.0, 70.0] and por_aluno[ids["T-003"]] == [80.0, None]


def test_banco_antigo_e_migrado_sem_perder_dados(tmp_path):
    """Um banco de versão antiga (sem as colunas e tabelas novas) é atualizado ao ser aberto, sem perder dados."""
    import sqlite3
    caminho = str(tmp_path / "antigo.db")
    con = sqlite3.connect(caminho)
    con.executescript("""
        CREATE TABLE alunos (id_aluno INTEGER PRIMARY KEY AUTOINCREMENT, matricula TEXT NOT NULL UNIQUE, nome TEXT NOT NULL,
                             turma TEXT, curso TEXT, data_cadastro TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE avaliacoes_risco (id_avaliacao INTEGER PRIMARY KEY AUTOINCREMENT, id_aluno INTEGER NOT NULL,
                             data_avaliacao TEXT NOT NULL DEFAULT (datetime('now')), nota_admissao REAL, nota_1sem REAL, nota_2sem REAL,
                             taxa_aprovacao_1sem REAL, taxa_aprovacao_2sem REAL, indicador_socioeconomico REAL,
                             risco TEXT NOT NULL, modelo_versao TEXT);
        CREATE TABLE processamentos (id_processamento INTEGER PRIMARY KEY AUTOINCREMENT, data_hora TEXT NOT NULL DEFAULT (datetime('now')),
                             nome_arquivo_origem TEXT, quantidade_alunos INTEGER);
        INSERT INTO alunos (matricula, nome) VALUES ('A1', 'Antigo');
        INSERT INTO avaliacoes_risco (id_aluno, risco) VALUES (1, 'Risco Alto');
    """)
    con.commit()
    con.close()
    with database.conectar(caminho) as c:
        assert {"anonimizado_em"} <= {l["name"] for l in c.execute("PRAGMA table_info(alunos)")}
        assert {"id_processamento", "frequencia_pct"} <= {l["name"] for l in c.execute("PRAGMA table_info(avaliacoes_risco)")}
        assert {"hash_conteudo", "periodo_referencia"} <= {l["name"] for l in c.execute("PRAGMA table_info(processamentos)")}
        assert c.execute("SELECT nome FROM alunos").fetchone()[0] == "Antigo"
        assert c.execute("SELECT risco FROM avaliacoes_risco").fetchone()[0] == "Risco Alto"
        tabelas = {l[0] for l in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "auditoria", "turmas_professores", "divergencias_resolvidas", "acoes_pedagogicas", "configuracoes"} <= tabelas
