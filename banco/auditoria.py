"""
Trilha de auditoria: quem abriu a ficha de qual aluno, quem entrou ou saiu e quem fez ações sensíveis (envio de planilha,
desfazer envio, apagar dados, gestão de usuários), com data e hora.

- Cada registro guarda uma "foto" do usuário (login, nome, perfil) e do aluno (matrícula, nome) no momento do evento.
- Nunca grava senhas. Os dados dos alunos podem ser reiniciados; a trilha NÃO é apagada junto (só pela limpeza por prazo).
- As datas ficam em UTC no banco; a consulta (`listar`) filtra pelo dia no horário de Brasília (UTC-3, sem horário de verão).
- Prazo de guarda sugerido: 12 meses (`MESES_RETENCAO`). A limpeza é manual, feita pelo administrador (`apagar_anteriores_a`).
"""

try:  # uso como pacote (from banco import auditoria)
    from .database import conectar
    from .criar_banco import CAMINHO_BANCO
except ImportError:  # uso como script dentro da pasta banco/
    from database import conectar
    from criar_banco import CAMINHO_BANCO

MESES_RETENCAO = 12
LIMITE_PADRAO = 2000
DESLOCAMENTO_BRASILIA = "-3 hours"

EVENTOS = {
    "ficha_aluno": "Abriu a ficha de aluno",
    "login": "Entrou no sistema",
    "login_falha": "Tentativa de login sem sucesso",
    "logout": "Saiu do sistema",
    "sessao_expirada": "Sessão encerrada por inatividade",
    "envio_planilha": "Enviou planilha / carregou dados",
    "desfazer_envio": "Desfez envio(s)",
    "apagar_dados": "Apagou os dados dos alunos",
    "usuario_criado": "Criou usuário",
    "usuario_editado": "Alterou usuário",
    "senha_redefinida": "Redefiniu senha de usuário",
    "usuario_desbloqueado": "Desbloqueou usuário",
    "senha_trocada": "Trocou a própria senha",
    "configuracao_alterada": "Alterou configuração",
    "retencao_anonimizacao": "Anonimizou alunos (prazo de retenção)",
    "aluno_excluido": "Excluiu aluno (pedido de exclusão)",
    "auditoria_limpeza": "Apagou registros antigos da trilha",
}


def _texto(valor, limite):
    if valor is None:
        return None
    valor = " ".join(str(valor).split())   # sem quebras de linha nem espaços repetidos
    return valor[:limite] or None


def registrar(evento, usuario=None, login=None, aluno=None, detalhe=None, caminho=CAMINHO_BANCO):
    """
    Grava um evento. `usuario` é o dict da sessão (id_usuario, login, nome, perfil); sem ele, use `login` (texto digitado
    numa tentativa de login, ou 'sistema'). `aluno` é um dict com id_aluno, matricula e nome. Devolve o id do evento.
    """
    if evento not in EVENTOS:
        raise ValueError(f"Evento de auditoria desconhecido: {evento}")
    usuario = usuario or {}
    aluno = aluno or {}
    with conectar(caminho) as c:
        cur = c.execute(
            "INSERT INTO auditoria (id_usuario, login, nome_usuario, perfil, evento, id_aluno, matricula, nome_aluno, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario.get("id_usuario"), _texto(usuario.get("login") or login, 60), _texto(usuario.get("nome"), 120),
             usuario.get("perfil"), evento, aluno.get("id_aluno"), _texto(aluno.get("matricula"), 60),
             _texto(aluno.get("nome"), 160), _texto(detalhe, 300)))
        return cur.lastrowid


def _filtros(login=None, eventos=None, aluno=None, de=None, ate=None):
    where, params = [], []
    if login:
        where.append("login = ? COLLATE NOCASE")
        params.append(login)
    if eventos:
        where.append(f"evento IN ({','.join('?' * len(eventos))})")
        params.extend(eventos)
    if aluno and str(aluno).strip():
        where.append("(matricula LIKE ? OR nome_aluno LIKE ?)")
        termo = f"%{str(aluno).strip()}%"
        params.extend([termo, termo])
    if de:
        where.append("date(data_hora, ?) >= ?")
        params.extend([DESLOCAMENTO_BRASILIA, str(de)])
    if ate:
        where.append("date(data_hora, ?) <= ?")
        params.extend([DESLOCAMENTO_BRASILIA, str(ate)])
    return (" WHERE " + " AND ".join(where)) if where else "", params


def listar(login=None, eventos=None, aluno=None, de=None, ate=None, limite=LIMITE_PADRAO, caminho=CAMINHO_BANCO):
    """Eventos do mais recente para o mais antigo. `de` e `ate` são datas (AAAA-MM-DD) no horário de Brasília, inclusive."""
    onde, params = _filtros(login, eventos, aluno, de, ate)
    with conectar(caminho) as c:
        linhas = c.execute(
            f"SELECT *, datetime(data_hora, '{DESLOCAMENTO_BRASILIA}') AS data_hora_brasilia FROM auditoria{onde} "
            "ORDER BY id_evento DESC LIMIT ?", params + [int(limite)]).fetchall()
    return [dict(l) for l in linhas]


def contar(login=None, eventos=None, aluno=None, de=None, ate=None, caminho=CAMINHO_BANCO):
    onde, params = _filtros(login, eventos, aluno, de, ate)
    with conectar(caminho) as c:
        return c.execute(f"SELECT COUNT(*) FROM auditoria{onde}", params).fetchone()[0]


def logins_registrados(caminho=CAMINHO_BANCO):
    """Logins que aparecem na trilha (inclusive de usuários desativados e de tentativas de login)."""
    with conectar(caminho) as c:
        return [l[0] for l in c.execute("SELECT DISTINCT login FROM auditoria WHERE login IS NOT NULL ORDER BY login COLLATE NOCASE")]


def resumo_retencao(meses=MESES_RETENCAO, caminho=CAMINHO_BANCO):
    """{'total', 'mais_antigo' (UTC ou None), 'vencidos'}: quantos registros têm mais de `meses` meses."""
    with conectar(caminho) as c:
        total, antigo = c.execute("SELECT COUNT(*), MIN(data_hora) FROM auditoria").fetchone()
        vencidos = c.execute("SELECT COUNT(*) FROM auditoria WHERE data_hora < datetime('now', ?)", (f"-{int(meses)} months",)).fetchone()[0]
    return {"total": total, "mais_antigo": antigo, "vencidos": vencidos}


def apagar_anteriores_a(meses=MESES_RETENCAO, usuario=None, caminho=CAMINHO_BANCO):
    """Apaga os registros com mais de `meses` meses e registra a própria limpeza. Devolve quantos foram apagados."""
    with conectar(caminho) as c:
        apagados = c.execute("DELETE FROM auditoria WHERE data_hora < datetime('now', ?)", (f"-{int(meses)} months",)).rowcount
    registrar("auditoria_limpeza", usuario, detalhe=f"{apagados} registro(s) com mais de {int(meses)} meses apagados", caminho=caminho)
    return apagados
