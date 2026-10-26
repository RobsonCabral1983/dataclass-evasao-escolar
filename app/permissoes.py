"""
Permissões por perfil (sem dependência do Streamlit, fácil de testar).

- admin: tudo (inclusive Usuários, Auditoria, Configurações e apagar dados).
- coordenacao: todos os alunos, upload, desfazer envios, divergências, relatórios e ações pedagógicas.
- professor: só os alunos das turmas em que aparece na coluna "professores" da planilha — Visão geral, Lista, Ficha,
  Relatórios e ações pedagógicas desses alunos.
"""

TODAS_AS_TELAS = ["Visão geral", "Lista priorizada", "Ficha do aluno", "Divergências", "Relatórios",
                  "Upload de dados", "Configurações", "Usuários", "Auditoria", "Minha conta"]

_TELAS = {
    "admin": set(TODAS_AS_TELAS),
    "coordenacao": {"Visão geral", "Lista priorizada", "Ficha do aluno", "Divergências", "Relatórios", "Upload de dados", "Minha conta"},
    "professor": {"Visão geral", "Lista priorizada", "Ficha do aluno", "Relatórios", "Minha conta"},
}

# ação -> perfis que podem
_ACOES = {
    "ver_todos_os_alunos": {"admin", "coordenacao"},
    "enviar_planilha": {"admin", "coordenacao"},
    "desfazer_envios": {"admin", "coordenacao"},
    "resolver_divergencias": {"admin", "coordenacao"},
    "carregar_demonstracao": {"admin", "coordenacao"},
    "apagar_dados": {"admin"},
    "configuracoes": {"admin"},
    "gerenciar_usuarios": {"admin"},
    "ver_auditoria": {"admin"},
    "gerenciar_retencao": {"admin"},   # anonimizar por prazo e excluir um aluno (pedido de exclusão)
    "registrar_acao_pedagogica": {"admin", "coordenacao", "professor"},
}


def pode(usuario, acao):
    return bool(usuario) and usuario.get("perfil") in _ACOES.get(acao, set())


def telas_permitidas(usuario):
    """Telas do menu, na ordem de TODAS_AS_TELAS (Divergências só entra quando o chamador decide mostrá-la)."""
    perfil = (usuario or {}).get("perfil")
    return [t for t in TODAS_AS_TELAS if t in _TELAS.get(perfil, set())]


def pode_ver_tela(usuario, tela):
    return tela in telas_permitidas(usuario)


def restringir_alunos(visao, usuario):
    """Filtra a visão geral: coordenação e admin veem todos; professor só as turmas dele (sem turmas, ninguém)."""
    if pode(usuario, "ver_todos_os_alunos"):
        return visao
    turmas = set(usuario.get("turmas") or [])
    if visao.empty:
        return visao
    return visao[visao["turma"].isin(turmas)].reset_index(drop=True)


def identificacao(usuario):
    """Texto gravado como 'responsável' nas ações pedagógicas e nas divergências resolvidas."""
    return f"{usuario['nome']} ({usuario['login']})"
