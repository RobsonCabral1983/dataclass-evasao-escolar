"""
Pipeline de previsão usado pelo dashboard.

Replica, passo a passo, a engenharia de atributos do notebook
02_pipeline_modelo.ipynb (e a taxa de aprovação do notebook 01), para que o
app produza exatamente as mesmas previsões do notebook.

Rótulos de saída: sempre "Risco Alto", "Risco Médio" e "Risco Baixo".
"""

import json
import os
import re
import unicodedata

import joblib
import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_MODELO = os.path.join(RAIZ, "modelo", "modelo_risco.pkl")
CAMINHO_FEATURES = os.path.join(RAIZ, "modelo", "features.json")

# Colunas que a planilha da escola precisa ter (nomes do dataset UCI, usados no treino)
COLUNAS_IDENTIFICACAO = ["matricula", "nome", "turma", "curso"]
COLUNAS_OBRIGATORIAS_IDENTIFICACAO = ["matricula", "nome"]
COLUNAS_NUMERICAS = [
    "Admission grade",
    "Curricular units 1st sem (grade)",
    "Curricular units 2nd sem (grade)",
    "Curricular units 1st sem (approved)",
    "Curricular units 1st sem (enrolled)",
    "Curricular units 2nd sem (approved)",
    "Curricular units 2nd sem (enrolled)",
]
COLUNAS_BINARIAS = ["Debtor", "Tuition fees up to date", "Scholarship holder"]
COLUNAS_ENTRADA = COLUNAS_IDENTIFICACAO + COLUNAS_NUMERICAS + COLUNAS_BINARIAS

# Coluna opcional que NÃO entra no modelo (ele foi treinado sem frequência): serve para o alerta de frequência
# baixa, comparado com um limite que a escola define no app (padrão 75%, mínimo da LDB).
# Escala da nota de admissão: o modelo foi treinado com notas de 0 a 200 (valores de 95 a 190). Se a escola usa
# outra escala (0-100, 0-10...), o app converte proporcionalmente para 0-200 antes de calcular o risco.
ESCALA_MODELO_NOTA_ADMISSAO = 200.0
MINIMO_TREINO_NOTA_ADMISSAO = 95.0   # menor nota de admissão vista no treino
ESCALAS_CONHECIDAS = (10.0, 100.0, 200.0)   # escalas que o app reconhece sozinho ao sugerir uma conversão
COLUNA_FREQUENCIA = "frequencia_pct"
# Coluna opcional com os logins dos professores (separados por ";"). Define quais turmas cada professor vê no app.
COLUNA_PROFESSORES = "professores"
_REGEX_LOGIN_PROFESSOR = re.compile(r"^[a-z0-9._-]{3,40}$")
LIMITE_FREQUENCIA_PADRAO = 75.0

# Nomes das colunas da planilha em português. Internamente o modelo continua usando os nomes originais
# do dataset UCI (COLUNAS_ENTRADA), então a planilha pode vir com os nomes em português OU em inglês.
NOME_PT = {
    "Admission grade": "nota_admissao",
    "Curricular units 1st sem (grade)": "nota_media_1sem",
    "Curricular units 2nd sem (grade)": "nota_media_2sem",
    "Curricular units 1st sem (approved)": "disciplinas_aprovadas_1sem",
    "Curricular units 1st sem (enrolled)": "disciplinas_cursadas_1sem",
    "Curricular units 2nd sem (approved)": "disciplinas_aprovadas_2sem",
    "Curricular units 2nd sem (enrolled)": "disciplinas_cursadas_2sem",
    "Debtor": "inadimplente",
    "Tuition fees up to date": "mensalidade_em_dia",
    "Scholarship holder": "bolsista",
}
COLUNAS_ENTRADA_PT = COLUNAS_IDENTIFICACAO + [NOME_PT[c] for c in COLUNAS_NUMERICAS + COLUNAS_BINARIAS]

