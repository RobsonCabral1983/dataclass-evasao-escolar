"""
Funções de acesso ao banco de dados do projeto (escola.db).

O dashboard em Streamlit (pasta app/) e os notebooks de modelagem devem
chamar essas funções em vez de escrever SQL espalhado pelo código.

Convenção de segurança: funções que lidam com avaliações de risco recebem
e devolvem só id_aluno, nunca nome — o cruzamento com o nome só acontece
explicitamente em buscar_ficha_aluno(), usada na tela "Ficha do aluno".
"""

import sqlite3
import os
from contextlib import contextmanager

try:  # uso como pacote (from banco import database)
    from .criar_banco import CAMINHO_BANCO, criar_banco, migrar
except ImportError:  # uso como script dentro da pasta banco/
    from criar_banco import CAMINHO_BANCO, criar_banco, migrar

MODELO_VERSAO_ATUAL = "regressao_logistica_v1"


@contextmanager
def conectar(caminho=CAMINHO_BANCO):
    if not os.path.exists(caminho):
        criar_banco(caminho)
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    try:
        migrar(conexao)  # bancos de versões antigas ganham as colunas novas (idempotente)
        yield conexao
        conexao.commit()
    finally:
        conexao.close()


def inserir_ou_atualizar_aluno(matricula, nome, turma=None, curso=None, caminho=CAMINHO_BANCO):
    """Garante que o aluno existe em `alunos` e devolve o id_aluno interno."""
    with conectar(caminho) as conexao:
        linha = conexao.execute(
            "SELECT id_aluno FROM alunos WHERE matricula = ?", (matricula,)
        ).fetchone()
        if linha:
            conexao.execute(
                "UPDATE alunos SET nome = ?, turma = ?, curso = ? WHERE id_aluno = ?",
                (nome, turma, curso, linha["id_aluno"]),
            )
            return linha["id_aluno"]

        cursor = conexao.execute(
            "INSERT INTO alunos (matricula, nome, turma, curso) VALUES (?, ?, ?, ?)",
            (matricula, nome, turma, curso),
        )
        return cursor.lastrowid


