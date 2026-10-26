"""
Gera dados 100% fictícios para demonstração do dashboard.

- Usa as colunas numéricas do dataset público UCI (as mesmas do treino do modelo). A nota de admissão sai em 0-100 (UCI/2).
- A frequência (frequencia_pct) também é FICTÍCIA (não existe no dataset UCI e não entra no modelo).
- Os professores de cada turma (coluna professores) e as contas de demonstração prof.ana e prof.bruno também são fictícios.
- Matrícula, nome, turma e curso são INVENTADOS (semente fixa = resultado reproduzível).
- Qualquer coincidência de nome com pessoa real é acidental.

Uso (a partir da raiz do repositório):
    python dados/demo/gerar_demo.py
Saídas: dados/demo/alunos_demo.csv, dados/demo/alunos_demo_rodada2.csv (uma "segunda avaliação"
fictícia: parte dos alunos piora, parte melhora, para demonstrar o alerta de piora) e
dados/demo/modelo_planilha.csv
e a sequência de 4 planilhas numeradas do roteiro de demonstração (demo_1_... a demo_4_...),
descrita no README.
"""
import os
import sys

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
sys.path.insert(0, os.path.join(RAIZ, "app"))
from pipeline import COLUNAS_ENTRADA, COLUNA_FREQUENCIA, NOME_PT  # noqa: E402

NOMES = ["Ana", "Bruno", "Camila", "Daniel", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela",
         "João", "Karina", "Lucas", "Mariana", "Nicolas", "Olívia", "Pedro", "Quésia", "Rafael",
         "Sofia", "Thiago", "Valentina", "Wesley", "Yasmin", "Zeca", "Alice", "Bianca", "Caio",
         "Davi", "Emanuel", "Fernanda"]
SOBRENOMES = ["Almeida", "Barbosa", "Carvalho", "Dias", "Esteves", "Ferreira", "Gomes", "Henriques",
              "Ito", "Jesus", "Klein", "Lima", "Moraes", "Nascimento", "Oliveira", "Pereira",
              "Queiroz", "Ribeiro", "Silva", "Teixeira", "Uchoa", "Vasconcelos", "Xavier", "Zanetti"]
CURSOS = ["Técnico em Informática", "Técnico em Administração", "Técnico em Enfermagem",
          "Técnico em Eletrotécnica", "Técnico em Logística"]
TURMAS = ["1º A", "1º B", "2º A", "2º B", "3º A"]
# Professores FICTÍCIOS de cada turma (logins das contas de demonstração). A coluna "professores" define o que cada professor vê no app.
PROFESSORES_DEMO = {"1º A": "prof.ana", "1º B": "prof.ana", "2º A": "prof.bruno", "2º B": "prof.bruno", "3º A": "prof.ana;prof.bruno"}


def gerar_frequencia(demo, semente=99):
    """
    Frequência FICTÍCIA (%), só para demonstrar o alerta: parte da taxa de aprovação do aluno, com variação
    aleatória, e ~6% dos alunos são "faltosos com notas boas" (frequência bem menor do que as notas sugerem).
    Não vem do dataset UCI e NÃO entra no modelo.
    """
    rng = np.random.default_rng(semente)
    n = len(demo)
    taxas = []
    for sem in ("1st", "2nd"):
        matr = demo[f"Curricular units {sem} sem (enrolled)"].replace(0, np.nan)
        taxas.append(demo[f"Curricular units {sem} sem (approved)"] / matr)
    taxa = pd.concat(taxas, axis=1).mean(axis=1).fillna(0.5).to_numpy()
    freq = 62 + 33 * taxa + rng.normal(0, 8, n)
    faltoso = rng.random(n) < 0.06
    freq = freq - np.where(faltoso, rng.uniform(20, 35, n), 0)
    return np.round(np.clip(freq, 20, 100), 1)


def salvar(df, caminho):
    """
    Grava o CSV com os nomes das colunas em português (o app aceita português e inglês). A nota de admissão do dataset
    UCI está em 0-200; nos CSVs ela vai em 0-100 (dividida por 2, com 2 casas, sem perda), a escala padrão do app, que
    converte de volta para 0-200 antes de calcular o risco.
    """
    df = df.copy()
    df["Admission grade"] = (df["Admission grade"] / 2).round(2)
    df["professores"] = df["turma"].map(PROFESSORES_DEMO)
    df.rename(columns=NOME_PT).to_csv(caminho, index=False, encoding="utf-8")


