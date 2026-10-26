"""Liga o pipeline de previsão ao banco de dados (planilha -> validação -> previsão -> SQLite)."""
import hashlib
import os
import sys

import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from banco import database  # noqa: E402
import pipeline  # noqa: E402


def impressao_digital(df_ok):
    """
    Código que identifica o CONTEÚDO da planilha (já validada): o mesmo conjunto de alunos e valores
    gera o mesmo código, mesmo que o arquivo tenha outro nome ou as linhas estejam em outra ordem.
    """
    colunas = list(pipeline.COLUNAS_ENTRADA)
    if df_ok[pipeline.COLUNA_FREQUENCIA].notna().any():   # planilhas sem frequência mantêm o mesmo código de antes
        colunas.append(pipeline.COLUNA_FREQUENCIA)
    if (df_ok[pipeline.COLUNA_PROFESSORES] != "").any():   # idem: planilhas sem a coluna mantêm o código de antes
        colunas.append(pipeline.COLUNA_PROFESSORES)
    base = df_ok[colunas].sort_values("matricula").reset_index(drop=True)
    return hashlib.sha256(base.to_csv(index=False).encode("utf-8")).hexdigest()


def atribuicoes_turma_professor(df_ok):
    """Pares (turma, login) da coluna de professores da planilha validada; vazio se a coluna não veio preenchida."""
    pares = set()
    for turma, profs in zip(df_ok["turma"], df_ok[pipeline.COLUNA_PROFESSORES]):
        if profs and turma is not None and str(turma) not in ("nan", "None", "") and str(turma).strip():
            pares.update((str(turma).strip(), login) for login in profs.split(";"))
    return sorted(pares)


def verificar_repetida(df, caminho=database.CAMINHO_BANCO, escala_nota_admissao=None):
    """
    Se uma planilha com exatamente o mesmo conteúdo já foi processada, devolve o registro desse
    processamento (data_hora, nome_arquivo_origem, eh_ultimo...). Caso contrário, ou se a planilha
    tiver erros de validação, devolve None.
    """
    if escala_nota_admissao is None:
        escala_nota_admissao = database.obter_escala_nota_admissao(caminho)
    df_ok, erros = pipeline.validar_planilha(df, escala_nota_admissao)
    if erros or df_ok.empty:
        return None
    return database.buscar_processamento_por_hash(impressao_digital(df_ok), caminho=caminho)


def processar_e_gravar(df, nome_arquivo, modelo, config, caminho=database.CAMINHO_BANCO, periodo_referencia=None,
                       escala_nota_admissao=None):
    """
    Valida a planilha, classifica cada aluno e grava tudo numa transação.
    A planilha pode ter as colunas em português ou em inglês. `periodo_referencia` é opcional (ex.: "2026/1"). A nota de admissão é lida na escala definida em Configurações (`escala_nota_admissao` sobrescreve, usado pelos dados de demonstração, que são 0-200).
    Devolve (quantidade_gravada, lista_de_erros). Se houver erros, nada é gravado.
    """
    if escala_nota_admissao is None:   # escala definida em Configurações (os dados de demonstração passam 200 explicitamente)
        escala_nota_admissao = database.obter_escala_nota_admissao(caminho)
    df_ok, erros = pipeline.validar_planilha(df, escala_nota_admissao)
    if erros:
        return 0, erros
    if df_ok.empty:
        return 0, ["A planilha não tem nenhum aluno."]
    atributos, riscos = pipeline.prever(df_ok, modelo, config)
    registros = []
    for idx in df_ok.index:
        reg = {
            "matricula": df_ok.at[idx, "matricula"],
            "nome": df_ok.at[idx, "nome"],
            "turma": None if df_ok.at[idx, "turma"] is None or str(df_ok.at[idx, "turma"]) == "nan" else str(df_ok.at[idx, "turma"]),
            "curso": None if df_ok.at[idx, "curso"] is None or str(df_ok.at[idx, "curso"]) == "nan" else str(df_ok.at[idx, "curso"]),
            "risco": riscos.at[idx],
        }
        for col, chave in pipeline.ATRIBUTO_PARA_BANCO.items():
            reg[chave] = float(atributos.at[idx, col])
        freq = df_ok.at[idx, pipeline.COLUNA_FREQUENCIA]
        reg["frequencia_pct"] = None if pd.isna(freq) else float(freq)
        registros.append(reg)
    qtd = database.gravar_lote(registros, nome_arquivo, caminho=caminho, hash_conteudo=impressao_digital(df_ok),
                               periodo_referencia=periodo_referencia, atribuicoes=atribuicoes_turma_professor(df_ok))
    return qtd, []