# Para a tela de upload: (coluna, obrigatoriedade, o que é)
DESCRICAO_COLUNAS = [
    ("matricula", "obrigatória", "Identificador único do aluno. É ela que liga o aluno ao histórico entre uma planilha e outra."),
    ("nome", "obrigatória", "Nome do aluno (aparece só na Ficha do aluno)."),
    ("turma", "recomendada", "Ex.: 2º A. Sem ela, os filtros e a comparação com a turma não funcionam."),
    ("curso", "recomendada", "Ex.: Técnico em Informática. Sem ela, os gráficos por curso não funcionam."),
    ("nota_admissao", "obrigatória", "Nota do processo seletivo de ingresso. A escala (padrão 0 a 100; ou 0 a 10, 0 a 200...) "
                                      "é definida em Configurações e o app converte para a escala do modelo."),
    ("nota_media_1sem", "obrigatória", "Média das notas do 1º semestre (0 se nenhuma disciplina foi avaliada)."),
    ("nota_media_2sem", "obrigatória", "Média das notas do 2º semestre (0 se nenhuma disciplina foi avaliada)."),
    ("disciplinas_aprovadas_1sem", "obrigatória", "Número de disciplinas em que o aluno foi aprovado no 1º semestre."),
    ("disciplinas_cursadas_1sem", "obrigatória", "Número de disciplinas em que o aluno se matriculou no 1º semestre."),
    ("disciplinas_aprovadas_2sem", "obrigatória", "Número de disciplinas em que o aluno foi aprovado no 2º semestre."),
    ("disciplinas_cursadas_2sem", "obrigatória", "Número de disciplinas em que o aluno se matriculou no 2º semestre."),
    ("inadimplente", "obrigatória", "1 = tem pendência financeira; 0 = não."),
    ("mensalidade_em_dia", "obrigatória", "1 = mensalidade em dia; 0 = não."),
    ("bolsista", "obrigatória", "1 = recebe bolsa; 0 = não."),
    ("frequencia_pct", "opcional", "Frequência do aluno de 0 a 100 (%). Não entra no modelo: gera o alerta de frequência baixa, "
                                   "comparada ao limite definido no app (padrão 75%)."),
    ("professores", "opcional", "Logins dos professores da turma, separados por ponto e vírgula (ex.: ana.silva;joao.souza). Cada professor "
                                "só vê os alunos das turmas em que aparece. O último envio que trouxe esta coluna substitui as atribuições anteriores."),
]


