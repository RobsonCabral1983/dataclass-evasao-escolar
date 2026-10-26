"""
Política de retenção e exclusão de dados de alunos (LGPD: princípio da necessidade).

Regras:
- Aluno ATIVO (presente na última planilha): os dados ficam enquanto ele constar na planilha da escola.
- Aluno que SAIU da escola (divergência resolvida com o motivo "Saiu da escola"): depois de `MESES_RETENCAO_SAIDA` meses (12) da
  confirmação, o administrador pode ANONIMIZAR o aluno: o nome vira "Aluno anonimizado", a matrícula vira "ANON-nnnnnn", a
  turma é apagada, as ações pedagógicas (texto livre) e os nomes antigos guardados para o "desfazer" são apagados, e o nome dele some
  da trilha de auditoria. As avaliações (notas, risco, frequência) ficam SEM identificação, para os números históricos e o retreino do
  modelo. O curso é mantido.
- Pedido de exclusão de um aluno (direito do titular): `excluir_aluno` apaga tudo dele (avaliações, ações, conferências) e tira o nome
  e a matrícula da trilha de auditoria. Atenção: se ele continuar na planilha da escola, voltará no próximo envio.
- A limpeza é MANUAL (com prévia e confirmação do administrador) e cada uma fica registrada na trilha de auditoria, sem dados do aluno.
"""
try:  # uso como pacote
    from .database import conectar, _consultar_divergencias
    from .criar_banco import CAMINHO_BANCO
    from . import auditoria
except ImportError:  # uso como script dentro da pasta banco/
    from database import conectar, _consultar_divergencias
    from criar_banco import CAMINHO_BANCO
    import auditoria

MESES_RETENCAO_SAIDA = 12
MOTIVO_SAIDA = "Saiu da escola"
ROTULO_ANONIMO = "Aluno anonimizado"
ROTULO_REMOVIDO_TRILHA = "(aluno removido)"


def _vencidos(conexao, meses):
    """Divergências resolvidas como 'Saiu da escola' há mais de `meses` meses, de alunos ainda não anonimizados."""
    limite = conexao.execute("SELECT datetime('now', ?)", (f"-{int(meses)} months",)).fetchone()[0]
    ids_anonimos = {l[0] for l in conexao.execute("SELECT id_aluno FROM alunos WHERE anonimizado_em IS NOT NULL OR matricula LIKE 'ANON-%'")}
    return [d for d in _consultar_divergencias(conexao)
            if d["resolvida"] and d["motivo"] == MOTIVO_SAIDA and d["resolvido_em"] < limite and d["id_aluno"] not in ids_anonimos]


def listar_elegiveis(meses=MESES_RETENCAO_SAIDA, caminho=CAMINHO_BANCO):
    """Alunos que já passaram do prazo depois de 'Saiu da escola' (matrícula, curso e data da confirmação; nunca o nome)."""
    with conectar(caminho) as c:
        return [{"id_aluno": d["id_aluno"], "matricula": d["matricula"], "curso": d["curso"], "saida_confirmada_em": d["resolvido_em"]}
                for d in _vencidos(c, meses)]


def resumo(meses=MESES_RETENCAO_SAIDA, caminho=CAMINHO_BANCO):
    """{'elegiveis', 'anonimizados', 'pendentes_antigas'}: pendentes_antigas são ausentes SEM conferência há mais de `meses` meses."""
    with conectar(caminho) as c:
        elegiveis = len(_vencidos(c, meses))
        anonimizados = c.execute("SELECT COUNT(*) FROM alunos WHERE anonimizado_em IS NOT NULL").fetchone()[0]
        limite = c.execute("SELECT datetime('now', ?)", (f"-{int(meses)} months",)).fetchone()[0]
        pendentes = sum(1 for d in _consultar_divergencias(c) if not d["resolvida"] and d["ausente_desde"] and d["ausente_desde"] < limite)
    return {"elegiveis": elegiveis, "anonimizados": anonimizados, "pendentes_antigas": pendentes}


def anonimizar_alunos(ids_aluno=None, meses=MESES_RETENCAO_SAIDA, usuario=None, caminho=CAMINHO_BANCO):
    """
    Anonimiza os alunos elegíveis (se `ids_aluno` for dado, só entre eles; quem não estiver vencido é ignorado). Devolve quantos.
    Tudo em uma única transação; depois registra um evento na trilha (sem dados dos alunos).
    """
    permitidos = None if ids_aluno is None else {int(i) for i in ids_aluno}
    with conectar(caminho) as c:
        alvos = [d["id_aluno"] for d in _vencidos(c, meses) if permitidos is None or d["id_aluno"] in permitidos]
        for i in alvos:
            c.execute("UPDATE alunos SET nome = ?, matricula = ?, turma = NULL, anonimizado_em = datetime('now') WHERE id_aluno = ?",
                      (ROTULO_ANONIMO, f"ANON-{i:06d}", i))
            c.execute("DELETE FROM acoes_pedagogicas WHERE id_aluno = ?", (i,))
            c.execute("DELETE FROM alunos_alteracoes WHERE id_aluno = ?", (i,))
            c.execute("UPDATE auditoria SET matricula = NULL, nome_aluno = ? WHERE id_aluno = ?", ("(aluno anonimizado)", i))
    if alvos:
        auditoria.registrar("retencao_anonimizacao", usuario, caminho=caminho,
                            detalhe=f"{len(alvos)} aluno(s) anonimizado(s) (saída confirmada há mais de {int(meses)} meses)")
    return len(alvos)


def excluir_aluno(id_aluno, motivo, usuario=None, caminho=CAMINHO_BANCO):
    """
    Exclusão definitiva de UM aluno (pedido do titular ou do responsável). Apaga avaliações, ações pedagógicas, conferências de
    divergência e nomes antigos, e remove nome e matrícula da trilha de auditoria. `motivo` é um texto curto, sem dados pessoais.
    Devolve True se o aluno existia.
    """
    motivo = " ".join(str(motivo or "").split())
    if not motivo:
        raise ValueError("Informe o motivo ou a referência do pedido (sem dados pessoais).")
    id_aluno = int(id_aluno)
    with conectar(caminho) as c:
        if c.execute("SELECT 1 FROM alunos WHERE id_aluno = ?", (id_aluno,)).fetchone() is None:
            return False
        for tabela in ("acoes_pedagogicas", "alunos_alteracoes", "divergencias_resolvidas", "avaliacoes_risco"):
            c.execute(f"DELETE FROM {tabela} WHERE id_aluno = ?", (id_aluno,))
        c.execute("DELETE FROM alunos WHERE id_aluno = ?", (id_aluno,))
        c.execute("UPDATE auditoria SET matricula = NULL, nome_aluno = ?, id_aluno = NULL WHERE id_aluno = ?", (ROTULO_REMOVIDO_TRILHA, id_aluno))
    auditoria.registrar("aluno_excluido", usuario, caminho=caminho, detalhe=f"exclusão individual (aluno interno nº {id_aluno}). Motivo: {motivo}")
    return True