def evoluir(demo, semente):
    """
    Simula a avaliação seguinte: ~8% dos alunos pioram e ~6% melhoram (notas, aprovações e,
    em parte, inadimplência). Não altera o DataFrame de entrada.
    """
    rng = np.random.default_rng(semente)
    r2 = demo.copy()
    n = len(r2)
    sorteio = rng.random(n)
    piora = sorteio < 0.08                      # ~8% pioram
    melhora = (sorteio >= 0.08) & (sorteio < 0.14)   # ~6% melhoram
    for sem in ("1st", "2nd"):
        nota = f"Curricular units {sem} sem (grade)"
        aprov = f"Curricular units {sem} sem (approved)"
        matr = f"Curricular units {sem} sem (enrolled)"
        tem_nota = r2[nota] > 0
        delta_nota = rng.uniform(2.0, 5.0, n)
        delta_aprov = rng.integers(1, 4, n)
        r2.loc[piora & tem_nota, nota] = (r2[nota] - delta_nota).clip(lower=0.5)[piora & tem_nota]
        r2.loc[piora, aprov] = (r2[aprov] - delta_aprov).clip(lower=0)[piora]
        r2.loc[melhora & tem_nota, nota] = (r2[nota] + delta_nota).clip(upper=19.5)[melhora & tem_nota]
        r2.loc[melhora, aprov] = np.minimum(r2[aprov] + delta_aprov, r2[matr])[melhora]
    # alguns que pioram também ficam inadimplentes; alguns que melhoram regularizam
    r2.loc[piora & (rng.random(n) < 0.3), "Debtor"] = 1
    r2.loc[melhora & (rng.random(n) < 0.3), "Debtor"] = 0
    if COLUNA_FREQUENCIA in r2.columns:   # a frequência acompanha a mudança: cai em quem piora, sobe em quem melhora
        var = rng.normal(0, 2, n)
        var = np.where(piora, -rng.uniform(3, 12, n), np.where(melhora, rng.uniform(2, 8, n), var))
        r2[COLUNA_FREQUENCIA] = np.round(np.clip(r2[COLUNA_FREQUENCIA] + var, 20, 100), 1)
    return r2


def gerar_rodada2(demo):
    """Simula a planilha do semestre seguinte (semente própria; não altera a 1ª rodada)."""
    salvar(evoluir(demo, 7), os.path.join(AQUI, "alunos_demo_rodada2.csv"))


CURSO_COM_ERRO = "Técnico em Logística"


def gerar_roteiro(demo):
    """
    Sequência de 4 planilhas para demonstrar, com a turma, todos os recursos de comparação:
      1 base inicial                -> 4.424 alunos (a mesma de alunos_demo.csv)
      2 nova avaliação              -> pioraram/melhoraram + 30 alunos ausentes (Divergências)
      3 planilha com erro           -> avaliação seguinte, mas um curso inteiro ficou de fora (para "Desfazer")
      4 planilha corrigida          -> a mesma avaliação, completa; 20 dos 30 ausentes voltam e 10 realmente saíram
    Sementes fixas: o resultado é sempre o mesmo. Não altera alunos_demo.csv nem alunos_demo_rodada2.csv.
    """
    rng = np.random.default_rng(2026)
    r2 = evoluir(demo, 7)
    r3 = evoluir(r2, 21)
    ausentes_2 = rng.choice(demo["matricula"].to_numpy(), 30, replace=False)     # faltam na planilha 2
    saidas = set(rng.choice(ausentes_2, 10, replace=False))                      # saíram de verdade (não voltam)
    d1 = demo
    d2 = r2[~r2["matricula"].isin(ausentes_2)]
    d4 = r3[~r3["matricula"].isin(saidas)]
    d3 = d4[d4["curso"] != CURSO_COM_ERRO]
    for nome, df in (("demo_1_base_inicial.csv", d1), ("demo_2_nova_avaliacao.csv", d2),
                     ("demo_3_planilha_com_erro.csv", d3), ("demo_4_planilha_corrigida.csv", d4)):
        salvar(df, os.path.join(AQUI, nome))
        print(f"  {nome}: {len(df)} alunos")


def main():
    rng = np.random.default_rng(42)
    raw = pd.read_csv(os.path.join(RAIZ, "dados", "raw", "dataset_uci_dropout_academic_success.csv"))
    n = len(raw)
    nomes = [f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)} {rng.choice(SOBRENOMES)}" for _ in range(n)]
    demo = pd.DataFrame({
        "matricula": [f"DEMO-{i:04d}" for i in range(1, n + 1)],
        "nome": nomes,
        "turma": rng.choice(TURMAS, n),
        "curso": rng.choice(CURSOS, n),
    })
    for c in COLUNAS_ENTRADA[4:]:
        demo[c] = raw[c].values
    demo[COLUNA_FREQUENCIA] = gerar_frequencia(demo)
    salvar(demo, os.path.join(AQUI, "alunos_demo.csv"))

    gerar_rodada2(demo)
    gerar_roteiro(demo)

    exemplo = demo.head(3).copy()
    exemplo["matricula"] = ["2026001", "2026002", "2026003"]
    exemplo["nome"] = ["Nome Exemplo Um", "Nome Exemplo Dois", "Nome Exemplo Três"]
    salvar(exemplo, os.path.join(AQUI, "modelo_planilha.csv"))
    print(f"{n} alunos fictícios gerados em dados/demo/")


if __name__ == "__main__":
    main()