def inserir_avaliacao(id_aluno, atributos, risco, modelo_versao=MODELO_VERSAO_ATUAL, caminho=CAMINHO_BANCO):
    """
    Registra uma nova avaliação de risco para o aluno (sempre insere uma
    linha nova — nunca sobrescreve — para preservar o histórico).

    `atributos` é um dicionário com as chaves: nota_admissao, nota_1sem,
    nota_2sem, taxa_aprovacao_1sem, taxa_aprovacao_2sem, indicador_socioeconomico.
    """
    with conectar(caminho) as conexao:
        conexao.execute(
            """
            INSERT INTO avaliacoes_risco (
                id_aluno, nota_admissao, nota_1sem, nota_2sem,
                taxa_aprovacao_1sem, taxa_aprovacao_2sem,
                indicador_socioeconomico, risco, modelo_versao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id_aluno,
                atributos.get("nota_admissao"),
                atributos.get("nota_1sem"),
                atributos.get("nota_2sem"),
                atributos.get("taxa_aprovacao_1sem"),
                atributos.get("taxa_aprovacao_2sem"),
                atributos.get("indicador_socioeconomico"),
                risco,
                modelo_versao,
            ),
        )


def registrar_processamento(nome_arquivo_origem, quantidade_alunos, caminho=CAMINHO_BANCO):
    """Loga no banco que uma planilha foi processada (trilha de auditoria)."""
    with conectar(caminho) as conexao:
        conexao.execute(
            "INSERT INTO processamentos (nome_arquivo_origem, quantidade_alunos) VALUES (?, ?)",
            (nome_arquivo_origem, quantidade_alunos),
        )


def _ultimo_processamento(conexao):
    """
    Id da última planilha processada, usado para separar quem está na avaliação atual de quem
    ficou de fora. Devolve None quando não dá para saber (banco vazio ou criado antes desta
    versão, em que as avaliações não registravam a planilha de origem): nesse caso ninguém é
    tratado como ausente.
    """
    ultimo = conexao.execute("SELECT MAX(id_processamento) FROM processamentos").fetchone()[0]
    if ultimo is None:
        return None
    ligadas = conexao.execute(
        "SELECT COUNT(*) FROM avaliacoes_risco WHERE id_processamento = ?", (ultimo,)
    ).fetchone()[0]
    return ultimo if ligadas else None


def buscar_visao_geral(caminho=CAMINHO_BANCO):
    """
    Última avaliação de cada aluno que consta na ÚLTIMA planilha processada (com os atributos
    usados no cálculo) e o risco da avaliação anterior, quando existir — usado nas telas
    'Visão geral', 'Lista priorizada' e no alerta de quem piorou. Alunos que não estavam na
    última planilha não aparecem aqui (ver buscar_divergencias). Traz a data da última ação pedagógica
    registrada (não o texto dela). Nunca devolve o nome.
    """
    with conectar(caminho) as conexao:
        ultimo = _ultimo_processamento(conexao)
        so_ultima = "AND av.id_processamento = :ultimo" if ultimo is not None else ""
        linhas = conexao.execute(
            f"""
            SELECT a.id_aluno, a.matricula, a.turma, a.curso,
                   av.risco, av.data_avaliacao,
                   av.nota_admissao, av.nota_1sem, av.nota_2sem,
                   av.taxa_aprovacao_1sem, av.taxa_aprovacao_2sem, av.indicador_socioeconomico,
                   av.frequencia_pct,
                   (SELECT ant.risco FROM avaliacoes_risco ant
                     WHERE ant.id_aluno = a.id_aluno AND ant.id_avaliacao < av.id_avaliacao
                     ORDER BY ant.id_avaliacao DESC LIMIT 1) AS risco_anterior,
                   (SELECT MAX(ac.data_acao) FROM acoes_pedagogicas ac WHERE ac.id_aluno = a.id_aluno) AS ultima_acao,
                   (SELECT p.periodo_referencia FROM processamentos p WHERE p.id_processamento = av.id_processamento) AS periodo
            FROM alunos a
            JOIN avaliacoes_risco av ON av.id_aluno = a.id_aluno
            WHERE av.id_avaliacao = (
                SELECT MAX(id_avaliacao) FROM avaliacoes_risco WHERE id_aluno = a.id_aluno
            ) {so_ultima}
            ORDER BY
                CASE av.risco
                    WHEN 'Risco Alto' THEN 1
                    WHEN 'Risco Médio' THEN 2
                    ELSE 3
                END,
                a.matricula
            """,
            {"ultimo": ultimo},
        ).fetchall()
        return [dict(linha) for linha in linhas]


MOTIVOS_RESOLUCAO = ("Saiu da escola", "Erro de planilha (conferido)", "Outro motivo")

# Id do primeiro envio em que o aluno ficou de fora (identifica a ausência; uma nova ausência depois de voltar é outra)
_SQL_PROC_AUSENCIA = """
    CASE WHEN av.id_processamento IS NOT NULL
         THEN (SELECT MIN(p.id_processamento) FROM processamentos p WHERE p.id_processamento > av.id_processamento)
         ELSE (SELECT MIN(p.id_processamento) FROM processamentos p WHERE p.data_hora > av.data_avaliacao)
    END
"""


def _consultar_divergencias(conexao):
    """Todas as ausências (pendentes e resolvidas) da última planilha, com os dados da resolução, quando houver."""
    ultimo = _ultimo_processamento(conexao)
    if ultimo is None:
        return []
    linhas = conexao.execute(
        f"""
        SELECT a.id_aluno, a.matricula, a.turma, a.curso,
               av.risco, av.data_avaliacao,
               (SELECT MIN(p.data_hora) FROM processamentos p
                 WHERE (av.id_processamento IS NOT NULL AND p.id_processamento > av.id_processamento)
                    OR (av.id_processamento IS NULL AND p.data_hora > av.data_avaliacao)
               ) AS ausente_desde,
               {_SQL_PROC_AUSENCIA} AS id_proc_ausencia,
               r.id_resolucao, r.motivo, r.responsavel AS responsavel_resolucao, r.resolvido_em
        FROM alunos a
        JOIN avaliacoes_risco av ON av.id_aluno = a.id_aluno
        LEFT JOIN divergencias_resolvidas r
               ON r.id_aluno = a.id_aluno AND r.id_proc_ausencia = ({_SQL_PROC_AUSENCIA})
        WHERE av.id_avaliacao = (
            SELECT MAX(id_avaliacao) FROM avaliacoes_risco WHERE id_aluno = a.id_aluno
        ) AND (av.id_processamento IS NULL OR av.id_processamento <> ?)
        ORDER BY a.matricula
        """,
        (ultimo,),
    ).fetchall()
    return [dict(linha, resolvida=linha["id_resolucao"] is not None) for linha in linhas]


def buscar_divergencias(caminho=CAMINHO_BANCO, incluir_resolvidas=False):
    """
    Alunos que já foram avaliados antes, mas NÃO estão na última planilha processada. Servem para
    conferir se foi erro de arquivo ou se o aluno realmente saiu da instituição. O histórico deles
    continua no banco; se voltarem em uma planilha futura, reaparecem nas outras telas sozinhos.
    Devolve última avaliação, risco e desde quando estão ausentes — nunca o nome. Por padrão só as PENDENTES;
    com `incluir_resolvidas=True` traz também as já conferidas (chave `resolvida`, com motivo, responsável e data).
    """
    with conectar(caminho) as conexao:
        todas = _consultar_divergencias(conexao)
    return todas if incluir_resolvidas else [d for d in todas if not d["resolvida"]]


def resolver_divergencias(ids_aluno, motivo, responsavel, caminho=CAMINHO_BANCO):
    """
    Marca como resolvidas as divergências PENDENTES dos alunos indicados (um ou vários de uma vez), com motivo e
    responsável. Não apaga nada: o aluno continua fora das listas até voltar numa planilha. Se ele voltar e sumir de
    novo, a nova ausência é pendente. Devolve quantas foram marcadas.
    """
    motivo, responsavel = str(motivo or "").strip(), str(responsavel or "").strip()
    if motivo not in MOTIVOS_RESOLUCAO:
        raise ValueError("Motivo inválido.")
    if not responsavel:
        raise ValueError("Informe o responsável pelo registro.")
    ids = {int(i) for i in ids_aluno}
    with conectar(caminho) as conexao:
        pendentes = [d for d in _consultar_divergencias(conexao) if not d["resolvida"] and d["id_aluno"] in ids]
        conexao.executemany(
            "INSERT OR IGNORE INTO divergencias_resolvidas (id_aluno, id_proc_ausencia, motivo, responsavel) VALUES (?, ?, ?, ?)",
            [(d["id_aluno"], d["id_proc_ausencia"], motivo, responsavel) for d in pendentes if d["id_proc_ausencia"] is not None],
        )
        return len(pendentes)


def reabrir_divergencias(ids_aluno, caminho=CAMINHO_BANCO):
    """Desfaz a marcação de 'resolvida' dos alunos indicados (voltam a ser pendentes). Devolve quantas foram reabertas."""
    ids = {int(i) for i in ids_aluno}
    with conectar(caminho) as conexao:
        resolvidas = [d["id_resolucao"] for d in _consultar_divergencias(conexao) if d["resolvida"] and d["id_aluno"] in ids]
        conexao.executemany("DELETE FROM divergencias_resolvidas WHERE id_resolucao = ?", [(i,) for i in resolvidas])
        return len(resolvidas)


def buscar_processamento_por_hash(hash_conteudo, caminho=CAMINHO_BANCO):
    """
    Procura uma planilha já processada com exatamente o mesmo conteúdo. Devolve o registro do
    processamento (com a chave extra 'eh_ultimo') ou None.
    """
    with conectar(caminho) as conexao:
        linha = conexao.execute(
            "SELECT * FROM processamentos WHERE hash_conteudo = ? ORDER BY id_processamento DESC LIMIT 1",
            (hash_conteudo,),
        ).fetchone()
        if linha is None:
            return None
        ultimo = conexao.execute("SELECT MAX(id_processamento) FROM processamentos").fetchone()[0]
        achado = dict(linha)
        achado["eh_ultimo"] = achado["id_processamento"] == ultimo
        return achado


def buscar_ficha_aluno(id_aluno, caminho=CAMINHO_BANCO):
    """Histórico completo de avaliações de um aluno, já com o nome — uso restrito à ficha individual."""
    with conectar(caminho) as conexao:
        aluno = conexao.execute(
            "SELECT * FROM alunos WHERE id_aluno = ?", (id_aluno,)
        ).fetchone()
        historico = conexao.execute(
            """
            SELECT av.*, p.periodo_referencia AS periodo
            FROM avaliacoes_risco av
            LEFT JOIN processamentos p ON p.id_processamento = av.id_processamento
            WHERE av.id_aluno = ?
            ORDER BY av.id_avaliacao ASC
            """,
            (id_aluno,),
        ).fetchall()
        return {
            "aluno": dict(aluno) if aluno else None,
            "historico": [dict(linha) for linha in historico],
        }


def gravar_lote(registros, nome_arquivo_origem, modelo_versao=MODELO_VERSAO_ATUAL, caminho=CAMINHO_BANCO,
                hash_conteudo=None, periodo_referencia=None, atribuicoes=()):
    """
    Grava vários alunos e suas avaliações em UMA transação (rápido e atômico:
    ou entra tudo, ou nada). Cada registro é um dict com: matricula, nome,
    turma, curso, risco e as chaves de atributos (nota_admissao, nota_1sem,
    nota_2sem, taxa_aprovacao_1sem, taxa_aprovacao_2sem, indicador_socioeconomico e, opcional, frequencia_pct).
    Alunos existentes (mesma matrícula) têm nome, turma e curso atualizados (turma e curso em branco
    na planilha não apagam os que já estavam gravados); a avaliação é sempre nova e fica ligada
    à planilha (id_processamento), o que permite saber quem estava ou não em cada envio. Quando o envio muda o nome,
    a turma ou o curso de um aluno que já existia, o valor anterior fica guardado (alunos_alteracoes) para o
    "desfazer" poder restaurá-lo.
    `hash_conteudo` é a impressão digital da planilha (detecta envio repetido) e `periodo_referencia`,
    um texto opcional dizendo a que período os dados se referem (ex.: "2026/1"). `atribuicoes`: pares (turma, login do
    professor) vindos da coluna "professores" da planilha; o último envio que trouxe pares passa a ser a atribuição vigente
    (a de envios anteriores só volta a valer se este for desfeito).
    Devolve a quantidade de alunos gravados.
    """
    chaves = ("nota_admissao", "nota_1sem", "nota_2sem", "taxa_aprovacao_1sem",
              "taxa_aprovacao_2sem", "indicador_socioeconomico", "frequencia_pct")
    with conectar(caminho) as conexao:
        id_proc = conexao.execute(
            "INSERT INTO processamentos (nome_arquivo_origem, quantidade_alunos, hash_conteudo, periodo_referencia) VALUES (?, ?, ?, ?)",
            (nome_arquivo_origem, len(registros), hash_conteudo, (periodo_referencia or "").strip() or None),
        ).lastrowid
        existentes = {l["matricula"]: l for l in conexao.execute("SELECT id_aluno, matricula, nome, turma, curso FROM alunos")}
        alteracoes = []
        for r in registros:
            antes = existentes.get(r["matricula"])
            if antes is not None:   # guarda o que este envio vai sobrescrever (turma/curso em branco não sobrescrevem)
                turma = r.get("turma") if r.get("turma") is not None else antes["turma"]
                curso = r.get("curso") if r.get("curso") is not None else antes["curso"]
                if (antes["nome"], antes["turma"], antes["curso"]) != (r["nome"], turma, curso):
                    alteracoes.append((id_proc, antes["id_aluno"], antes["nome"], antes["turma"], antes["curso"]))
            conexao.execute(
                """
                INSERT INTO alunos (matricula, nome, turma, curso) VALUES (?, ?, ?, ?)
                ON CONFLICT(matricula) DO UPDATE SET
                    nome = excluded.nome,
                    turma = COALESCE(excluded.turma, alunos.turma),   -- planilha sem turma/curso não apaga o que já existe
                    curso = COALESCE(excluded.curso, alunos.curso)
                """,
                (r["matricula"], r["nome"], r.get("turma"), r.get("curso")),
            )
        conexao.executemany(
            "INSERT INTO alunos_alteracoes (id_processamento, id_aluno, nome_anterior, turma_anterior, curso_anterior) VALUES (?, ?, ?, ?, ?)",
            alteracoes,
        )
        conexao.executemany("INSERT OR IGNORE INTO turmas_professores (id_processamento, turma, login) VALUES (?, ?, ?)",
                            [(id_proc, t, lg) for t, lg in atribuicoes])
        mapa = {
            linha["matricula"]: linha["id_aluno"]
            for linha in conexao.execute("SELECT matricula, id_aluno FROM alunos")
        }
        conexao.executemany(
            """
            INSERT INTO avaliacoes_risco (
                id_aluno, nota_admissao, nota_1sem, nota_2sem,
                taxa_aprovacao_1sem, taxa_aprovacao_2sem,
                indicador_socioeconomico, frequencia_pct, risco, modelo_versao, id_processamento
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (mapa[r["matricula"]], *[r.get(k) for k in chaves], r["risco"], modelo_versao, id_proc)
                for r in registros
            ],
        )
    return len(registros)


