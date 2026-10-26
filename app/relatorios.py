"""
Exportação de relatórios: Excel (lista priorizada filtrada) e PDF (relatório por turma, curso ou escola toda).

Por privacidade (LGPD) os arquivos trazem só a MATRÍCULA, nunca o nome do aluno.
As funções só recebem DataFrames e devolvem bytes, sem depender do Streamlit (fácil de testar).
"""
import io
from datetime import datetime

import pandas as pd

CORES = {"Risco Alto": "#B3402F", "Risco Médio": "#D9A441", "Risco Baixo": "#3C8D6E"}
ORDEM = ["Risco Alto", "Risco Médio", "Risco Baixo"]
AVISO_LGPD = ("Documento com dados sensíveis de alunos (muitos menores de idade — LGPD). "
              "Contém apenas matrículas. Use somente para ação pedagógica de apoio e não compartilhe fora da escola.")
LIMITE_LISTA_PDF = 50   # alunos de Risco Alto listados no PDF (a lista completa está no Excel)


def _agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _n(valor):
    return f"{int(valor):,}".replace(",", ".")


def _pct(parte, total):
    return f"{parte / total:.1%}".replace(".", ",") if total else "—"


# ------------------------------------------------------------------------------------------------ Excel
def lista_para_excel(tabela, filtros=(), limite_frequencia=None, prob_coluna="Prob. Risco Alto"):
    """
    Excel da lista priorizada. `tabela`: o DataFrame exatamente como aparece na tela (colunas já com nomes de exibição;
    a probabilidade em 0–100). `filtros`: pares (nome, valor) dos filtros aplicados, registrados na 2ª aba.
    """
    with io.BytesIO() as saida:
        with pd.ExcelWriter(saida, engine="xlsxwriter") as escritor:
            tabela.to_excel(escritor, sheet_name="Lista priorizada", index=False, startrow=0)
            wb, ws = escritor.book, escritor.sheets["Lista priorizada"]
            cab = wb.add_format({"bold": True, "bg_color": "#16283D", "font_color": "#FFFFFF", "border": 1, "valign": "vcenter"})
            for j, nome in enumerate(tabela.columns):
                ws.write(0, j, nome, cab)
                valores = tabela[nome].astype(str)
                largura = min(max([len(nome)] + [len(v) for v in valores.head(500)]) + 3, 42)
                ws.set_column(j, j, largura)
            ws.freeze_panes(1, 1)
            if len(tabela):
                ws.autofilter(0, 0, len(tabela), len(tabela.columns) - 1)
            if "Risco" in tabela.columns and len(tabela):
                j = list(tabela.columns).index("Risco")
                for risco, cor in CORES.items():
                    ws.conditional_format(1, j, len(tabela), j, {
                        "type": "cell", "criteria": "==", "value": f'"{risco}"',
                        "format": wb.add_format({"bg_color": cor, "font_color": "#FFFFFF", "bold": True})})
            for nome, formato in ((prob_coluna, "0.0"), ("Frequência", '0.0"%"'), ("Alertas seguidos", "0")):
                if nome in tabela.columns:
                    j = list(tabela.columns).index(nome)
                    ws.set_column(j, j, 18, wb.add_format({"num_format": formato}))
            info = escritor.book.add_worksheet("Informações")
            negrito = wb.add_format({"bold": True})
            info.set_column(0, 0, 30)
            info.set_column(1, 1, 70)
            linhas = [("Relatório", "Lista priorizada de alunos por risco de evasão"),
                      ("Gerado em", _agora()),
                      ("Alunos na lista", _n(len(tabela)))]
            if limite_frequencia is not None:
                linhas.append(("Limite de frequência", f"{limite_frequencia:g}%".replace(".", ",")))
            linhas += [(f"Filtro: {nome}", str(valor)) for nome, valor in filtros]
            if not filtros:
                linhas.append(("Filtros", "nenhum (lista completa)"))
            linhas.append(("Privacidade", AVISO_LGPD))
            for i, (k, v) in enumerate(linhas):
                info.write(i, 0, k, negrito)
                info.write(i, 1, v)
        return saida.getvalue()