def _chave(texto):
    """Nome de coluna sem acento, minúsculo e sem espaços nas pontas, para comparar cabeçalhos."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


# cabeçalho aceito (sem acento, minúsculo) -> nome interno
_ALIAS = {_chave(c): c for c in COLUNAS_IDENTIFICACAO + COLUNAS_NUMERICAS + COLUNAS_BINARIAS}
_ALIAS.update({_chave(pt): original for original, pt in NOME_PT.items()})
_ALIAS.update({_chave(COLUNA_FREQUENCIA): COLUNA_FREQUENCIA, _chave("frequencia"): COLUNA_FREQUENCIA,
               _chave("frequencia (%)"): COLUNA_FREQUENCIA,
               _chave("professores"): COLUNA_PROFESSORES, _chave("professor"): COLUNA_PROFESSORES})


def normalizar_colunas(df):
    """
    Renomeia as colunas da planilha para os nomes internos, aceitando português ou inglês (com ou sem
    acento, maiúsculas e espaços nas pontas). Colunas desconhecidas são mantidas como vieram.
    Devolve (df, erros); há erro se a mesma coluna aparece duas vezes (por exemplo, em português e em inglês).
    """
    novos = [_ALIAS.get(_chave(c), c) for c in df.columns]
    repetidas = sorted({_nome_pt(n) for n in novos if novos.count(n) > 1 and n in _ALIAS.values()})
    if repetidas:
        return df, [f"A coluna '{r}' aparece mais de uma vez (talvez com o nome em português e em inglês)." for r in repetidas]
    df = df.copy()
    df.columns = novos
    return df, []


def _nome_pt(coluna):
    return NOME_PT.get(coluna, coluna)


def _converter_nota_admissao(serie, escala):
    """Nota de admissão na escala da escola (0 a `escala`) -> escala do modelo (0 a 200), de forma proporcional."""
    return serie * (ESCALA_MODELO_NOTA_ADMISSAO / float(escala))


def sugerir_escala(df, escala_nota_admissao):
    """
    Se a nota de admissão da planilha (já normalizada) passa do máximo da escala configurada, procura a menor escala
    conhecida (0-10, 0-100, 0-200) que comporta todos os valores e a devolve como SUGESTÃO (por exemplo, valores até 190
    com a escala 0-100 sugerem 0-200). Devolve None se não há excesso, se há valor negativo ou se nenhuma escala comporta.
    """
    if "Admission grade" not in df.columns:
        return None
    nota = pd.to_numeric(df["Admission grade"], errors="coerce").dropna()
    if nota.empty or (nota < 0).any() or nota.max() <= escala_nota_admissao:
        return None
    return next((e for e in ESCALAS_CONHECIDAS if e >= nota.max() and e > escala_nota_admissao), None)


def avisos_planilha(df, escala_nota_admissao=ESCALA_MODELO_NOTA_ADMISSAO):
    """
    Avisos (não impedem o envio) sobre a planilha já normalizada: turma/curso ausentes ou em branco deixam
    filtros, gráficos por curso/turma e a comparação com a turma sem funcionar; notas de admissão (já convertidas
    para a escala do modelo) bem abaixo do que o modelo viu no treino podem inflar o risco.
    """
    avisos = []
    if "Admission grade" in df.columns:
        nota = _converter_nota_admissao(pd.to_numeric(df["Admission grade"], errors="coerce"), escala_nota_admissao).dropna()
        abaixo = int((nota < MINIMO_TREINO_NOTA_ADMISSAO).sum())
        if len(nota) and abaixo / len(nota) >= 0.2:
            avisos.append(f"{abaixo} aluno(s) ({abaixo / len(nota):.0%}) têm nota de admissão, já convertida para a escala do modelo (0 a 200), "
                          f"abaixo de {MINIMO_TREINO_NOTA_ADMISSAO:.0f}, a menor vista no treino. O modelo pode superestimar o risco desses alunos; "
                          "confira a escala em Configurações.")
    for coluna, sem_tudo, sem_alguns in (
            ("turma", "os filtros por turma e a comparação com a turma não vão funcionar",
             "ficam fora dos filtros por turma e da comparação com a turma"),
            ("curso", "os filtros e os gráficos por curso não vão funcionar",
             "ficam fora dos filtros e dos gráficos por curso")):
        if coluna not in df.columns:
            avisos.append(f"A planilha não tem a coluna **{coluna}**: {sem_tudo}.")
            continue
        em_branco = int(df[coluna].isna().sum() + (df[coluna].astype(str).str.strip() == "").sum())
        if em_branco == len(df):
            avisos.append(f"A coluna **{coluna}** está toda em branco: {sem_tudo}.")
        elif em_branco:
            avisos.append(f"{em_branco} aluno(s) estão sem **{coluna}** e {sem_alguns}.")
    if COLUNA_PROFESSORES in df.columns and "turma" in df.columns:
        com_prof = df[COLUNA_PROFESSORES].fillna("").astype(str).str.strip() != ""
        sem_turma = com_prof & (df["turma"].isna() | (df["turma"].astype(str).str.strip() == ""))
        if sem_turma.any():
            avisos.append(f"{int(sem_turma.sum())} aluno(s) têm **{COLUNA_PROFESSORES}** mas estão sem turma: a atribuição só vale para turmas informadas.")
    if COLUNA_FREQUENCIA not in df.columns:
        avisos.append(f"A planilha não tem a coluna **{COLUNA_FREQUENCIA}**: o alerta de frequência baixa fica desligado para este envio.")
    else:
        freq = _frequencia_numerica(df[COLUNA_FREQUENCIA])
        sem_valor = int(freq.isna().sum())
        if sem_valor == len(df):
            avisos.append(f"A coluna **{COLUNA_FREQUENCIA}** está toda em branco: o alerta de frequência baixa fica desligado para este envio.")
        else:
            if sem_valor:
                avisos.append(f"{sem_valor} aluno(s) estão sem **{COLUNA_FREQUENCIA}** e ficam fora do alerta de frequência baixa.")
            if freq.dropna().max() <= 1:
                avisos.append(f"Todos os valores de **{COLUNA_FREQUENCIA}** estão entre 0 e 1. A coluna deve estar em porcentagem "
                              "(de 0 a 100): 0,9 seria lido como 0,9% de frequência e todos os alunos ficariam abaixo do limite.")
    return avisos


def _frequencia_numerica(serie):
    """Converte a coluna de frequência para número, aceitando '85', '85,5' e '85%' (vazio ou inválido vira NaN)."""
    texto = serie.astype(str).str.strip().str.replace("%", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(texto, errors="coerce")


# Nome do atributo do modelo -> chave usada no banco de dados
ATRIBUTO_PARA_BANCO = {
    "Admission grade": "nota_admissao",
    "Curricular units 1st sem (grade)": "nota_1sem",
    "Curricular units 2nd sem (grade)": "nota_2sem",
    "taxa_aprovacao_1sem": "taxa_aprovacao_1sem",
    "taxa_aprovacao_2sem": "taxa_aprovacao_2sem",
    "indicador_socioeconomico": "indicador_socioeconomico",
}

# Nomes legíveis para a tela "Ficha do aluno"
NOME_AMIGAVEL = {
    "Admission grade": "Nota de admissão",
    "Curricular units 1st sem (grade)": "Nota média 1º semestre",
    "Curricular units 2nd sem (grade)": "Nota média 2º semestre",
    "taxa_aprovacao_1sem": "Taxa de aprovação 1º semestre",
    "taxa_aprovacao_2sem": "Taxa de aprovação 2º semestre",
    "indicador_socioeconomico": "Indicador socioeconômico",
}


def carregar_modelo():
    modelo = joblib.load(CAMINHO_MODELO)
    with open(CAMINHO_FEATURES, encoding="utf-8") as f:
        config = json.load(f)
    return modelo, config


def validar_planilha(df, escala_nota_admissao=ESCALA_MODELO_NOTA_ADMISSAO):
    """
    Confere colunas e valores. Devolve (df_limpo, lista_de_erros).
    Se houver erros, df_limpo é None. A nota de admissão deve estar entre 0 e `escala_nota_admissao` (a escala da
    escola, definida em Configurações); no df_limpo ela já vem convertida para a escala do modelo (0 a 200).
    """
    erros = []
    df, erros_nomes = normalizar_colunas(df)
    if erros_nomes:
        return None, erros_nomes
    faltando = [c for c in COLUNAS_OBRIGATORIAS_IDENTIFICACAO + COLUNAS_NUMERICAS + COLUNAS_BINARIAS
                if c not in df.columns]
    if faltando:
        return None, [f"Colunas ausentes: {', '.join(_nome_pt(c) for c in faltando)}"]

    df = df.copy()
    for c in ("turma", "curso"):
        if c not in df.columns:
            df[c] = None
    df["matricula"] = df["matricula"].astype(str).str.strip()
    df["nome"] = df["nome"].astype(str).str.strip()

    if (df["matricula"].isin(["", "nan", "None"])).any():
        erros.append("Há linhas sem matrícula.")
    if (df["nome"].isin(["", "nan", "None"])).any():
        erros.append("Há linhas sem nome.")
    duplicadas = df.loc[df["matricula"].duplicated(), "matricula"].unique()
    if len(duplicadas):
        erros.append(f"Matrículas duplicadas na planilha: {', '.join(map(str, duplicadas[:5]))}"
                     + ("..." if len(duplicadas) > 5 else ""))

    for c in COLUNAS_NUMERICAS + COLUNAS_BINARIAS:
        convertida = pd.to_numeric(df[c], errors="coerce")
        invalidos = convertida.isna() & df[c].notna() & (df[c].astype(str).str.strip() != "")
        if invalidos.any():
            erros.append(f"Coluna '{_nome_pt(c)}' tem valores não numéricos (linhas {list(df.index[invalidos][:5] + 2)}).")
        df[c] = convertida

    # frequência (opcional): sempre existe depois da validação; NaN quando não informada
    if COLUNA_FREQUENCIA in df.columns:
        original = df[COLUNA_FREQUENCIA]
        freq = _frequencia_numerica(original)
        informado = original.notna() & (original.astype(str).str.strip() != "")
        invalidos = freq.isna() & informado
        if invalidos.any():
            erros.append(f"Coluna '{COLUNA_FREQUENCIA}' tem valores não numéricos (linhas {list(df.index[invalidos][:5] + 2)}).")
        fora = (freq < 0) | (freq > 100)
        if fora.any():
            erros.append(f"Coluna '{COLUNA_FREQUENCIA}' deve estar entre 0 e 100 (linhas {list(df.index[fora][:5] + 2)}).")
        df[COLUNA_FREQUENCIA] = freq
    else:
        df[COLUNA_FREQUENCIA] = np.nan

    # professores (opcional): logins separados por ";"; fica como texto normalizado ("a;b", em ordem), vazio se não informado
    if COLUNA_PROFESSORES in df.columns:
        listas, ruins = [], []
        for pos, valor in zip(df.index, df[COLUNA_PROFESSORES]):
            logins = sorted({x.strip().lower() for x in re.split(r"[;,]", "" if pd.isna(valor) else str(valor)) if x.strip()})
            if any(not _REGEX_LOGIN_PROFESSOR.match(x) for x in logins):
                ruins.append(pos + 2)
            listas.append(";".join(logins))
        if ruins:
            erros.append(f"Coluna '{COLUNA_PROFESSORES}' tem logins inválidos (linhas {ruins[:5]}): use de 3 a 40 letras minúsculas, "
                         "números, ponto, sublinhado ou hífen, separados por ponto e vírgula.")
        df[COLUNA_PROFESSORES] = listas
    else:
        df[COLUNA_PROFESSORES] = ""

    nota = df["Admission grade"]
    fora = (nota < 0) | (nota > escala_nota_admissao)
    if fora.any():
        erros.append(f"Coluna 'nota_admissao' deve estar entre 0 e {escala_nota_admissao:g}, a escala definida em Configurações "
                     f"(linhas {list(df.index[fora][:5] + 2)}). Se a escola usa outra escala, ajuste-a em Configurações.")
    elif escala_nota_admissao != ESCALA_MODELO_NOTA_ADMISSAO:
        df["Admission grade"] = _converter_nota_admissao(nota, escala_nota_admissao)

    for c in COLUNAS_BINARIAS:
        if (~df[c].isin([0, 1]) & df[c].notna()).any():
            erros.append(f"Coluna '{_nome_pt(c)}' deve conter apenas 0 ou 1.")

    for c in ("Curricular units 1st sem (approved)", "Curricular units 1st sem (enrolled)",
              "Curricular units 2nd sem (approved)", "Curricular units 2nd sem (enrolled)"):
        if (df[c] < 0).any():
            erros.append(f"Coluna '{_nome_pt(c)}' tem valores negativos.")

    if erros:
        return None, erros
    return df, []


def montar_atributos(df):
    """
    Mesma engenharia de atributos dos notebooks 01 e 02.
    Entrada: DataFrame com as colunas do dataset UCI. Saída: DataFrame com os 6 atributos.
    """
    out = pd.DataFrame(index=df.index)
    out["Admission grade"] = df["Admission grade"]
    out["Curricular units 1st sem (grade)"] = df["Curricular units 1st sem (grade)"]
    out["Curricular units 2nd sem (grade)"] = df["Curricular units 2nd sem (grade)"]
    # Notebook 01: aprovadas / matriculadas (matriculadas = 0 vira NaN)
    out["taxa_aprovacao_1sem"] = (
        df["Curricular units 1st sem (approved)"]
        / df["Curricular units 1st sem (enrolled)"].replace(0, np.nan)
    )
    out["taxa_aprovacao_2sem"] = (
        df["Curricular units 2nd sem (approved)"]
        / df["Curricular units 2nd sem (enrolled)"].replace(0, np.nan)
    )
    # Notebook 02: indicador socioeconômico (pesos 3 / 2 / 1)
    out["indicador_socioeconomico"] = (
        3 * df["Debtor"]
        + 2 * (1 - df["Tuition fees up to date"])
        + 1 * (1 - df["Scholarship holder"])
    )
    # Notebook 02: nulos viram 0
    return out.fillna(0)


def prever(df, modelo=None, config=None):
    """Devolve (atributos, rotulos_de_risco) para um DataFrame no formato da planilha."""
    if modelo is None or config is None:
        modelo, config = carregar_modelo()
    atributos = montar_atributos(df)[config["atributos"]]
    previsoes = modelo.predict(atributos)
    return atributos, pd.Series(previsoes, index=df.index, name="risco")


def contribuicoes(atributos_linha, modelo, config, classe="Risco Alto"):
    """
    Contribuição de cada atributo para a pontuação (logit) de uma classe:
    coeficiente x valor padronizado. Positivo = empurra para essa classe.
    Usa model.classes_ (ordem alfabética) para achar a linha certa dos coeficientes.
    """
    scaler = modelo.named_steps["scaler"]
    clf = modelo.named_steps["clf"]
    idx = list(clf.classes_).index(classe)
    x = pd.DataFrame([atributos_linha], columns=config["atributos"])
    padronizado = scaler.transform(x)[0]
    contrib = clf.coef_[idx] * padronizado
    return pd.DataFrame({
        "atributo": [NOME_AMIGAVEL[a] for a in config["atributos"]],
        "valor": x.iloc[0].values,
        "contribuicao": contrib,
    }).sort_values("contribuicao", key=lambda s: -s.abs())


def probabilidades(atributos, modelo):
    """Probabilidade por classe (colunas com os rótulos de risco)."""
    p = modelo.predict_proba(atributos)
    return pd.DataFrame(p, columns=modelo.named_steps["clf"].classes_, index=atributos.index)