def buscar_envios_desfaziveis(caminho=CAMINHO_BANCO):
    """
    Envios (processamentos) que podem ser desfeitos, do MAIS RECENTE para o mais antigo. Só entram os envios seguidos,
    a partir do último, cujas avaliações registram a origem (envios de versões muito antigas do app não registravam).
    """
    with conectar(caminho) as conexao:
        linhas = conexao.execute(
            """
            SELECT p.*, (SELECT COUNT(*) FROM avaliacoes_risco av WHERE av.id_processamento = p.id_processamento) AS avaliacoes
            FROM processamentos p ORDER BY p.id_processamento DESC
            """
        ).fetchall()
    envios = []
    for linha in linhas:
        if not linha["avaliacoes"]:
            break
        envios.append(dict(linha))
    return envios


def resumo_desfazer(id_processamento, caminho=CAMINHO_BANCO):
    """
    O que aconteceria ao desfazer o envio indicado E todos os posteriores (ou None se não for possível):
    quantos envios e avaliações saem, que alunos novos (só existiam nesses envios) são removidos, quantas ações
    pedagógicas e resoluções de divergência saem junto e quantos alunos têm nome/turma/curso restaurados.
    """
    with conectar(caminho) as conexao:
        return _resumir_desfazer(conexao, id_processamento)