# ------------------------------------------------------------------------------------------------ PDF
def _grupos(base, coluna):
    """Resumo por turma/curso: alunos por nível de risco, % de Risco Alto e frequência baixa."""
    linhas = []
    for nome, g in base.dropna(subset=[coluna]).groupby(coluna):
        c = g["risco"].value_counts()
        linhas.append([str(nome), _n(len(g)), _n(c.get("Risco Alto", 0)), _n(c.get("Risco Médio", 0)), _n(c.get("Risco Baixo", 0)),
                       _pct(c.get("Risco Alto", 0), len(g)), _n(g["freq_baixa"].sum()) if g["frequencia_pct"].notna().any() else "—",
                       c.get("Risco Alto", 0) / len(g)])
    linhas.sort(key=lambda l: -l[-1])
    return [l[:-1] for l in linhas]


def relatorio_pdf(visao, titulo_escopo, agrupar_por=None, limite_frequencia=75.0):
    """
    PDF de um recorte da escola (a `visao` já deve vir filtrada pelo escopo). `titulo_escopo`: texto como
    "Curso: Informática". `agrupar_por`: "turma" ou "curso" para incluir a tabela comparativa (None = sem tabela).
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    estilos = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=estilos["Title"], fontSize=18, textColor=colors.HexColor("#16283D"), alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=estilos["Heading2"], fontSize=12.5, textColor=colors.HexColor("#2F6F82"), spaceBefore=12, spaceAfter=5)
    txt = ParagraphStyle("txt", parent=estilos["BodyText"], fontSize=9.5, leading=13)
    mini = ParagraphStyle("mini", parent=txt, fontSize=8, textColor=colors.HexColor("#5B6470"), leading=10)

    total = len(visao)
    contagem = visao["risco"].value_counts().to_dict()
    tem_freq = bool(visao["frequencia_pct"].notna().any())
    alto = visao[visao["risco"] == "Risco Alto"]
    periodos = visao["periodo"].dropna() if "periodo" in visao else pd.Series(dtype=object)

    def tabela(dados, larguras, alinhar_direita=(), cabecalho_cor="#16283D", fonte=9):
        t = Table(dados, colWidths=larguras, repeatRows=1)
        estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(cabecalho_cor)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fonte),
                  ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F1EA")]),
                  ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5D0C2")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        estilo += [("ALIGN", (j, 0), (j, -1), "RIGHT") for j in alinhar_direita]
        t.setStyle(TableStyle(estilo))
        return t

    elementos = [Paragraph("Relatório de risco de evasão escolar", h1),
                 Paragraph(f"<b>{titulo_escopo}</b>", txt),
                 Paragraph(f"Gerado em {_agora()}"
                           + (f" · Período de referência: {periodos.iloc[0]}" if len(periodos) else "")
                           + (f" · Limite de frequência: {limite_frequencia:g}%".replace(".", ",") if tem_freq else ""), mini)]

    if total == 0:
        elementos.append(Paragraph("Nenhum aluno neste recorte.", txt))
    else:
        # resumo por nível + barra empilhada
        elementos.append(Paragraph("Resumo por nível de risco", h2))
        dados = [["Nível de risco", "Alunos", "% do total"]] + [[r, _n(contagem.get(r, 0)), _pct(contagem.get(r, 0), total)] for r in ORDEM]
        dados.append(["Total", _n(total), "100%"])
        t = tabela(dados, [6 * cm, 3 * cm, 3 * cm], alinhar_direita=(1, 2))
        t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
        elementos.append(t)
        elementos.append(Spacer(1, 8))
        larg = 17 * cm
        d = Drawing(larg, 30)
        x = 0
        for r in ORDEM:
            w = larg * contagem.get(r, 0) / total
            if w > 0:
                d.add(Rect(x, 8, w, 18, fillColor=colors.HexColor(CORES[r]), strokeColor=colors.white, strokeWidth=0.8))
                if w > 1.6 * cm:
                    d.add(String(x + w / 2, 14, f"{contagem.get(r, 0) / total:.0%}", fontSize=8.5, fillColor=colors.white,
                                 textAnchor="middle", fontName="Helvetica-Bold"))
            x += w
        elementos.append(d)

        # indicadores
        elementos.append(Paragraph("Pontos de atenção", h2))
        itens = [["Indicador", "Alunos"],
                 ["Pioraram de nível desde a avaliação anterior", _n(visao["piorou"].sum())],
                 ["Melhoraram de nível desde a avaliação anterior", _n(visao["melhorou"].sum())]]
        if tem_freq:
            itens.insert(1, [f"Frequência abaixo de {limite_frequencia:g}%".replace(".", ","), _n(visao["freq_baixa"].sum())])
            itens.append(["Frequência abaixo do limite em 2 ou mais avaliações seguidas", _n((visao["alertas_seguidos"] >= 2).sum())])
        sem_acao = int(alto["ultima_acao"].isna().sum())
        itens.append(["Risco Alto com ação pedagógica registrada", _n(len(alto) - sem_acao)])
        itens.append(["Risco Alto SEM nenhuma ação registrada", _n(sem_acao)])
        elementos.append(tabela(itens, [13 * cm, 3.5 * cm], alinhar_direita=(1,)))
        if not visao["risco_anterior"].notna().any():
            elementos.append(Paragraph("Comparação com a avaliação anterior indisponível: cada aluno tem só uma avaliação.", mini))

        # tabela comparativa
        if agrupar_por in ("turma", "curso"):
            grupos = _grupos(visao, agrupar_por)
            if grupos:
                elementos.append(Paragraph(f"Comparativo por {agrupar_por}", h2))
                cab = [agrupar_por.capitalize(), "Alunos", "Alto", "Médio", "Baixo", "% Alto", "Freq. baixa"]
                elementos.append(tabela([cab] + grupos, [5.2 * cm, 1.9 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2 * cm, 2.4 * cm],
                                        alinhar_direita=(1, 2, 3, 4, 5, 6), fonte=8.5))
                elementos.append(Paragraph("Ordenado pela proporção de Risco Alto (maior primeiro).", mini))

        # lista de risco alto
        elementos.append(Paragraph("Alunos de Risco Alto", h2))
        if alto.empty:
            elementos.append(Paragraph("Nenhum aluno de Risco Alto neste recorte.", txt))
        else:
            topo = alto.head(LIMITE_LISTA_PDF)
            cab = ["Matrícula", "Turma", "Prob.", "Freq."] + [] + ["Mudança", "Última ação"]
            linhas = []
            for _, a in topo.iterrows():
                mud = "Piorou" if a["piorou"] else ("Melhorou" if a["melhorou"] else ("Manteve" if pd.notna(a["risco_anterior"]) else "—"))
                freq = f"{a['frequencia_pct']:.0f}%" if pd.notna(a["frequencia_pct"]) else "—"
                acao = pd.to_datetime(a["ultima_acao"]).strftime("%d/%m/%Y") if pd.notna(a["ultima_acao"]) else "sem ação"
                linhas.append([str(a["matricula"]), str(a["turma"] or "—")[:18], f"{a['prob_alto']:.0f}%", freq, mud, acao])
            elementos.append(tabela([cab] + linhas, [3.2 * cm, 3.6 * cm, 1.8 * cm, 1.8 * cm, 2.6 * cm, 3 * cm], alinhar_direita=(2, 3), fonte=8.5))
            if len(alto) > len(topo):
                elementos.append(Paragraph(f"Mostrando os {len(topo)} mais críticos de {_n(len(alto))} alunos de Risco Alto. "
                                           "A lista completa está disponível em Excel na Lista priorizada.", mini))

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.2)
        canvas.setFillColor(colors.HexColor("#5B6470"))
        corte = AVISO_LGPD.rfind(" ", 0, 118)
        canvas.drawString(2 * cm, 1.1 * cm, AVISO_LGPD[:corte])
        canvas.drawString(2 * cm, 0.7 * cm, AVISO_LGPD[corte + 1:])
        canvas.drawRightString(A4[0] - 2 * cm, 0.7 * cm, f"Página {doc.page}")
        canvas.restoreState()

    with io.BytesIO() as saida:
        doc = SimpleDocTemplate(saida, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                                title="Relatório de risco de evasão escolar", author="Plataforma de prevenção da evasão")
        doc.build(elementos, onFirstPage=rodape, onLaterPages=rodape)
        return saida.getvalue()