def _resumir_desfazer(conexao, id_proc):
    desfaziveis = {l[0] for l in conexao.execute(
        """
        SELECT p.id_processamento FROM processamentos p
        WHERE p.id_processamento >= ? AND EXISTS (SELECT 1 FROM avaliacoes_risco av WHERE av.id_processamento = p.id_processamento)
        """, (id_proc,))}
    total = conexao.execute("SELECT COUNT(*) FROM processamentos WHERE id_processamento >= ?", (id_proc,)).fetchone()[0]
    if not total or len(desfaziveis) != total:
        return None
    # só é possível se TODOS os envios a partir deste têm avaliações ligadas (e este é o mais antigo a desfazer)
    novos = [l[0] for l in conexao.execute(
        """
        SELECT DISTINCT a.id_aluno FROM alunos a
        WHERE EXISTS (SELECT 1 FROM avaliacoes_risco WHERE id_aluno = a.id_aluno AND id_processamento >= :p)
          AND NOT EXISTS (SELECT 1 FROM avaliacoes_risco WHERE id_aluno = a.id_aluno
                           AND (id_processamento IS NULL OR id_processamento < :p))
        """, {"p": id_proc})]
    marcas = ",".join("?" * len(novos)) or "-1"
    acoes = conexao.execute(f"SELECT COUNT(*) FROM acoes_pedagogicas WHERE id_aluno IN ({marcas})", novos).fetchone()[0]
    restaurados = conexao.execute(
        f"SELECT COUNT(DISTINCT id_aluno) FROM alunos_alteracoes WHERE id_processamento >= ? AND id_aluno NOT IN ({marcas})",
        [id_proc, *novos]).fetchone()[0]
    resolucoes = conexao.execute(
        f"SELECT COUNT(*) FROM divergencias_resolvidas WHERE id_proc_ausencia >= ? OR id_aluno IN ({marcas})",
        [id_proc, *novos]).fetchone()[0]
    avaliacoes = conexao.execute("SELECT COUNT(*) FROM avaliacoes_risco WHERE id_processamento >= ?", (id_proc,)).fetchone()[0]
    return {"id_processamento": id_proc, "envios": total, "avaliacoes": avaliacoes, "alunos_novos": len(novos),
            "ids_alunos_novos": novos, "acoes_removidas": acoes, "alunos_restaurados": restaurados,
            "resolucoes_removidas": resolucoes}


def desfazer_ate_processamento(id_processamento, caminho=CAMINHO_BANCO):
    """
    Desfaz o envio indicado e TODOS os posteriores (do mais novo para o mais antigo), numa única transação: apaga as
    avaliações geradas por eles, os alunos que só existiam neles (com ações pedagógicas e resoluções de divergência),
    restaura nome, turma e curso que esses envios sobrescreveram e apaga os registros dos envios. A avaliação anterior
    de cada aluno volta a valer. Devolve o resumo do que foi feito, ou None se não houver como desfazer.
    Limite: envios feitos antes desta versão não guardaram o valor anterior de nome/turma/curso (não há o que restaurar).
    """
    with conectar(caminho) as conexao:
        resumo = _resumir_desfazer(conexao, id_processamento)
        if resumo is None:
            return None
        info = dict(conexao.execute("SELECT * FROM processamentos WHERE id_processamento = ?", (id_processamento,)).fetchone())
        resumo["nome_arquivo_origem"] = info["nome_arquivo_origem"]
        resumo["data_hora"] = info["data_hora"]
        novos = resumo["ids_alunos_novos"]
        # restaura do envio mais recente para o mais antigo: no fim vale o valor anterior ao primeiro envio desfeito
        for alt in conexao.execute(
                "SELECT * FROM alunos_alteracoes WHERE id_processamento >= ? ORDER BY id_processamento DESC, id_alteracao DESC",
                (id_processamento,)).fetchall():
            conexao.execute("UPDATE alunos SET nome = ?, turma = ?, curso = ? WHERE id_aluno = ?",
                            (alt["nome_anterior"], alt["turma_anterior"], alt["curso_anterior"], alt["id_aluno"]))
        conexao.execute("DELETE FROM alunos_alteracoes WHERE id_processamento >= ?", (id_processamento,))
        conexao.execute("DELETE FROM turmas_professores WHERE id_processamento >= ?", (id_processamento,))
        conexao.execute("DELETE FROM avaliacoes_risco WHERE id_processamento >= ?", (id_processamento,))
        conexao.execute("DELETE FROM divergencias_resolvidas WHERE id_proc_ausencia >= ?", (id_processamento,))
        # alunos que só existiam nesses envios saem junto, com tudo que está ligado a eles
        for tabela in ("acoes_pedagogicas", "divergencias_resolvidas", "alunos_alteracoes"):
            conexao.executemany(f"DELETE FROM {tabela} WHERE id_aluno = ?", [(i,) for i in novos])
        conexao.executemany("DELETE FROM alunos WHERE id_aluno = ?", [(i,) for i in novos])
        conexao.execute("DELETE FROM processamentos WHERE id_processamento >= ?", (id_processamento,))
    return resumo


def buscar_ultimo_processamento_desfazivel(caminho=CAMINHO_BANCO):
    """Dados do último envio, se puder ser desfeito (ou None). Atalho para o primeiro item de buscar_envios_desfaziveis."""
    envios = buscar_envios_desfaziveis(caminho)
    if not envios:
        return None
    info = envios[0]
    resumo = resumo_desfazer(info["id_processamento"], caminho)
    return {**info, **(resumo or {})}


def desfazer_ultimo_processamento(caminho=CAMINHO_BANCO):
    """Desfaz só o último envio (atalho para desfazer_ate_processamento). Devolve o resumo, ou None se não houver o que desfazer."""
    envios = buscar_envios_desfaziveis(caminho)
    return desfazer_ate_processamento(envios[0]["id_processamento"], caminho) if envios else None


def buscar_processamentos(limite=20, caminho=CAMINHO_BANCO):
    """Últimos processamentos (trilha de auditoria)."""
    with conectar(caminho) as conexao:
        linhas = conexao.execute(
            "SELECT * FROM processamentos ORDER BY id_processamento DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(l) for l in linhas]


def contar_alunos(caminho=CAMINHO_BANCO):
    with conectar(caminho) as conexao:
        return conexao.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]


def limpar_dados(caminho=CAMINHO_BANCO):
    """Apaga alunos, avaliações, ações pedagógicas, resoluções de divergência, turmas dos professores e processamentos (usado só para reiniciar a demonstração). Usuários, configurações e a trilha de auditoria ficam."""
    with conectar(caminho) as conexao:
        conexao.execute("DELETE FROM acoes_pedagogicas")
        conexao.execute("DELETE FROM divergencias_resolvidas")
        conexao.execute("DELETE FROM alunos_alteracoes")
        conexao.execute("DELETE FROM turmas_professores")
        conexao.execute("DELETE FROM avaliacoes_risco")
        conexao.execute("DELETE FROM alunos")
        conexao.execute("DELETE FROM processamentos")
        conexao.execute("DELETE FROM sqlite_sequence WHERE name NOT IN ('usuarios', 'auditoria')")   # usuários, configurações e a trilha de auditoria não são apagados


# ----------------------------------------------------------------- ações pedagógicas
def registrar_acao(id_aluno, data_acao, tipo, descricao, responsavel, caminho=CAMINHO_BANCO):
    """
    Registra uma ação pedagógica (conversa com a família, reforço etc.) para o aluno.
    `data_acao` é uma data (date ou 'AAAA-MM-DD'). Tipo, descrição e responsável são obrigatórios.
    Devolve o id da ação criada.
    """
    tipo, descricao, responsavel = (str(v or "").strip() for v in (tipo, descricao, responsavel))
    if not (tipo and descricao and responsavel):
        raise ValueError("Tipo, descrição e responsável são obrigatórios.")
    with conectar(caminho) as conexao:
        return conexao.execute(
            "INSERT INTO acoes_pedagogicas (id_aluno, data_acao, tipo, descricao, responsavel) VALUES (?, ?, ?, ?, ?)",
            (id_aluno, str(data_acao), tipo, descricao, responsavel),
        ).lastrowid


def buscar_acoes(id_aluno, caminho=CAMINHO_BANCO):
    """Ações pedagógicas de um aluno, da mais recente para a mais antiga (uso restrito à ficha)."""
    with conectar(caminho) as conexao:
        linhas = conexao.execute(
            "SELECT * FROM acoes_pedagogicas WHERE id_aluno = ? ORDER BY data_acao DESC, id_acao DESC", (id_aluno,)
        ).fetchall()
        return [dict(l) for l in linhas]


def excluir_acao(id_acao, caminho=CAMINHO_BANCO):
    """Exclui uma ação (para corrigir um registro errado ou indevido). Não há como desfazer."""
    with conectar(caminho) as conexao:
        return conexao.execute("DELETE FROM acoes_pedagogicas WHERE id_acao = ?", (id_acao,)).rowcount > 0


# ----------------------------------------------------------------- configurações da instituição
ESCALA_NOTA_ADMISSAO_PADRAO = 100.0   # padrão da escola (0 a 100); o app converte para 0-200, a escala do modelo
LIMITE_FREQUENCIA_PADRAO = 75.0   # mínimo de presença exigido pela LDB (art. 24, VI); a escola pode ajustar


def obter_limite_frequencia(caminho=CAMINHO_BANCO):
    """Limite de frequência (%) abaixo do qual o aluno entra no alerta. Padrão: 75."""
    with conectar(caminho) as conexao:
        linha = conexao.execute("SELECT valor FROM configuracoes WHERE chave = 'limite_frequencia'").fetchone()
    try:
        return float(linha["valor"]) if linha else LIMITE_FREQUENCIA_PADRAO
    except (TypeError, ValueError):
        return LIMITE_FREQUENCIA_PADRAO


def salvar_limite_frequencia(valor, caminho=CAMINHO_BANCO):
    """Grava o limite de frequência da instituição. Aceita de 1 a 100; devolve o valor gravado."""
    valor = float(valor)
    if not 1 <= valor <= 100:
        raise ValueError("O limite de frequência deve estar entre 1 e 100.")
    with conectar(caminho) as conexao:
        conexao.execute(
            """
            INSERT INTO configuracoes (chave, valor) VALUES ('limite_frequencia', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (repr(valor),),
        )
    return valor


def obter_escala_nota_admissao(caminho=CAMINHO_BANCO):
    """Nota máxima da escala em que a escola informa a nota de admissão (padrão 100; o modelo usa 0 a 200)."""
    with conectar(caminho) as conexao:
        linha = conexao.execute("SELECT valor FROM configuracoes WHERE chave = 'escala_nota_admissao'").fetchone()
    try:
        return float(linha["valor"]) if linha else ESCALA_NOTA_ADMISSAO_PADRAO
    except (TypeError, ValueError):
        return ESCALA_NOTA_ADMISSAO_PADRAO


def salvar_escala_nota_admissao(valor, caminho=CAMINHO_BANCO):
    """
    Grava a nota máxima da escala da nota de admissão (ex.: 200, 100, 10). Vale para os PRÓXIMOS envios: as notas
    já gravadas ficam como estão (convertidas para a escala do modelo no momento do envio). Aceita de 1 a 1000.
    """
    valor = float(valor)
    if not 1 <= valor <= 1000:
        raise ValueError("A nota máxima da escala deve estar entre 1 e 1000.")
    with conectar(caminho) as conexao:
        conexao.execute(
            """
            INSERT INTO configuracoes (chave, valor) VALUES ('escala_nota_admissao', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (repr(valor),),
        )
    return valor


def buscar_frequencias(caminho=CAMINHO_BANCO):
    """Frequência (%) de cada avaliação de cada aluno, em ordem: {id_aluno: [freq1, freq2, ...]} (None = não informada)."""
    resultado = {}
    with conectar(caminho) as conexao:
        for linha in conexao.execute("SELECT id_aluno, frequencia_pct FROM avaliacoes_risco ORDER BY id_aluno, id_avaliacao"):
            resultado.setdefault(linha["id_aluno"], []).append(linha["frequencia_pct"])
    return resultado
