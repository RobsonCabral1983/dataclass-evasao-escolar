"""
Dashboard de prevenção da evasão escolar (Streamlit).

Rodar localmente, a partir da raiz do repositório:
    streamlit run app/dashboard.py

Acesso por login e senha próprios (perfis Administrador, Coordenação e Professor). Sem nenhum
usuário e sem o administrador inicial nos Secrets (admin_login e admin_senha), o app NÃO abre (falha fechada).
"""
import io
import os
import re
import sys
import time
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
for caminho in (AQUI, RAIZ):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

import frequencia  # noqa: E402
import inatividade  # noqa: E402
import permissoes  # noqa: E402
import pipeline  # noqa: E402
import relatorios  # noqa: E402
import traducao  # noqa: E402
import servico  # noqa: E402
from banco import auditoria, database, retencao, usuarios  # noqa: E402

st.set_page_config(page_title="Prevenção de Evasão Escolar", page_icon="🎓", layout="wide")

CORES = {"Risco Alto": "#B3402F", "Risco Médio": "#D9A441", "Risco Baixo": "#3C8D6E"}
ORDEM = ["Risco Alto", "Risco Médio", "Risco Baixo"]
CAMINHO_DEMO = os.path.join(RAIZ, "dados", "demo", "alunos_demo.csv")
CAMINHO_TEMPLATE = os.path.join(RAIZ, "dados", "demo", "modelo_planilha.csv")
CAMINHO_DEMO2 = os.path.join(RAIZ, "dados", "demo", "alunos_demo_rodada2.csv")
ESCALA_DEMO = 100.0   # escala da nota de admissão nos CSVs de demonstração
NOME_DEMO = "alunos_demo.csv (dados fictícios)"
NOME_DEMO2 = "alunos_demo_rodada2.csv (dados fictícios)"
NIVEL = {"Risco Baixo": 0, "Risco Médio": 1, "Risco Alto": 2}   # maior = mais grave
OPCOES_MUDANCA = ["Todos", "Somente quem piorou", "Somente quem melhorou"]
OPCOES_ACAO = ["Todos", "Somente sem ação registrada", "Somente com ação registrada"]
OPCOES_FREQUENCIA = ["Todos", "Somente abaixo do limite"]
TIPOS_ACAO = ["Conversa com a família", "Conversa com o aluno", "Reforço escolar",
              "Encaminhamento (psicólogo / assistência social)", "Acompanhamento de frequência", "Outro"]

TELA_DIVERGENCIAS = "Divergências"
TELAS = permissoes.TODAS_AS_TELAS   # o menu de cada pessoa é filtrado pelo perfil; "Divergências" só entra quando houver alunos ausentes

PASSO_A_PASSO = """
1. Exporte a planilha atualizada com **todos os alunos matriculados**, nas mesmas colunas do modelo. A **matrícula** de cada aluno deve ser a mesma da avaliação anterior: é ela que liga o aluno ao histórico.
2. Envie o arquivo abaixo e clique em **Processar planilha**. Se o conteúdo for idêntico ao de uma planilha já enviada, o app avisa antes.
3. Na **Visão geral**, veja os cards **Pioraram** e **Melhoraram** (comparação com a avaliação anterior).
4. Se aparecer o card **Divergências**, são alunos da avaliação anterior que não estão na nova planilha. Confira com a secretaria: se foi erro de arquivo, envie a planilha corrigida e completa; se o aluno saiu da escola, não precisa fazer nada.
"""
# Estados que precisam sobreviver quando o usuário troca de tela (filtros da lista, aluno da ficha)
ESTADO_PERSISTENTE = ["f_risco", "f_curso", "f_turma", "f_busca", "f_mudanca", "f_acao", "f_freq", "f_matricula", "detalhar_por",
                      "responsavel_acao", "motivo_resolucao", "ver_resolvidas", "f_faixa", "f_alerta", "rel_escopo", "rel_escopo_prof", "rel_curso", "rel_turma"]


# ----------------------------------------------------------------- navegação por clique
# Estas funções rodam como "callbacks": o Streamlit as executa ANTES de redesenhar a página,
# por isso podem trocar de tela e preencher filtros com segurança.
def ir_para_lista(riscos=None, cursos=None, turmas=None, mudanca="Todos", frequencia="Todos"):
    st.session_state["f_risco"] = list(riscos or [])
    st.session_state["f_mudanca"] = mudanca
    st.session_state["f_acao"] = "Todos"
    st.session_state["f_freq"] = frequencia
    st.session_state["f_faixa"] = []
    st.session_state["f_alerta"] = "Todos"
    st.session_state["f_curso"] = list(cursos or [])
    st.session_state["f_turma"] = list(turmas or [])
    st.session_state["f_busca"] = ""
    st.session_state["tela"] = "Lista priorizada"


def ir_para_ficha(matricula):
    st.session_state["f_matricula"] = matricula
    st.session_state["tela"] = "Ficha do aluno"


def voltar_para_lista():
    st.session_state["tela"] = "Lista priorizada"


def voltar_para_visao_geral():
    st.session_state["tela"] = "Visão geral"


def ir_para_divergencias():
    st.session_state["tela"] = TELA_DIVERGENCIAS


def _selecao_grafico(chave):
    """Itens clicados num gráfico Altair (lista vazia se nada foi selecionado)."""
    try:
        return list(st.session_state[chave]["selection"]["sel"])
    except Exception:  # noqa: BLE001
        return []


def ao_clicar_barra_risco():
    sel = _selecao_grafico("graf_risco")
    if sel:
        ir_para_lista(riscos=[sel[0]["risco"]])


def ao_clicar_barra_detalhe(agrupar):
    sel = _selecao_grafico(f"graf_detalhe_{agrupar}")
    if not sel:
        return
    item = sel[0]
    filtros = {"cursos": [item[agrupar]]} if agrupar == "curso" else {"turmas": [item[agrupar]]}
    ir_para_lista(riscos=[item["risco"]], **filtros)


def ao_selecionar_linha():
    """Clique numa linha da lista priorizada -> abre a ficha daquele aluno."""
    try:
        linhas = st.session_state["tabela_lista"]["selection"]["rows"]
        matriculas = st.session_state["_matriculas_lista"]
        if linhas:
            ir_para_ficha(matriculas[linhas[0]])
    except Exception:  # noqa: BLE001
        pass


def manter_estado():
    """Evita que o Streamlit apague filtros/seleções ao sair de uma tela e voltar depois."""
    for chave in ESTADO_PERSISTENTE:
        if chave in st.session_state:
            st.session_state[chave] = st.session_state[chave]


CORES_CARDS = {"card_total": "#2F6F82", "card_alto": "#B3402F", "card_medio": "#D9A441",
               "card_baixo": "#3C8D6E", "card_piorou": "#6B4E9B", "card_melhorou": "#3A6EA5",
               "card_diverg": "#8C5E2A", "card_diverg_zero": "#B8BCC2",
               "card_freq": "#CF6A32", "card_freq_zero": "#B8BCC2"}


def _estilo_cards():
    def alvo(sufixo=""):
        return ", ".join(f".st-key-{k} button{sufixo}" for k in CORES_CARDS)

    cores = "\n".join(f".st-key-{k} button {{ border-left-color: {c}; }}" for k, c in CORES_CARDS.items())
    return f"""
<style>
{alvo()} {{
    height: auto; min-height: 0; padding: 14px 18px; display: block; text-align: left;
    background: #FFFFFF; border: 1px solid #E1DCCF; border-radius: 14px; border-left-width: 8px;
}}
{cores}
{alvo(":hover")} {{ box-shadow: 0 3px 10px rgba(22, 40, 61, 0.18); border-color: #2F6F82; }}
{alvo(":disabled")} {{ opacity: 1; cursor: default; box-shadow: none; border-color: #E1DCCF; }}
.st-key-card_diverg_zero button p, .st-key-card_freq_zero button p {{ color: #8A8F98 !important; }}
{alvo(" > div")} {{ display: block; width: 100%; text-align: left; }}
{alvo(" p")} {{ display: block; margin: 0; text-align: left; }}
{alvo(" p:first-child")} {{ font-size: 0.95rem; color: #4A5568; white-space: nowrap; }}
{alvo(" p:last-child")} {{ font-size: 2.3rem; font-weight: 600; color: #16283D; line-height: 1.25; }}
</style>
"""


ESTILO_CARDS = _estilo_cards()


# ----------------------------------------------------------------- acesso
def _segredo(chave, padrao=None):
    try:
        return st.secrets[chave]
    except Exception:
        return padrao


SENHA_DEMO = "demonstracao-2026"
CONTAS_DEMO = (("demo.admin", "Administração (demonstração)", "admin"), ("demo.coord", "Coordenação (demonstração)", "coordenacao"),
               ("prof.ana", "Profa. Ana (demonstração)", "professor"), ("prof.bruno", "Prof. Bruno (demonstração)", "professor"))


def garantir_contas_demo():
    """Só no deploy de demonstração (demo_automatica = true): cria contas FICTÍCIAS dos três perfis, com senha pública."""
    if not bool(_segredo("demo_automatica", False)):
        return
    existentes = {u["login"] for u in usuarios.listar_usuarios()}
    for login, nome, perfil in CONTAS_DEMO:
        if login not in existentes:
            usuarios.criar_usuario(login, nome, perfil, SENHA_DEMO, trocar_senha=False)


def _auditar(evento, aluno=None, detalhe=None, login=None):
    """Registra um evento na trilha de auditoria em nome do usuário logado (ou do 'login' informado, ex.: tentativa de login)."""
    auditoria.registrar(evento, st.session_state.get("usuario"), login=login, aluno=aluno, detalhe=detalhe)


def _sair():
    if st.session_state.get("usuario"):
        _auditar("logout")
    st.session_state.clear()


def _encerrar_por_inatividade():
    """Encerra a sessão por falta de uso, registra na trilha e deixa um aviso para a tela de login."""
    if st.session_state.get("usuario"):
        _auditar("sessao_expirada", detalhe=f"mais de {_fmt_limite(inatividade.minutos_validos(_segredo('inatividade_minutos', inatividade.MINUTOS_PADRAO)))} minutos sem uso")
    st.session_state.clear()
    st.session_state["_aviso_login"] = "Sua sessão foi encerrada por inatividade. Entre de novo para continuar."


def exigir_login():
    """
    Bloqueia o app até o login. Falha fechada: sem nenhum usuário e sem o administrador inicial nos Secrets, nada abre.
    Devolve o usuário logado (dict) já atualizado a partir do banco (perfil, turmas e situação mudam sem novo login).
    """
    if usuarios.contar_usuarios() == 0:
        login, senha = _segredo("admin_login"), _segredo("admin_senha")
        if not (login and senha):
            st.error("Acesso bloqueado: ainda não há nenhum usuário. Configure o administrador inicial em `.streamlit/secrets.toml` "
                     "(`admin_login` e `admin_senha`; veja `secrets.toml.example`) ou nos Secrets do Streamlit Cloud.")
            st.stop()
        try:
            usuarios.garantir_admin_inicial(str(login), str(senha))
        except ValueError as e:
            st.error(f"Não foi possível criar o administrador inicial: {e}")
            st.stop()
    garantir_contas_demo()

    minutos = inatividade.minutos_validos(_segredo("inatividade_minutos", inatividade.MINUTOS_PADRAO))
    atual = st.session_state.get("usuario")
    if atual and inatividade.expirou(st.session_state.get("ultima_atividade"), time.time(), minutos):
        _encerrar_por_inatividade()   # a pessoa voltou depois do prazo (ou o navegador não conseguiu avisar)
        atual = None
    if atual:
        fresco = usuarios.obter_usuario(atual["id_usuario"])
        if fresco and fresco["ativo"]:
            st.session_state["usuario"] = fresco
            st.session_state["ultima_atividade"] = time.time()
            inatividade.vigiar(minutos, _encerrar_por_inatividade)
            if fresco["trocar_senha"]:
                tela_trocar_senha(fresco, obrigatoria=True)
                st.stop()
            return fresco
        _sair()   # usuário desativado ou apagado: encerra a sessão

    st.title("🎓 Prevenção de Evasão Escolar")
    st.caption("Acesso restrito. Entre com o seu login e a sua senha.")
    aviso = st.session_state.pop("_aviso_login", None)
    if aviso:
        st.warning(aviso)
    if bool(_segredo("demo_automatica", False)):
        st.info("**Demonstração com dados fictícios.** Logins: `demo.admin`, `demo.coord`, `prof.ana` ou `prof.bruno` — "
                f"senha `{SENHA_DEMO}`.")
    with st.form("login"):
        login = st.text_input("Login")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        usuario, erro = usuarios.autenticar(login, senha)
        if usuario:
            st.session_state["usuario"] = usuario
            st.session_state["ultima_atividade"] = time.time()
            _auditar("login")
            st.rerun()
        _auditar("login_falha", login=usuarios.normalizar_login(login) or "(em branco)",
                 detalhe="usuário bloqueado" if "bloqueado" in erro else "login ou senha incorretos")
        st.error(erro)
    st.stop()


def tela_trocar_senha(usuario, obrigatoria=False):
    """Troca da própria senha (obrigatória no primeiro acesso ou depois de uma redefinição pelo administrador)."""
    if obrigatoria:
        st.title("🎓 Prevenção de Evasão Escolar")
        st.warning(f"Olá, **{usuario['nome']}**. Por segurança, crie agora a sua senha pessoal para continuar.")
    else:
        st.header("Minha conta")
        st.write(f"**{usuario['nome']}** · login `{usuario['login']}` · perfil **{usuarios.PERFIS[usuario['perfil']]}**")
        if usuario["perfil"] == "professor":
            turmas = usuario.get("turmas") or []
            st.write("**Turmas:** " + (", ".join(turmas) if turmas else "nenhuma atribuída ainda (a atribuição vem da coluna `professores` da planilha)"))
        st.subheader("Trocar senha")
    mensagem = st.session_state.pop("_msg_senha", None)
    if mensagem:
        st.success(mensagem)
    with st.form(f"form_senha_{'obrig' if obrigatoria else 'conta'}", clear_on_submit=True):
        atual = st.text_input("Senha atual", type="password")
        nova = st.text_input(f"Nova senha (mínimo {usuarios.TAMANHO_MINIMO_SENHA} caracteres)", type="password")
        repete = st.text_input("Repita a nova senha", type="password")
        salvar = st.form_submit_button("Salvar nova senha", type="primary")
    if salvar:
        if nova != repete:
            st.error("A nova senha e a repetição não são iguais.")
        else:
            try:
                usuarios.trocar_propria_senha(usuario["id_usuario"], atual, nova)
            except ValueError as e:
                st.error(str(e))
            else:
                _auditar("senha_trocada")
                st.session_state["_msg_senha"] = "Senha alterada."
                st.rerun()
    if obrigatoria:
        st.button("Sair", on_click=_sair)


# ----------------------------------------------------------------- dados
@st.cache_resource(show_spinner=False)
def carregar_modelo():
    return pipeline.carregar_modelo()


def carregar_demo(automatica=False):
    df = pd.read_csv(CAMINHO_DEMO)
    # os dados de demonstração estão na escala 0-100, qualquer que seja a escala configurada para a escola
    resultado = servico.processar_e_gravar(df, NOME_DEMO, *carregar_modelo(), escala_nota_admissao=ESCALA_DEMO)
    if automatica:   # carga feita pelo próprio sistema (deploy de demonstração), não por uma pessoa
        auditoria.registrar("envio_planilha", login="sistema", detalhe=f"carga automática dos dados de demonstração ({NOME_DEMO})")
    else:
        _auditar("envio_planilha", detalhe=f"dados de demonstração ({NOME_DEMO})")
    return resultado


def carregar_demo_rodada2():
    df = pd.read_csv(CAMINHO_DEMO2)
    resultado = servico.processar_e_gravar(df, NOME_DEMO2, *carregar_modelo(), escala_nota_admissao=ESCALA_DEMO)
    _auditar("envio_planilha", detalhe=f"dados de demonstração ({NOME_DEMO2})")
    return resultado


def enriquecer_visao(visao, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO):
    """
    Acrescenta à visão: probabilidade de Risco Alto, quem piorou/melhorou desde a avaliação
    anterior, quem está com frequência abaixo do limite da escola e a ordem final (nível de risco;
    dentro dele, o mais crítico primeiro).
    """
    if visao.empty:
        return visao
    modelo, config = carregar_modelo()
    colunas_banco = [pipeline.ATRIBUTO_PARA_BANCO[a] for a in config["atributos"]]
    x = visao[colunas_banco].fillna(0).copy()
    x.columns = config["atributos"]
    visao = visao.copy()
    visao["freq_baixa"] = visao["frequencia_pct"].notna() & (visao["frequencia_pct"] < limite_frequencia)
    visao["prob_alto"] = pipeline.probabilidades(x, modelo)["Risco Alto"].values * 100
    # histórico de alertas: com o limite atual, quantas avaliações seguidas (até a última) ficaram abaixo dele
    historico_freq = database.buscar_frequencias()
    situacoes = [frequencia.situacao_alerta(historico_freq.get(i), limite_frequencia) for i in visao["id_aluno"]]
    visao["alertas_seguidos"] = [a for a, _ in situacoes]
    visao["situacao_alerta"] = [sit for _, sit in situacoes]
    faixas = frequencia.faixas_frequencia(limite_frequencia)
    visao["faixa_freq"] = [frequencia.rotulo_faixa(v, faixas) for v in visao["frequencia_pct"]]

    nivel = visao["risco"].map(NIVEL)
    anterior = visao["risco_anterior"].map(NIVEL)
    visao["piorou"] = anterior.notna() & (nivel > anterior)
    visao["melhorou"] = anterior.notna() & (nivel < anterior)

    def descrever(atual, antes):
        if pd.isna(antes):
            return "—"
        a, b = atual.replace("Risco ", ""), antes.replace("Risco ", "")
        if NIVEL[atual] > NIVEL[antes]:
            return f"▲ Piorou: {b} → {a}"
        if NIVEL[atual] < NIVEL[antes]:
            return f"▼ Melhorou: {b} → {a}"
        return "Manteve"

    visao["mudanca"] = [descrever(a, b) for a, b in zip(visao["risco"], visao["risco_anterior"])]
    return visao.assign(_ordem=-nivel).sort_values(["_ordem", "prob_alto"], ascending=[True, False]).drop(columns="_ordem").reset_index(drop=True)


def garantir_banco_demo():
    """No Streamlit Cloud o banco é recriado a cada reinício; com 'demo_automatica' = true recarregamos os dados fictícios."""
    if bool(_segredo("demo_automatica", False)) and database.contar_alunos() == 0:
        with st.spinner("Carregando dados fictícios de demonstração..."):
            carregar_demo(automatica=True)


def grafico_barras_risco(contagem):
    df = pd.DataFrame({"risco": ORDEM, "alunos": [contagem.get(r, 0) for r in ORDEM]})
    selecao = alt.selection_point(name="sel", fields=["risco"])
    return (
        alt.Chart(df)
        .mark_bar(cursor="pointer")
        .add_params(selecao)
        .encode(
            x=alt.X("risco:N", sort=ORDEM, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("alunos:Q", title="Alunos", axis=alt.Axis(format="d")),
            color=alt.Color("risco:N", scale=alt.Scale(domain=ORDEM, range=[CORES[r] for r in ORDEM]), legend=None),
            tooltip=["risco", "alunos"],
        )
        .properties(height=320)
    )


# ----------------------------------------------------------------- telas
def tela_visao_geral(visao, n_divergencias=0, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO, n_resolvidas=0, mostrar_divergencias=True):
    st.header("Visão geral")
    if visao.empty:
        st.info("Ainda não há alunos no banco. Vá em **Upload de dados** para carregar uma planilha ou os dados de demonstração.")
        return

    total = len(visao)
    contagem = visao["risco"].value_counts().to_dict()
    st.markdown(ESTILO_CARDS, unsafe_allow_html=True)
    st.caption("Clique em um card ou em uma barra para ver a lista dos alunos daquele grupo.")

    def fmt(n):
        return f"{n:,}".replace(",", ".")

    st.caption("**Situação atual**")
    cols = st.columns(5)
    with cols[0]:
        st.button(f"Alunos avaliados\n\n{fmt(total)}", key="card_total", on_click=ir_para_lista, width="stretch")
        st.caption("Ver todos")
    for col, r, chave in zip(cols[1:4], ORDEM, ["card_alto", "card_medio", "card_baixo"]):
        n = contagem.get(r, 0)
        with col:
            st.button(f"{r}\n\n{fmt(n)}", key=chave, on_click=ir_para_lista, kwargs={"riscos": [r]}, width="stretch")
            st.caption(f"{n / total:.1%} do total".replace(".", ","))
    with cols[4]:
        # alerta por regra (não é previsão do modelo): frequência abaixo do limite que a escola define em Configurações
        com_freq = int(visao["frequencia_pct"].notna().sum())
        if com_freq:
            n_freq = int(visao["freq_baixa"].sum())
            st.button(f"Frequência baixa\n\n{fmt(n_freq)}", key="card_freq", on_click=ir_para_lista,
                      kwargs={"frequencia": "Somente abaixo do limite"}, width="stretch")
            st.caption(f"abaixo de {_fmt_limite(limite_frequencia)}% de frequência")
        else:
            st.button("Frequência baixa\n\n—", key="card_freq_zero", disabled=True, width="stretch")
            st.caption("planilha sem frequência")

    st.caption("**Mudanças desde a avaliação anterior**")
    tem_anterior = visao["risco_anterior"].notna().any()
    cols = st.columns(3)
    with cols[0]:
        st.button(f"Pioraram\n\n{fmt(int(visao['piorou'].sum()))}", key="card_piorou", on_click=ir_para_lista,
                  kwargs={"mudanca": "Somente quem piorou"}, width="stretch")
        st.caption("subiram de nível" if tem_anterior else "precisa de 2 avaliações por aluno")
    with cols[1]:
        st.button(f"Melhoraram\n\n{fmt(int(visao['melhorou'].sum()))}", key="card_melhorou", on_click=ir_para_lista,
                  kwargs={"mudanca": "Somente quem melhorou"}, width="stretch")
        st.caption("desceram de nível" if tem_anterior else "precisa de 2 avaliações por aluno")
    with cols[2]:
        # sempre visível para quem resolve divergências: com 0 fica cinza e sem clique; com ausentes ganha destaque e abre a lista
        if not mostrar_divergencias:   # professor não vê divergências
            pass
        elif n_divergencias:
            st.button(f"Divergências\n\n{fmt(n_divergencias)}", key="card_diverg", on_click=ir_para_divergencias, width="stretch")
            st.caption("alunos de antes que não estão na última planilha")
        elif n_resolvidas:   # nada pendente, mas há ausências já conferidas: o card cinza abre o histórico
            st.button("Divergências\n\n0", key="card_diverg_zero", on_click=ir_para_divergencias, width="stretch")
            st.caption(f"{fmt(n_resolvidas)} já conferida(s) · clique para ver")
        else:
            st.button("Divergências\n\n0", key="card_diverg_zero", disabled=True, width="stretch")
            st.caption("nenhum aluno ausente da última planilha")

    esq, dir_ = st.columns([1, 1.4])
    with esq:
        st.subheader("Distribuição de risco")
        st.altair_chart(grafico_barras_risco(contagem), width="stretch", key="graf_risco",
                        on_select=ao_clicar_barra_risco, selection_mode="sel")
    with dir_:
        agrupar = st.radio("Detalhar por", ["curso", "turma"], horizontal=True, key="detalhar_por")
        st.subheader(f"Risco por {agrupar}")
        base = visao.dropna(subset=[agrupar])
        if base.empty:
            st.caption("Sem informação de " + agrupar + " nos dados.")
        else:
            tab = base.groupby([agrupar, "risco"]).size().reset_index(name="alunos")
            selecao = alt.selection_point(name="sel", fields=[agrupar, "risco"])
            graf = (
                alt.Chart(tab)
                .mark_bar(cursor="pointer")
                .add_params(selecao)
                .encode(
                    y=alt.Y(f"{agrupar}:N", title=None, sort="-x", axis=alt.Axis(labelLimit=260)),
                    x=alt.X("alunos:Q", stack="normalize", title="Proporção de alunos", axis=alt.Axis(format="%")),
                    color=alt.Color("risco:N", scale=alt.Scale(domain=ORDEM, range=[CORES[r] for r in ORDEM]), title=None),
                    tooltip=[agrupar, "risco", "alunos"],
                )
                .properties(height=320)
            )
            st.altair_chart(graf, width="stretch", key=f"graf_detalhe_{agrupar}",
                            on_select=lambda: ao_clicar_barra_detalhe(agrupar), selection_mode="sel")


def tela_lista(visao, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO):
    st.button("← Voltar à Visão geral", on_click=voltar_para_visao_geral)
    st.header("Lista priorizada")
    st.caption("Alunos ordenados por nível de risco e, dentro de cada nível, pela probabilidade de Risco Alto (mais críticos primeiro). Por privacidade, esta lista mostra só a matrícula — o nome aparece na **Ficha do aluno**.")
    if visao.empty:
        st.info("Nenhum aluno no banco ainda.")
        return

    opcoes_curso = sorted(visao["curso"].dropna().unique())
    opcoes_turma = sorted(visao["turma"].dropna().unique())
    st.session_state.setdefault("f_risco", ["Risco Alto"])
    # descarta valores de filtro que não existem mais nos dados (evita erro do multiselect)
    for chave, opcoes in (("f_risco", ORDEM), ("f_curso", opcoes_curso), ("f_turma", opcoes_turma)):
        st.session_state[chave] = [v for v in st.session_state.get(chave, []) if v in opcoes]
    st.session_state.setdefault("f_busca", "")
    if st.session_state.get("f_mudanca") not in OPCOES_MUDANCA:
        st.session_state["f_mudanca"] = "Todos"
    if st.session_state.get("f_acao") not in OPCOES_ACAO:
        st.session_state["f_acao"] = "Todos"
    if st.session_state.get("f_freq") not in OPCOES_FREQUENCIA:
        st.session_state["f_freq"] = "Todos"
    tem_freq = bool(visao["frequencia_pct"].notna().any())
    faixas = [r for r, _, _ in frequencia.faixas_frequencia(limite_frequencia)]   # mudam junto com o limite
    st.session_state["f_faixa"] = [v for v in st.session_state.get("f_faixa", []) if v in faixas]
    if st.session_state.get("f_alerta") not in frequencia.OPCOES_SITUACAO:
        st.session_state["f_alerta"] = "Todos"

    c1, c2, c3 = st.columns(3)
    riscos = c1.multiselect("Nível de risco", ORDEM, key="f_risco")
    cursos = c2.multiselect("Curso", opcoes_curso, key="f_curso")
    turmas = c3.multiselect("Turma", opcoes_turma, key="f_turma")
    b1, b2, b3, b4 = st.columns([1.2, 1, 1, 1])
    busca = b1.text_input("Buscar matrícula", key="f_busca")
    mudanca = b2.selectbox("Mudança desde a última avaliação", OPCOES_MUDANCA, key="f_mudanca",
                           help="Piorou = o nível de risco subiu em relação à avaliação anterior; melhorou = desceu.")
    acao = b3.selectbox("Ações pedagógicas", OPCOES_ACAO, key="f_acao",
                        help="Útil para achar alunos de risco que ainda não receberam nenhuma ação registrada.")
    freq = b4.selectbox("Frequência", OPCOES_FREQUENCIA, key="f_freq",
                        help=f"Abaixo do limite = frequência menor que {_fmt_limite(limite_frequencia)}% (o limite é definido em Configurações). "
                             "Alunos sem frequência informada não entram neste filtro.")

    faixa_sel, alerta = [], "Todos"
    if tem_freq:
        d1, d2, _ = st.columns([1.4, 1.2, 1.4])
        faixa_sel = d1.multiselect("Faixa de frequência", faixas, key="f_faixa", placeholder="Todas as faixas",
                                   help=f"Faixas calculadas a partir do limite de {_fmt_limite(limite_frequencia)}% (Configurações).")
        alerta = d2.selectbox("Situação do alerta", frequencia.OPCOES_SITUACAO, key="f_alerta",
                              help="Novo alerta = abaixo do limite agora e não estava antes. Reincidente = 2 ou mais avaliações seguidas abaixo do limite. "
                                   "Saiu do alerta = estava abaixo antes e agora está no limite ou acima. O limite atual vale para todo o histórico.")

    filtrado = visao
    if riscos:
        filtrado = filtrado[filtrado["risco"].isin(riscos)]
    if cursos:
        filtrado = filtrado[filtrado["curso"].isin(cursos)]
    if turmas:
        filtrado = filtrado[filtrado["turma"].isin(turmas)]
    if busca:
        filtrado = filtrado[filtrado["matricula"].str.contains(busca, case=False, na=False)]
    if mudanca == "Somente quem piorou":
        filtrado = filtrado[filtrado["piorou"]]
    elif mudanca == "Somente quem melhorou":
        filtrado = filtrado[filtrado["melhorou"]]
    if acao == "Somente sem ação registrada":
        filtrado = filtrado[filtrado["ultima_acao"].isna()]
    elif acao == "Somente com ação registrada":
        filtrado = filtrado[filtrado["ultima_acao"].notna()]

    if freq == "Somente abaixo do limite":
        filtrado = filtrado[filtrado["freq_baixa"]]

    if faixa_sel:
        filtrado = filtrado[filtrado["faixa_freq"].isin(faixa_sel)]
    if alerta != "Todos":
        filtrado = filtrado[filtrado["situacao_alerta"] == alerta]

    st.write(f"**{len(filtrado):,}** aluno(s) encontrados.".replace(",", "."))
    colunas_lista = ["matricula", "turma", "curso", "risco", "prob_alto", "frequencia_pct", "alertas_seguidos", "mudanca", "ultima_acao", "data_avaliacao"]
    if not visao["frequencia_pct"].notna().any():   # planilhas sem frequência: a coluna só ocuparia espaço
        colunas_lista.remove("frequencia_pct")
        colunas_lista.remove("alertas_seguidos")
    if filtrado["periodo"].notna().any():   # coluna "Período" só aparece quando alguma planilha informou o período
        colunas_lista.insert(len(colunas_lista) - 1, "periodo")
    tabela = filtrado[colunas_lista].copy()
    tabela["ultima_acao"] = tabela["ultima_acao"].map(_fmt_data_curta)
    tabela["data_avaliacao"] = tabela["data_avaliacao"].map(_fmt_data_curta)
    tabela = tabela.rename(
        columns={"matricula": "Matrícula", "turma": "Turma", "curso": "Curso", "risco": "Risco",
                 "prob_alto": "Prob. Risco Alto", "mudanca": "Mudança", "ultima_acao": "Última ação",
                 "periodo": "Período", "data_avaliacao": "Avaliado em", "frequencia_pct": "Frequência", "alertas_seguidos": "Alertas seguidos"}
    )
    st.caption("Marque a caixinha à esquerda de uma linha para abrir a ficha do aluno.")
    st.session_state["_matriculas_lista"] = tabela["Matrícula"].tolist()
    st.dataframe(tabela, hide_index=True, width="stretch", height=440, key="tabela_lista",
                 on_select=ao_selecionar_linha, selection_mode="single-row",
                 column_config={"Alertas seguidos": st.column_config.NumberColumn(
                     "Alertas seguidos", format="%d", help="Quantas avaliações seguidas, até a última, ficaram com frequência abaixo do limite (0 = última avaliação ok)."),
                     "Frequência": st.column_config.NumberColumn(
                     "Frequência", format="%.0f%%", help=f"Limite atual: {_fmt_limite(limite_frequencia)}%. Não entra no modelo de risco."),
                     "Prob. Risco Alto": st.column_config.ProgressColumn(
                     "Prob. Risco Alto", format="%.0f%%", min_value=0, max_value=100,
                     help="Probabilidade estimada pelo modelo de o aluno ser Risco Alto. Dentro de cada nível, a lista começa pelos mais críticos.")})
    filtros_aplicados = [(nome, valor) for nome, valor in (
        ("Nível de risco", ", ".join(riscos)), ("Curso", ", ".join(cursos)), ("Turma", ", ".join(turmas)),
        ("Matrícula contém", busca), ("Mudança", mudanca if mudanca != "Todos" else ""),
        ("Ações pedagógicas", acao if acao != "Todos" else ""), ("Frequência", freq if freq != "Todos" else ""),
        ("Faixa de frequência", ", ".join(faixa_sel)), ("Situação do alerta", alerta if alerta != "Todos" else "")) if valor]
    b_csv, b_xlsx, _ = st.columns([1, 1, 3])
    b_csv.download_button("Baixar lista filtrada (CSV)", tabela.to_csv(index=False).encode("utf-8"),
                          "lista_priorizada.csv", "text/csv")
    b_xlsx.download_button("Baixar lista filtrada (Excel)",
                           relatorios.lista_para_excel(tabela, filtros_aplicados, limite_frequencia if tem_freq else None),
                           "lista_priorizada.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _fmt_limite(valor):
    """75.0 -> '75'; 72.5 -> '72,5'."""
    return f"{valor:g}".replace(".", ",")


def _fmt_data_segundos(texto):
    """'2026-10-19 14:02:53' -> '19/10/2026 14:02:53'."""
    try:
        return pd.to_datetime(texto).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:  # noqa: BLE001
        return str(texto or "—")


def _fmt_data(texto):
    """'2026-10-19 14:02:53' -> '19/10/2026 14:02' (devolve '—' se vazio)."""
    if not texto:
        return "—"
    try:
        return pd.to_datetime(texto).strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(texto)


MOTIVO_PADRAO_RESOLUCAO = database.MOTIVOS_RESOLUCAO[0]


def _tabela_divergencias(df, resolvidas=False):
    """Tabela de exibição das divergências (só matrícula, nunca o nome)."""
    colunas = ["matricula", "turma", "curso", "risco", "data_avaliacao", "ausente_desde"]
    nomes = {"matricula": "Matrícula", "turma": "Turma", "curso": "Curso", "risco": "Último risco",
             "data_avaliacao": "Última avaliação", "ausente_desde": "Ausente desde"}
    if resolvidas:
        colunas += ["motivo", "responsavel_resolucao", "resolvido_em"]
        nomes.update({"motivo": "Motivo", "responsavel_resolucao": "Responsável", "resolvido_em": "Resolvida em"})
    tabela = df[colunas].copy()
    for c in ("data_avaliacao", "ausente_desde", "resolvido_em"):
        if c in tabela:
            tabela[c] = tabela[c].map(_fmt_data)
    return tabela.rename(columns=nomes)


def _linhas_selecionadas(evento):
    try:
        return list(evento.selection.rows)
    except Exception:  # noqa: BLE001
        return []


def tela_relatorios(visao, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO, restrito=False):
    st.header("Relatórios")
    if visao.empty:
        st.info("Ainda não há alunos no banco.")
        return
    st.write("Gere um **relatório em PDF** de uma turma, de um curso ou " + ("das suas turmas" if restrito else "da escola toda") + ": totais por nível de risco, pontos de atenção "
             "(piorou, frequência, ações registradas), comparativo e a lista dos alunos de Risco Alto.")
    st.caption("Para a lista completa em planilha, use **Baixar lista filtrada (Excel)** na Lista priorizada. Os arquivos trazem só a matrícula, nunca o nome.")
    todo = "Minhas turmas" if restrito else "Escola toda"
    escopo = st.radio("Escopo", [todo, "Um curso", "Uma turma"], horizontal=True, key="rel_escopo_prof" if restrito else "rel_escopo")
    base, titulo, agrupar = visao, todo, "curso"
    if escopo == "Um curso":
        opcoes = sorted(visao["curso"].dropna().unique())
        if not opcoes:
            st.info("Os dados não têm informação de curso.")
            return
        curso = st.selectbox("Curso", opcoes, key="rel_curso")
        base, titulo, agrupar = visao[visao["curso"] == curso], f"Curso: {curso}", "turma"
    elif escopo == "Uma turma":
        opcoes = sorted(visao["turma"].dropna().unique())
        if not opcoes:
            st.info("Os dados não têm informação de turma.")
            return
        turma = st.selectbox("Turma", opcoes, key="rel_turma")
        base, titulo, agrupar = visao[visao["turma"] == turma], f"Turma: {turma}", None
    st.write(f"**{len(base):,}** aluno(s) no recorte, **{int((base['risco'] == 'Risco Alto').sum()):,}** de Risco Alto.".replace(",", "."))
    nome_arquivo = "relatorio_" + re.sub(r"[^A-Za-z0-9]+", "_", titulo).strip("_").lower() + ".pdf"
    if st.button("Gerar relatório PDF", type="primary"):
        with st.spinner("Gerando o PDF..."):
            st.session_state["_pdf"] = (titulo, nome_arquivo,
                                        relatorios.relatorio_pdf(base, titulo, agrupar, limite_frequencia))
    pronto = st.session_state.get("_pdf")
    if pronto and pronto[0] == titulo:
        st.download_button("Baixar relatório (PDF)", pronto[2], pronto[1], "application/pdf")
    elif pronto:
        st.caption("Escopo alterado: gere o relatório de novo.")


def tela_divergencias(div, usuario):
    """`div`: todas as divergências (pendentes e resolvidas), uma linha por aluno ausente."""
    st.button("← Voltar à Visão geral", on_click=voltar_para_visao_geral)
    st.header("Divergências")
    resultado = st.session_state.pop("_resultado_divergencia", None)
    if resultado:
        st.success(resultado)
    if div.empty:
        st.success("Nenhuma divergência: todos os alunos avaliados antes estão na última planilha.")
        return
    pendentes = div[~div["resolvida"]].reset_index(drop=True)
    resolvidas = div[div["resolvida"]].reset_index(drop=True)
    n_tab = st.session_state.get("_n_resolvidas_tab", 0)   # muda a chave das tabelas: zera a seleção depois de agir

    if pendentes.empty:
        st.success("Nenhuma divergência pendente: todas as ausências já foram conferidas.")
    else:
        st.write(f"**{len(pendentes):,}** aluno(s) já avaliados antes **não estão na última planilha** enviada.".replace(",", "."))
        st.caption("Eles saíram da Visão geral e da Lista priorizada, mas **nada foi apagado**: o histórico continua no banco. "
                   "Confira com a secretaria. **Erro de arquivo?** Envie a planilha corrigida e completa — os alunos voltam sozinhos. "
                   "**Saíram da escola, ou já conferiu?** Marque como resolvida abaixo: some do card e do menu, mas fica registrado.")
        st.caption("Por privacidade, esta lista mostra só a matrícula.")
        tabela = _tabela_divergencias(pendentes)
        evento = st.dataframe(tabela, hide_index=True, width="stretch", height=380, key=f"tabela_diverg_{n_tab}",
                              on_select="rerun", selection_mode="multi-row")
        marcadas = _linhas_selecionadas(evento)
        st.caption("Marque uma ou mais linhas (a caixa do cabeçalho marca todas) para registrar a conferência.")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            motivo = c1.selectbox("Motivo", database.MOTIVOS_RESOLUCAO, key="motivo_resolucao")
            responsavel = permissoes.identificacao(usuario)   # vem do login
            c2.text_input("Responsável pelo registro", value=responsavel, disabled=True, help="Preenchido automaticamente com o seu login.")
            if st.button(f"Marcar como resolvida ({len(marcadas)})", type="primary", disabled=not marcadas):
                qtd = database.resolver_divergencias(pendentes.loc[marcadas, "id_aluno"].tolist(), motivo, responsavel)
                st.session_state["_resultado_divergencia"] = f"{qtd} divergência(s) marcada(s) como resolvida(s): {motivo.lower()}."
                st.session_state["_n_resolvidas_tab"] = n_tab + 1
                st.rerun()
        st.download_button("Baixar pendentes (CSV)", tabela.to_csv(index=False).encode("utf-8"),
                           "divergencias.csv", "text/csv")

    if resolvidas.empty:
        return
    mostrar = True if pendentes.empty else st.toggle(f"Mostrar divergências resolvidas ({len(resolvidas)})", key="ver_resolvidas")
    if mostrar:
        st.subheader("Resolvidas")
        st.caption("Continuam fora das listas. Se o aluno voltar numa planilha futura e sumir de novo, a nova ausência aparece como pendente.")
        tabela_res = _tabela_divergencias(resolvidas, resolvidas=True)
        evento = st.dataframe(tabela_res, hide_index=True, width="stretch", height=300, key=f"tabela_diverg_res_{n_tab}",
                              on_select="rerun", selection_mode="multi-row")
        marcadas = _linhas_selecionadas(evento)
        if st.button(f"Reabrir ({len(marcadas)})", disabled=not marcadas,
                     help="Volta a marcar como pendente (por exemplo, se o registro foi feito por engano)."):
            qtd = database.reabrir_divergencias(resolvidas.loc[marcadas, "id_aluno"].tolist())
            st.session_state["_resultado_divergencia"] = f"{qtd} divergência(s) reaberta(s): voltaram a ficar pendentes."
            st.session_state["_n_resolvidas_tab"] = n_tab + 1
            st.rerun()
        st.download_button("Baixar resolvidas (CSV)", tabela_res.to_csv(index=False).encode("utf-8"),
                           "divergencias_resolvidas.csv", "text/csv")


def _fmt_data_curta(texto):
    """'2026-10-20' -> '20/10/2026' (devolve '—' se vazio)."""
    if texto is None or (not isinstance(texto, str) and pd.isna(texto)) or str(texto).strip() == "":
        return "—"
    try:
        return pd.to_datetime(texto).strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return str(texto)


def _texto_seguro(texto):
    """Mostra um texto digitado pelo usuário sem que o Markdown o reformate (negrito, links, listas...)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~$<])", r"\\\1", texto).replace("\n", "  \n")


def probabilidades_historico(hist, modelo, config):
    """Probabilidade de Risco Alto de cada avaliação do histórico (DataFrame com os atributos gravados)."""
    colunas_banco = [pipeline.ATRIBUTO_PARA_BANCO[a] for a in config["atributos"]]
    x = hist[colunas_banco].fillna(0).copy()
    x.columns = config["atributos"]
    return pipeline.probabilidades(x, modelo)["Risco Alto"].values


def _rotular_historico(historico):
    """
    Histórico como DataFrame, com o rótulo do eixo de cada avaliação: o período de referência, quando todas
    as avaliações têm um e são diferentes entre si; senão "Avaliação n".
    """
    hist = pd.DataFrame(historico)
    periodos = hist["periodo"].fillna("").astype(str).str.strip()
    usar_periodo = bool((periodos != "").all() and periodos.is_unique)
    hist["avaliacao"] = periodos if usar_periodo else [f"Avaliação {i}" for i in range(1, len(hist) + 1)]
    hist["periodo"] = periodos.replace("", "—")
    hist["data"] = pd.to_datetime(hist["data_avaliacao"]).dt.strftime("%d/%m/%Y")
    return hist


def grafico_frequencia(historico, limite):
    """Frequência em cada avaliação, com uma linha tracejada no limite da escola (pontos abaixo dele ficam em vermelho)."""
    hist = _rotular_historico(historico)
    ordem = hist["avaliacao"].tolist()
    hist["situacao"] = hist["frequencia_pct"].apply(
        lambda v: "Abaixo do limite" if pd.notna(v) and v < limite else "No limite ou acima")
    com_dado = hist.dropna(subset=["frequencia_pct"])
    eixo_x = alt.X("avaliacao:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0))
    eixo_y = alt.Y("frequencia_pct:Q", scale=alt.Scale(domain=[0, 100]), title="Frequência (%)")
    base = alt.Chart(com_dado).encode(x=eixo_x, y=eixo_y)
    linha = base.mark_line(color="#7A8591", strokeWidth=2)
    pontos = base.mark_point(filled=True, size=140, opacity=1).encode(
        color=alt.Color("situacao:N", title=None, scale=alt.Scale(
            domain=["Abaixo do limite", "No limite ou acima"], range=[CORES["Risco Alto"], "#2F6F82"])),
        tooltip=["avaliacao", alt.Tooltip("periodo:N", title="período"), "data",
                 alt.Tooltip("frequencia_pct:Q", title="Frequência (%)", format=".1f")])
    regua = pd.DataFrame({"limite": [limite], "rotulo": [f"Limite {_fmt_limite(limite)}%"]})
    tracejado = alt.Chart(regua).mark_rule(strokeDash=[6, 4], color="#B3402F", strokeWidth=1.5).encode(y="limite:Q")
    texto = alt.Chart(regua).mark_text(align="left", baseline="bottom", dx=4, dy=-3, color="#B3402F").encode(
        y="limite:Q", text="rotulo:N", x=alt.value(2))
    return alt.layer(linha, pontos, tracejado, texto).properties(height=200)


def grafico_evolucao(historico, acoes, modelo, config):
    """
    Linha da probabilidade de Risco Alto em cada avaliação (pontos coloridos pelo nível). Cada ação
    pedagógica é ligada à avaliação mais recente que veio ANTES dela (ou no mesmo dia) e aparece como
    um losango em volta do ponto.
    """
    hist = _rotular_historico(historico)
    hist["prob"] = probabilidades_historico(hist, modelo, config)
    ordem = hist["avaliacao"].tolist()

    eixo_x = alt.X("avaliacao:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0))
    eixo_y = alt.Y("prob:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%"), title="Prob. de Risco Alto")
    base = alt.Chart(hist).encode(x=eixo_x, y=eixo_y)
    linha = base.mark_line(color="#7A8591", strokeWidth=2)
    pontos = base.mark_point(filled=True, size=170, opacity=1).encode(
        color=alt.Color("risco:N", scale=alt.Scale(domain=ORDEM, range=[CORES[r] for r in ORDEM]), title="Nível"),
        tooltip=["avaliacao", alt.Tooltip("periodo:N", title="período"), "data", "risco",
                 alt.Tooltip("prob:Q", title="Prob. Risco Alto", format=".0%")],
    )
    camadas = [linha, pontos]

    if acoes:
        datas_aval = pd.to_datetime(hist["data_avaliacao"]).dt.normalize()
        por_aval = {}
        for a in acoes:
            d = pd.to_datetime(a["data_acao"])
            anteriores = [i for i, da in enumerate(datas_aval) if da <= d]
            por_aval.setdefault(anteriores[-1] if anteriores else 0, []).append(a)
        marcas = pd.DataFrame([
            {"avaliacao": ordem[i], "prob": hist.at[i, "prob"],
             "acoes": "; ".join(f"{_fmt_data_curta(a['data_acao'])} {a['tipo']}" for a in lista)}
            for i, lista in por_aval.items()
        ])
        camadas.append(
            alt.Chart(marcas).mark_point(shape="diamond", size=520, filled=False, strokeWidth=2.5, color="#16283D")
            .encode(x=eixo_x, y=eixo_y, tooltip=[alt.Tooltip("acoes:N", title="Ações depois desta avaliação")])
        )
    return alt.layer(*camadas).properties(height=280)


def secao_evolucao(historico, acoes, modelo, config, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO):
    st.subheader("Evolução do risco")
    if len(historico) < 2:
        st.caption("Este aluno tem só uma avaliação; a linha aparece a partir da segunda.")
    else:
        st.caption("Cada ponto é uma avaliação: a cor é o nível de risco e a altura, a probabilidade estimada de Risco Alto. "
                   "Um losango ◇ em volta do ponto indica ações pedagógicas registradas depois daquela avaliação.")
    st.altair_chart(grafico_evolucao(historico, acoes, modelo, config), width="stretch")
    if any(h.get("frequencia_pct") is not None for h in historico):
        st.caption("**Frequência em cada avaliação.** A linha tracejada é o limite definido pela escola em Configurações; "
                   "pontos vermelhos estão abaixo dele. A frequência não entra no cálculo do risco.")
        st.altair_chart(grafico_frequencia(historico, limite_frequencia), width="stretch")


def secao_acoes(id_aluno, acoes, usuario):
    st.subheader("Ações pedagógicas")
    st.caption("Registre o que foi feito com este aluno. O texto fica visível a quem acessa a ficha: "
               "evite dados de saúde ou da família além do estritamente necessário.")
    mensagem = st.session_state.pop("_msg_acao", None)
    if mensagem:
        st.success(mensagem)

    n = st.session_state.get("_n_acao", 0)
    with st.form(f"form_acao_{id_aluno}"):
        responsavel = permissoes.identificacao(usuario)   # vem do login: ninguém registra em nome de outra pessoa
        c1, c2, c3 = st.columns([1, 1.6, 1.4])
        data_acao = c1.date_input("Data da ação", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
        tipo = c2.selectbox("Tipo", TIPOS_ACAO)
        c3.text_input("Responsável pelo registro", value=responsavel, disabled=True, help="Preenchido automaticamente com o seu login.")
        descricao = st.text_area("Descrição", max_chars=500, height=90, key=f"descricao_acao_{id_aluno}_{n}",
                                 placeholder="Ex.: Liguei para a mãe; combinamos reforço de matemática às terças.")
        enviar = st.form_submit_button("Registrar ação")
    if enviar:
        if not descricao.strip():
            st.error("Descreva a ação realizada.")
        else:
            database.registrar_acao(id_aluno, data_acao, tipo, descricao, responsavel)
            st.session_state["_msg_acao"] = "Ação registrada."
            st.session_state["_n_acao"] = n + 1   # zera o campo de descrição
            st.rerun()

    if not acoes:
        st.caption("Nenhuma ação registrada para este aluno ainda.")
    for a in acoes:
        with st.container(border=True):
            esq, dir_ = st.columns([6, 1])
            esq.markdown(f"**{_fmt_data_curta(a['data_acao'])} · {_texto_seguro(a['tipo'])}** — {_texto_seguro(a['responsavel'])}")
            esq.markdown(_texto_seguro(a["descricao"]))
            pode_excluir = permissoes.pode(usuario, "apagar_dados") or permissoes.pode(usuario, "enviar_planilha") \
                or a["responsavel"] == permissoes.identificacao(usuario)   # professor só exclui o que ele mesmo registrou
            if pode_excluir:
                with dir_.popover("Excluir"):
                    st.write("Excluir esta ação? Não dá para desfazer.")
                    confirma = st.checkbox("Confirmo a exclusão", key=f"conf_exc_{a['id_acao']}")
                    if st.button("Excluir ação", key=f"exc_{a['id_acao']}", disabled=not confirma):
                        database.excluir_acao(a["id_acao"])
                        st.session_state["_msg_acao"] = "Ação excluída."
                        st.rerun()


def _fmt_num(v, casas=1):
    return f"{v:.{casas}f}".replace(".", ",")


def comparar_com_turma(visao, aluno):
    """Mostra, para cada indicador, o valor do aluno e se está acima ou abaixo da média da turma."""
    turma = aluno["turma"]
    st.subheader("Comparação com a turma")
    if turma is None or pd.isna(turma):
        st.caption("A turma deste aluno não foi informada, então não há comparação.")
        return
    colegas = visao[visao["turma"] == turma]
    if len(colegas) < 2:
        st.caption(f"Não há outros alunos na turma {turma} para comparar.")
        return

    # (rótulo, coluna, é taxa?, coluna que indica "tem nota no semestre")
    indicadores = [
        ("Nota de admissão", "nota_admissao", False, "nota_admissao"),
        ("Nota média 1º semestre", "nota_1sem", False, "nota_1sem"),
        ("Nota média 2º semestre", "nota_2sem", False, "nota_2sem"),
        ("Aprovação 1º sem.", "taxa_aprovacao_1sem", True, "nota_1sem"),
        ("Aprovação 2º sem.", "taxa_aprovacao_2sem", True, "nota_2sem"),
    ]
    if colegas["frequencia_pct"].notna().any() or pd.notna(aluno["frequencia_pct"]):
        indicadores.append(("Frequência", "frequencia_pct", "pct", "frequencia_pct"))
    cols = st.columns(len(indicadores))
    for col, (rotulo, campo, taxa, ref) in zip(cols, indicadores):
        elegiveis = colegas[colegas[ref] > 0]
        with col:
            if pd.isna(aluno[ref]) or aluno[ref] <= 0 or elegiveis.empty:
                st.metric(rotulo, "—")
                st.caption("sem frequência informada" if taxa == "pct" else "sem notas no semestre")
                continue
            media = elegiveis[campo].mean()
            if taxa == "pct":   # já está em porcentagem (0 a 100)
                valor, dif = f"{aluno[campo]:.0f}%", aluno[campo] - media
                delta, dica = f"{dif:+.0f} p.p. vs. turma", f"Média da turma: {media:.0f}%"
            elif taxa:
                valor, dif = f"{aluno[campo] * 100:.0f}%", (aluno[campo] - media) * 100
                delta, dica = f"{dif:+.0f} p.p. vs. turma", f"Média da turma: {media * 100:.0f}%"
            else:
                valor, dif = _fmt_num(aluno[campo]), aluno[campo] - media
                delta, dica = f"{_fmt_num(dif)} vs. turma ({_fmt_num(media)})", None
                if dif >= 0:
                    delta = "+" + delta
            st.metric(rotulo, valor, delta=delta, help=dica)
    st.caption(f"Média da turma {turma} ({len(colegas)} alunos). Quem não tem notas (ou frequência) informada fica fora da média daquele indicador. "
               "Seta verde = acima da turma; vermelha = abaixo.")


def tela_ficha(visao, limite_frequencia=pipeline.LIMITE_FREQUENCIA_PADRAO, usuario=None):
    st.button("← Voltar à lista priorizada", on_click=voltar_para_lista)
    st.header("Ficha do aluno")
    st.caption("Uso restrito: aqui o nome é exibido. Consulte apenas quando houver necessidade pedagógica.")
    mensagem_exclusao = st.session_state.pop("_msg_exclusao", None)
    if mensagem_exclusao:
        st.success(mensagem_exclusao)
    if visao.empty:
        st.info("Nenhum aluno no banco ainda.")
        return

    opcoes = visao["matricula"].tolist()
    if st.session_state.get("f_matricula") not in opcoes:
        st.session_state["f_matricula"] = None
    matricula = st.selectbox("Matrícula", opcoes, index=None, key="f_matricula",
                             placeholder="Digite ou escolha uma matrícula")
    if not matricula:
        st.session_state.pop("_ficha_auditada", None)
        return
    id_aluno = int(visao.loc[visao["matricula"] == matricula, "id_aluno"].iloc[0])
    ficha = database.buscar_ficha_aluno(id_aluno)
    aluno, historico = ficha["aluno"], ficha["historico"]
    if st.session_state.get("_ficha_auditada") != id_aluno:   # um registro por abertura (mexer na mesma ficha não repete)
        _auditar("ficha_aluno", aluno={"id_aluno": id_aluno, "matricula": aluno["matricula"], "nome": aluno["nome"]})
        st.session_state["_ficha_auditada"] = id_aluno
    atual = historico[-1]
    linha_visao = visao.loc[visao["matricula"] == matricula].iloc[0]

    st.subheader(aluno["nome"])
    st.write(f"**Matrícula:** {aluno['matricula']} · **Turma:** {aluno['turma'] or '—'} · **Curso:** {aluno['curso'] or '—'}")
    st.markdown(
        f"<div style='display:inline-block;padding:6px 16px;border-radius:8px;color:white;font-weight:600;"
        f"background:{CORES[atual['risco']]}'>{atual['risco']}</div>",
        unsafe_allow_html=True,
    )
    freq_atual = atual.get("frequencia_pct")
    if freq_atual is None or pd.isna(freq_atual):
        st.caption("Frequência não informada na última avaliação.")
    elif freq_atual < limite_frequencia:
        st.error(f"**Frequência baixa:** {_fmt_num(freq_atual)}% na última avaliação, abaixo do limite de {_fmt_limite(limite_frequencia)}% "
                 "definido pela escola. Este alerta é uma regra, separada do nível de risco calculado pelo modelo.")
    else:
        st.caption(f"Frequência: {_fmt_num(freq_atual)}% na última avaliação (limite da escola: {_fmt_limite(limite_frequencia)}%).")
    if linha_visao["situacao_alerta"] in (frequencia.SITUACAO_REINCIDENTE, frequencia.SITUACAO_SAIU):
        if linha_visao["situacao_alerta"] == frequencia.SITUACAO_REINCIDENTE:
            st.caption(f"Histórico de alertas: **{int(linha_visao['alertas_seguidos'])} avaliações seguidas** com frequência abaixo do limite.")
        else:
            st.caption("Histórico de alertas: este aluno **saiu do alerta** de frequência (estava abaixo do limite antes e agora está no limite ou acima).")
    if linha_visao["piorou"]:
        st.warning(f"**Atenção:** o risco deste aluno subiu desde a avaliação anterior, de {linha_visao['risco_anterior']} para {linha_visao['risco']}.")
    elif linha_visao["mudanca"].startswith("▼"):
        st.success(f"O risco deste aluno diminuiu desde a avaliação anterior, de {linha_visao['risco_anterior']} para {linha_visao['risco']}.")

    modelo, config = carregar_modelo()
    valores = {
        "Admission grade": atual["nota_admissao"],
        "Curricular units 1st sem (grade)": atual["nota_1sem"],
        "Curricular units 2nd sem (grade)": atual["nota_2sem"],
        "taxa_aprovacao_1sem": atual["taxa_aprovacao_1sem"],
        "taxa_aprovacao_2sem": atual["taxa_aprovacao_2sem"],
        "indicador_socioeconomico": atual["indicador_socioeconomico"],
    }
    linha = pd.DataFrame([valores])[config["atributos"]]

    esq, dir_ = st.columns(2)
    with esq:
        st.subheader("Probabilidade por nível")
        prob = pipeline.probabilidades(linha, modelo).iloc[0]
        dfp = pd.DataFrame({"risco": ORDEM, "probabilidade": [float(prob[r]) for r in ORDEM]})
        graf = (
            alt.Chart(dfp).mark_bar()
            .encode(
                y=alt.Y("risco:N", sort=ORDEM, title=None),
                x=alt.X("probabilidade:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
                color=alt.Color("risco:N", scale=alt.Scale(domain=ORDEM, range=[CORES[r] for r in ORDEM]), legend=None),
                tooltip=["risco", alt.Tooltip("probabilidade:Q", format=".1%")],
            ).properties(height=180)
        )
        st.altair_chart(graf, width="stretch")
    with dir_:
        st.subheader("O que mais pesou para o Risco Alto")
        contrib = pipeline.contribuicoes(linha.iloc[0], modelo, config, "Risco Alto")
        contrib["sentido"] = contrib["contribuicao"].apply(lambda v: "Aumenta o risco" if v > 0 else "Reduz o risco")
        graf = (
            alt.Chart(contrib).mark_bar()
            .encode(
                y=alt.Y("atributo:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("contribuicao:Q", title="Contribuição (coef. × valor padronizado)"),
                color=alt.Color("sentido:N", scale=alt.Scale(domain=["Aumenta o risco", "Reduz o risco"],
                                                             range=[CORES["Risco Alto"], CORES["Risco Baixo"]]), title=None),
                tooltip=["atributo", alt.Tooltip("valor:Q", format=".2f"), alt.Tooltip("contribuicao:Q", format=".2f")],
            ).properties(height=240)
        )
        st.altair_chart(graf, width="stretch")
        st.caption("Barras vermelhas empurram o aluno para Risco Alto; verdes afastam. É um apoio à conversa pedagógica, não um veredito.")

    comparar_com_turma(visao, linha_visao)

    acoes = database.buscar_acoes(id_aluno)
    secao_evolucao(historico, acoes, modelo, config, limite_frequencia)
    secao_acoes(id_aluno, acoes, usuario)

    st.subheader("Histórico de avaliações")
    hist = pd.DataFrame(historico)
    hist["prob"] = probabilidades_historico(hist, modelo, config) * 100
    hist["data_avaliacao"] = hist["data_avaliacao"].map(_fmt_data_curta)
    hist["taxa_aprovacao_1sem"] *= 100
    hist["taxa_aprovacao_2sem"] *= 100
    colunas_hist = ["data_avaliacao", "periodo", "risco", "prob", "frequencia_pct", "nota_1sem", "nota_2sem",
                    "taxa_aprovacao_1sem", "taxa_aprovacao_2sem", "indicador_socioeconomico"]
    if not hist["frequencia_pct"].notna().any():
        colunas_hist.remove("frequencia_pct")
    if not hist["periodo"].notna().any():   # sem nenhum período informado, a coluna só ocuparia espaço
        colunas_hist.remove("periodo")
    hist = hist[colunas_hist].rename(columns={
        "data_avaliacao": "Avaliado em", "periodo": "Período", "risco": "Risco", "prob": "Prob. Risco Alto", "frequencia_pct": "Frequência",
        "nota_1sem": "Nota 1º sem", "nota_2sem": "Nota 2º sem", "taxa_aprovacao_1sem": "Aprov. 1º sem",
        "taxa_aprovacao_2sem": "Aprov. 2º sem", "indicador_socioeconomico": "Indic. socioeconômico"})
    st.dataframe(hist.iloc[::-1], hide_index=True, width="stretch", column_config={
        "Prob. Risco Alto": st.column_config.NumberColumn(format="%.0f%%"),
        "Frequência": st.column_config.NumberColumn(format="%.0f%%"),
        "Aprov. 1º sem": st.column_config.NumberColumn(format="%.0f%%"),
        "Aprov. 2º sem": st.column_config.NumberColumn(format="%.0f%%"),
        "Nota 1º sem": st.column_config.NumberColumn(format="%.1f"),
        "Nota 2º sem": st.column_config.NumberColumn(format="%.1f"),
        "Indic. socioeconômico": st.column_config.NumberColumn(format="%.0f")})
    if permissoes.pode(usuario, "gerenciar_retencao"):
        secao_excluir_aluno(id_aluno)


def _excluir_aluno_agora(id_aluno, chave_motivo):
    """Callback do botão de exclusão (roda antes de redesenhar a página, então pode limpar a seleção da ficha)."""
    try:
        retencao.excluir_aluno(id_aluno, st.session_state.get(chave_motivo), st.session_state.get("usuario"))
    except ValueError as e:
        st.session_state["_msg_exclusao_erro"] = str(e)
        return
    st.session_state["f_matricula"] = None
    st.session_state.pop("_ficha_auditada", None)
    st.session_state["_msg_exclusao"] = "Aluno excluído definitivamente. Nome e matrícula também saíram da trilha de auditoria."


def secao_excluir_aluno(id_aluno):
    """Só administrador: exclusão individual (pedido do titular ou do responsável, LGPD)."""
    erro = st.session_state.pop("_msg_exclusao_erro", None)
    if erro:
        st.error(erro)
    with st.expander("Excluir este aluno (pedido de exclusão de dados)"):
        st.warning("**A exclusão é definitiva.** Apaga todas as avaliações, ações pedagógicas e conferências deste aluno, e tira o nome e a "
                   "matrícula dele da trilha de auditoria. Se ele continuar na planilha da escola, **volta no próximo envio**: "
                   "remova-o também da planilha de origem.")
        chave_motivo = f"excl_motivo_{id_aluno}"
        motivo = st.text_input("Motivo ou referência do pedido (sem dados pessoais)", key=chave_motivo, max_chars=150,
                               placeholder="Ex.: pedido do responsável em 20/10/2026, protocolo 123")
        confirma = st.checkbox("Entendo que isso não pode ser desfeito", key=f"excl_ok_{id_aluno}")
        st.button("Excluir definitivamente", key=f"excl_btn_{id_aluno}", disabled=not (confirma and motivo.strip()),
                  on_click=_excluir_aluno_agora, args=(id_aluno, chave_motivo))


def _rotulo_envio(e):
    periodo = f", período {e['periodo_referencia']}" if e.get("periodo_referencia") else ""
    return f"#{e['id_processamento']} — {e['nome_arquivo_origem']} — {_fmt_data(e['data_hora'])} ({e['quantidade_alunos']} alunos{periodo})"


def _texto_desfeito(r):
    partes = [f"{r['avaliacoes']} avaliação(ões) removida(s)"]
    if r["alunos_novos"]:
        partes.append(f"{r['alunos_novos']} aluno(s) que só existiam nesses envios removido(s)")
    if r["acoes_removidas"]:
        partes.append(f"{r['acoes_removidas']} ação(ões) pedagógica(s) removida(s) junto")
    if r["alunos_restaurados"]:
        partes.append(f"nome, turma ou curso restaurados em {r['alunos_restaurados']} aluno(s)")
    if r["resolucoes_removidas"]:
        partes.append(f"{r['resolucoes_removidas']} conferência(s) de divergência apagada(s)")
    envios = "1 envio" if r["envios"] == 1 else f"{r['envios']} envios (do escolhido até o mais recente)"
    return (f"Desfeito: {envios}, a partir de **{r['nome_arquivo_origem']}** ({_fmt_data(r['data_hora'])}). "
            + "; ".join(partes) + ". A avaliação anterior de cada aluno voltou a valer.")


def secao_desfazer():
    """Escolhe um envio do histórico e desfaz ele e todos os posteriores."""
    envios = database.buscar_envios_desfaziveis()
    if not envios:
        return
    base = envios[0]["id_processamento"]   # a chave muda a cada envio novo, então a escolha nunca fica velha
    with st.expander("Desfazer envios"):
        st.write("Use quando uma planilha errada foi processada. Escolha o envio: ele **e todos os enviados depois dele** serão desfeitos, "
                 "e a avaliação anterior de cada aluno volta a valer.")
        escolhido = st.selectbox("Desfazer a partir de", [e["id_processamento"] for e in envios], key=f"desfazer_envio_{base}",
                                 format_func=lambda i: _rotulo_envio(next(e for e in envios if e["id_processamento"] == i)))
        r = database.resumo_desfazer(escolhido)
        if r is None:
            st.error("Não é possível desfazer este envio.")
            return
        linhas = [f"**{r['envios']}** envio(s) e **{r['avaliacoes']}** avaliação(ões) removidos"]
        if r["alunos_novos"]:
            linhas.append(f"**{r['alunos_novos']}** aluno(s) que só existem nesses envios serão removidos"
                          + (f", com **{r['acoes_removidas']}** ação(ões) pedagógica(s) registrada(s) para eles" if r["acoes_removidas"] else ""))
        if r["alunos_restaurados"]:
            linhas.append(f"nome, turma ou curso voltam ao valor anterior em **{r['alunos_restaurados']}** aluno(s)")
        if r["resolucoes_removidas"]:
            linhas.append(f"**{r['resolucoes_removidas']}** conferência(s) de divergência (marcadas como resolvidas) ligadas a esses envios serão apagadas")
        st.markdown("O que acontece:\n\n" + "\n".join(f"- {l}" for l in linhas))
        st.caption("**Não dá para refazer**; para ter os dados de volta, envie a planilha de novo. Envios feitos em versões antigas do app "
                   "não guardaram o nome, a turma e o curso anteriores, então esses três campos não voltam ao valor antigo nesses casos.")
        ok_desfazer = st.checkbox("Entendo que isso apaga dados do banco", key=f"confirma_desfazer_{base}_{escolhido}")
        if st.button("Desfazer", disabled=not ok_desfazer, key="btn_desfazer"):
            resultado = database.desfazer_ate_processamento(escolhido)
            _auditar("desfazer_envio", detalhe=f"a partir do envio #{escolhido}: {r['envios']} envio(s), {r['avaliacoes']} avaliação(ões)")
            st.session_state["_resultado_desfazer"] = resultado
            st.rerun()


def tela_upload(pode_apagar=False):
    st.header("Upload de dados")
    st.write("Envie a planilha da escola (CSV). Cada aluno recebe uma nova avaliação de risco, e o histórico anterior é preservado.")
    st.caption("Para acompanhar a evolução, envie sempre a lista **completa** de alunos: quem faltar na nova planilha vai para **Divergências**.")
    with st.expander("Passo a passo: enviar uma nova avaliação e comparar com a anterior"):
        st.markdown(PASSO_A_PASSO)
    with open(CAMINHO_TEMPLATE, "rb") as f:
        st.download_button("Baixar planilha-modelo (CSV)", f.read(), "modelo_planilha.csv", "text/csv")
    with st.expander("Colunas esperadas"):
        st.dataframe(pd.DataFrame(pipeline.DESCRICAO_COLUNAS, columns=["Coluna", "Preenchimento", "O que é"]),
                     hide_index=True, width="stretch")
        st.caption("Os nomes antigos em inglês (por exemplo `Admission grade`) também são aceitos, e o cabeçalho pode ter "
                   "maiúsculas ou acento. Turma e curso podem ficar em branco, mas várias telas dependem deles.")

    resultado = st.session_state.pop("_resultado_upload", None)
    if resultado:
        st.success(f"{resultado['qtd']} aluno(s) processados e gravados.")
        if resultado["ausentes"]:
            st.warning(f"**{resultado['ausentes']}** aluno(s) da avaliação anterior não estão nesta planilha e saíram das listas.")
            st.button("Ver divergências", on_click=ir_para_divergencias)

    escala_nota = database.obter_escala_nota_admissao()
    st.caption(f"A **nota de admissão** é lida na escala de 0 a {_fmt_limite(escala_nota)} (definida em **Configurações**) e convertida "
               "para a escala do modelo (0 a 200). Se a sua planilha usa outra escala, ajuste lá antes de processar.")

    # o número na chave "zera" o campo de envio depois de processar (evita avisar de repetição logo em seguida)
    arquivo = st.file_uploader("Planilha CSV", type=["csv"], key=f"upload_{st.session_state.get('upload_n', 0)}")
    if arquivo is not None:
        df = None
        try:
            df = pd.read_csv(io.BytesIO(arquivo.getvalue()))
        except Exception as e:  # noqa: BLE001
            st.error(f"Não consegui ler o arquivo: {e}")
        liberado = df is not None
        escala_uso = escala_nota   # escala usada neste envio (a configurada, ou a sugerida quando o usuário confirma)
        if liberado:
            df_normalizado, _ = pipeline.normalizar_colunas(df)
            sugerida = pipeline.sugerir_escala(df_normalizado, escala_nota)
            if sugerida:
                maximo = pd.to_numeric(df_normalizado["Admission grade"], errors="coerce").max()
                st.warning(f"A **nota de admissão** tem valores de até {_fmt_limite(float(maximo))}, acima do máximo da escala configurada "
                           f"(0 a {_fmt_limite(escala_nota)}). A planilha parece estar na escala de **0 a {_fmt_limite(sugerida)}**.")
                if st.checkbox(f"Processar convertendo da escala de 0 a {_fmt_limite(sugerida)} (só neste envio; a configuração não muda)",
                               key=f"confirma_escala_{st.session_state.get('upload_n', 0)}_{arquivo.name}_{sugerida:g}"):
                    escala_uso = sugerida
                else:
                    liberado = False
            repetida = servico.verificar_repetida(df, escala_nota_admissao=escala_uso)
            if repetida:
                st.warning(f"Esta planilha tem **exatamente o mesmo conteúdo** da enviada em {_fmt_data(repetida['data_hora'])} "
                           f"({repetida['nome_arquivo_origem']}). Processar de novo cria uma avaliação idêntica à anterior "
                           "e os alertas de \"pioraram\" e \"melhoraram\" deixam de aparecer.")
                confirma_repetida = st.checkbox("Quero processar mesmo assim", key=f"confirma_repetida_{repetida['id_processamento']}")
                liberado = liberado and confirma_repetida
            for aviso in pipeline.avisos_planilha(df_normalizado, escala_uso):
                st.warning(aviso)
            if pipeline.COLUNA_PROFESSORES in df_normalizado.columns:
                logins = {x.strip().lower() for v in df_normalizado[pipeline.COLUNA_PROFESSORES].dropna()
                          for x in re.split(r"[;,]", str(v)) if x.strip()}
                desconhecidos = usuarios.logins_desconhecidos(logins)
                if desconhecidos:
                    st.warning("Estes logins da coluna **professores** ainda não têm usuário: " + ", ".join(f"`{d}`" for d in desconhecidos[:10])
                               + (" e outros" if len(desconhecidos) > 10 else "")
                               + ". A atribuição de turmas fica guardada e passa a valer quando o administrador criar o usuário.")
            else:
                st.caption("Sem a coluna **professores**: as atribuições de turmas que já estão no sistema continuam valendo.")
        periodo = st.text_input("Período de referência (opcional)", max_chars=20, placeholder="Ex.: 2026/1",
                                key=f"periodo_ref_{st.session_state.get('upload_n', 0)}",
                                help="A que período os dados desta planilha se referem. Aparece no histórico e no gráfico de evolução do aluno.")
        if st.button("Processar planilha", type="primary", disabled=not liberado):
            with st.spinner("Classificando alunos..."):
                qtd, erros = servico.processar_e_gravar(df, arquivo.name, *carregar_modelo(), periodo_referencia=periodo,
                                                        escala_nota_admissao=escala_uso)
            if erros:
                st.error("Planilha rejeitada — nada foi gravado:")
                for e in erros:
                    st.write(f"- {e}")
            else:
                _auditar("envio_planilha", detalhe=f"{arquivo.name}: {qtd} aluno(s)")
                st.session_state["_resultado_upload"] = {"qtd": qtd, "ausentes": len(database.buscar_divergencias())}
                st.session_state["upload_n"] = st.session_state.get("upload_n", 0) + 1
                st.rerun()

    st.divider()
    st.subheader("Dados de demonstração")
    st.caption("Alunos 100% fictícios (nomes e matrículas inventados) sobre o dataset público UCI. "
               "Atenção: a maior parte dessas linhas foi usada para treinar o modelo, então os resultados parecem melhores do que seriam com alunos novos.")
    n = database.contar_alunos()
    if n == 0:
        if st.button("Carregar dados de demonstração"):
            with st.spinner("Carregando 4.424 alunos fictícios..."):
                carregar_demo()
            st.rerun()
    else:
        st.write(f"O banco tem **{n:,}** aluno(s).".replace(",", "."))
        if pode_apagar:
            with st.expander("Reiniciar o banco (apaga tudo)"):
                confirma = st.checkbox("Entendo que isso apaga todos os alunos, avaliações e o histórico")
                c_a, c_b = st.columns(2)
                if c_a.button("Apagar e recarregar demonstração", disabled=not confirma):
                    database.limpar_dados()
                    _auditar("apagar_dados", detalhe=f"{n} aluno(s) apagados; demonstração recarregada")
                    carregar_demo()
                    st.rerun()
                if c_b.button("Apagar tudo e começar do zero", disabled=not confirma):
                    database.limpar_dados()
                    _auditar("apagar_dados", detalhe=f"{n} aluno(s) apagados; banco reiniciado do zero")
                    st.rerun()

    if n > 0:
        usados = {p["nome_arquivo_origem"] for p in database.buscar_processamentos(200)}
        if NOME_DEMO in usados and NOME_DEMO2 not in usados:
            st.subheader("Nova avaliação (demonstração)")
            st.caption("Simula, com dados fictícios, a planilha do semestre seguinte: parte dos alunos piora e parte melhora. "
                       "Serve para mostrar os alertas de \"pioraram\" e \"melhoraram\" e o histórico de avaliações. "
                       "Com dados reais, use o envio de planilha acima.")
            if st.button("Carregar nova avaliação"):
                with st.spinner("Classificando a nova avaliação..."):
                    carregar_demo_rodada2()
                st.rerun()

    st.subheader("Últimos processamentos")
    desfeito = st.session_state.pop("_resultado_desfazer", None)
    if desfeito:
        st.success(_texto_desfeito(desfeito))
    proc = database.buscar_processamentos()
    if proc:
        log = pd.DataFrame(proc).drop(columns=["hash_conteudo"], errors="ignore")
        log["data_hora"] = log["data_hora"].map(_fmt_data)
        log["periodo_referencia"] = log["periodo_referencia"].fillna("—")
        st.dataframe(log[["id_processamento", "data_hora", "nome_arquivo_origem", "periodo_referencia", "quantidade_alunos"]].rename(columns={
            "id_processamento": "#", "data_hora": "Data/hora", "nome_arquivo_origem": "Arquivo",
            "periodo_referencia": "Período", "quantidade_alunos": "Alunos"}),
            hide_index=True, width="stretch")
        secao_desfazer()
    else:
        st.caption("Nenhum processamento registrado.")


ESCALAS_NOTA = {"0 a 100 (padrão, porcentagem)": 100.0, "0 a 10": 10.0, "0 a 200 (a do modelo, sem conversão)": 200.0, "Outra escala": None}


def secao_escala_nota():
    st.subheader("Escala da nota de admissão")
    st.write("Informe em que escala a escola registra a **nota do processo seletivo**. O app a converte, de forma proporcional, "
             "para a escala do modelo (0 a 200) antes de calcular o risco: por exemplo, 60 numa escala de 0 a 100 vira 120.")
    st.caption("O modelo foi treinado com notas entre 95 e 190. Notas convertidas muito abaixo disso podem fazer o modelo superestimar o risco "
               "(o upload avisa quando isso acontece). A mudança vale só para os **próximos envios**: as notas já gravadas não são alteradas. "
               "Planilhas com nota fora da escala escolhida são rejeitadas.")
    atual = database.obter_escala_nota_admissao()
    nome_atual = next((n for n, v in ESCALAS_NOTA.items() if v == atual), "Outra escala")
    st.caption(f"Escala atual: **0 a {_fmt_limite(atual)}**.")
    mensagem = st.session_state.pop("_msg_escala", None)
    if mensagem:
        st.success(mensagem)
    with st.form("form_escala_nota"):
        escolha = st.radio("Escala", list(ESCALAS_NOTA), index=list(ESCALAS_NOTA).index(nome_atual))
        outra = st.number_input("Se for outra escala, nota máxima", min_value=1.0, max_value=1000.0,
                                value=float(atual), step=1.0, format="%.1f")
        salvar = st.form_submit_button("Salvar escala", type="primary")
    if salvar:
        valor = database.salvar_escala_nota_admissao(ESCALAS_NOTA[escolha] or outra)
        _auditar("configuracao_alterada", detalhe=f"escala da nota de admissão: 0 a {_fmt_limite(valor)}")
        st.session_state["_msg_escala"] = f"Escala da nota de admissão salva: 0 a {_fmt_limite(valor)}."
        st.rerun()


def secao_retencao():
    st.subheader("Retenção de dados")
    st.write(f"Alunos **ativos** ficam no sistema enquanto constarem na planilha da escola. Quando um aluno **sai da escola** (divergência "
             f"resolvida como *Saiu da escola*), os dados pessoais são guardados por **{retencao.MESES_RETENCAO_SAIDA} meses** e depois "
             "**anonimizados**: nome, matrícula, turma, ações pedagógicas e nomes antigos são apagados e o nome some da Auditoria; as "
             "avaliações (notas, risco e frequência) ficam **sem identificação**, para os números históricos e o retreino do modelo. "
             f"A trilha de auditoria é guardada por {auditoria.MESES_RETENCAO} meses (tela Auditoria). Um pedido de exclusão de um aluno "
             "específico é feito na **Ficha do aluno** (só administrador).")
    mensagem = st.session_state.pop("_msg_retencao", None)
    if mensagem:
        st.success(mensagem)
    r = retencao.resumo()
    st.caption(f"Já anonimizados: **{r['anonimizados']}** aluno(s).")
    if r["pendentes_antigas"]:
        st.warning(f"**{r['pendentes_antigas']}** aluno(s) estão ausentes da planilha **sem conferência** há mais de "
                   f"{retencao.MESES_RETENCAO_SAIDA} meses. Confira na tela **Divergências**: se saíram da escola, marque como resolvidas "
                   "para que entrem na regra de retenção.")
    elegiveis = retencao.listar_elegiveis()
    if not elegiveis:
        st.info(f"Nenhum aluno passou do prazo de {retencao.MESES_RETENCAO_SAIDA} meses depois da saída confirmada.")
        return
    st.write(f"**{len(elegiveis)}** aluno(s) passaram do prazo e podem ser anonimizados (a lista mostra só matrícula e curso):")
    tabela = pd.DataFrame([{"Matrícula": e["matricula"], "Curso": e["curso"] or "—",
                            "Saída confirmada em": _fmt_data_curta(e["saida_confirmada_em"])} for e in elegiveis])
    st.dataframe(tabela, hide_index=True, width="stretch")
    confirma = st.checkbox(f"Entendo que a anonimização de {len(elegiveis)} aluno(s) não pode ser desfeita", key="ret_confirma")
    if st.button(f"Anonimizar {len(elegiveis)} aluno(s)", disabled=not confirma, key="ret_anonimizar"):
        n = retencao.anonimizar_alunos([e["id_aluno"] for e in elegiveis], usuario=st.session_state.get("usuario"))
        st.session_state["_msg_retencao"] = f"{n} aluno(s) anonimizado(s)."
        st.rerun()


def tela_configuracoes(limite_atual):
    st.header("Configurações")
    st.subheader("Limite de frequência")
    st.write("Alunos com frequência **abaixo** deste valor entram no alerta de frequência baixa (card da Visão geral, filtro da "
             "Lista priorizada e aviso na Ficha do aluno).")
    st.caption("O padrão é 75%, o mínimo de presença exigido pela LDB (art. 24, VI). Ajuste conforme a regra da sua instituição. "
               "A mudança vale na hora para todos os alunos já gravados e fica salva no banco. A frequência é um alerta por regra: "
               "não entra no cálculo do risco do modelo.")
    mensagem = st.session_state.pop("_msg_config", None)
    if mensagem:
        st.success(mensagem)
    with st.form("form_limite_frequencia"):
        novo = st.number_input("Limite de frequência (%)", min_value=1.0, max_value=100.0, value=float(limite_atual),
                               step=1.0, format="%.1f")
        c1, c2 = st.columns([1, 1])
        salvar = c1.form_submit_button("Salvar limite", type="primary")
        padrao = c2.form_submit_button(f"Voltar ao padrão ({_fmt_limite(pipeline.LIMITE_FREQUENCIA_PADRAO)}%)")
    if salvar or padrao:
        valor = database.salvar_limite_frequencia(pipeline.LIMITE_FREQUENCIA_PADRAO if padrao else novo)
        _auditar("configuracao_alterada", detalhe=f"limite de frequência: {_fmt_limite(valor)}%")
        st.session_state["_msg_config"] = f"Limite de frequência salvo: {_fmt_limite(valor)}%."
        st.rerun()
    st.divider()
    secao_escala_nota()
    st.divider()
    secao_retencao()


def _fmt_situacao_usuario(u):
    if not u["ativo"]:
        return "Inativo"
    return "Bloqueado" if u["bloqueado"] else "Ativo"


def tela_usuarios(usuario):
    st.header("Usuários")
    st.write("Quem acessa o app. **Administrador:** tudo. **Coordenação:** todos os alunos, upload, divergências e relatórios. "
             "**Professor:** só os alunos das turmas em que aparece na coluna `professores` da planilha.")
    mensagem = st.session_state.pop("_msg_usuarios", None)
    if mensagem:
        st.success(mensagem)
    gerada = st.session_state.pop("_senha_gerada", None)
    if gerada:
        st.warning(f"Senha provisória de **{gerada[0]}**: anote e entregue com segurança — ela **não será mostrada de novo**. "
                   "A pessoa troca no primeiro acesso.")
        st.code(gerada[1], language=None)

    lista = usuarios.listar_usuarios()
    tabela = pd.DataFrame([{"Login": u["login"], "Nome": u["nome"], "Perfil": usuarios.PERFIS[u["perfil"]],
                            "Situação": _fmt_situacao_usuario(u), "Último acesso": _fmt_data(u["ultimo_acesso"]),
                            "Turmas": ", ".join(u["turmas"]) if u["perfil"] == "professor" else "todas"} for u in lista])
    st.dataframe(tabela, hide_index=True, width="stretch")
    sem_usuario = usuarios.logins_sem_usuario()
    if sem_usuario:
        st.info("Logins que a planilha atribui a turmas e ainda **não têm usuário**: " + ", ".join(f"`{x}`" for x in sem_usuario)
                + ". Crie-os abaixo com o mesmo login e o perfil Professor.")

    st.subheader("Novo usuário")
    with st.form("form_novo_usuario", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1.4, 1])
        login = c1.text_input("Login", help="Letras minúsculas, números, ponto, sublinhado ou hífen. Para professores, é o mesmo texto usado na coluna `professores`.")
        nome = c2.text_input("Nome completo")
        perfil = c3.selectbox("Perfil", list(usuarios.PERFIS), format_func=usuarios.PERFIS.get, index=2)
        senha = st.text_input("Senha provisória (opcional)", type="password",
                              help=f"Se ficar em branco, o app gera uma. Mínimo de {usuarios.TAMANHO_MINIMO_SENHA} caracteres. A troca é exigida no primeiro acesso.")
        criar = st.form_submit_button("Criar usuário", type="primary")
    if criar:
        provisoria = senha or usuarios.gerar_senha_provisoria()
        try:
            usuarios.criar_usuario(login, nome, perfil, provisoria)
        except ValueError as e:
            st.error(str(e))
        else:
            _auditar("usuario_criado", detalhe=f"{usuarios.normalizar_login(login)} ({usuarios.PERFIS[perfil]})")
            st.session_state["_msg_usuarios"] = f"Usuário **{usuarios.normalizar_login(login)}** criado."
            if not senha:
                st.session_state["_senha_gerada"] = (usuarios.normalizar_login(login), provisoria)
            st.rerun()

    st.subheader("Editar usuário")
    escolhido = st.selectbox("Usuário", [u["id_usuario"] for u in lista], key="usuario_editar",
                             format_func=lambda i: next(f"{u['login']} — {u['nome']}" for u in lista if u["id_usuario"] == i))
    alvo = next(u for u in lista if u["id_usuario"] == escolhido)
    eu = alvo["id_usuario"] == usuario["id_usuario"]
    with st.form(f"form_editar_usuario_{escolhido}"):
        c1, c2, c3 = st.columns([1.6, 1, 0.8])
        novo_nome = c1.text_input("Nome completo", value=alvo["nome"])
        novo_perfil = c2.selectbox("Perfil", list(usuarios.PERFIS), format_func=usuarios.PERFIS.get,
                                   index=list(usuarios.PERFIS).index(alvo["perfil"]), disabled=eu)
        ativo = c3.toggle("Ativo", value=alvo["ativo"], disabled=eu)
        salvar = st.form_submit_button("Salvar alterações")
    if eu:
        st.caption("Você não pode mudar o próprio perfil nem se desativar.")
    if salvar:
        try:
            usuarios.atualizar_usuario(escolhido, novo_nome, alvo["perfil"] if eu else novo_perfil, True if eu else ativo)
        except ValueError as e:
            st.error(str(e))
        else:
            _auditar("usuario_editado", detalhe=f"{alvo['login']}: perfil {usuarios.PERFIS[alvo['perfil'] if eu else novo_perfil]}, "
                                                f"{'ativo' if (True if eu else ativo) else 'inativo'}")
            st.session_state["_msg_usuarios"] = "Alterações salvas."
            st.rerun()
    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Redefinir senha", key=f"redef_{escolhido}", help="Gera uma nova senha provisória e desbloqueia o usuário."):
        provisoria = usuarios.gerar_senha_provisoria()
        usuarios.definir_senha(escolhido, provisoria)
        _auditar("senha_redefinida", detalhe=alvo["login"])
        st.session_state["_senha_gerada"] = (alvo["login"], provisoria)
        st.session_state["_msg_usuarios"] = f"Senha de **{alvo['login']}** redefinida."
        st.rerun()
    if alvo["bloqueado"] and b2.button("Desbloquear", key=f"desb_{escolhido}"):
        usuarios.desbloquear(escolhido)
        _auditar("usuario_desbloqueado", detalhe=alvo["login"])
        st.session_state["_msg_usuarios"] = f"**{alvo['login']}** desbloqueado."
        st.rerun()
    if alvo["perfil"] == "professor":
        st.caption("As turmas do professor vêm da coluna `professores` da planilha (o último envio que trouxe a coluna vale).")


def tela_auditoria(usuario):
    st.header("Auditoria")
    st.write("Trilha de acessos: quem abriu a ficha de qual aluno, quem entrou e saiu, e as ações sensíveis (envio de planilha, desfazer envios, "
             "apagar dados, gestão de usuários e configurações), com data e hora.")
    st.caption("Datas no horário de Brasília. Senhas nunca são registradas. Reiniciar os dados dos alunos **não** apaga esta trilha; "
               f"o prazo de guarda sugerido é de {auditoria.MESES_RETENCAO} meses.")
    mensagem = st.session_state.pop("_msg_auditoria", None)
    if mensagem:
        st.success(mensagem)

    hoje = date.today()
    c1, c2 = st.columns(2)
    periodo = c1.date_input("Período", value=(hoje - timedelta(days=30), hoje), max_value=hoje, format="DD/MM/YYYY", key="aud_periodo")
    eventos = c2.multiselect("Tipo de evento", list(auditoria.EVENTOS), format_func=auditoria.EVENTOS.get, key="aud_eventos",
                             placeholder="Todos os eventos")
    c3, c4 = st.columns(2)
    login = c3.selectbox("Usuário", [None] + auditoria.logins_registrados(), format_func=lambda x: "Todos" if x is None else x, key="aud_login")
    aluno = c4.text_input("Aluno (matrícula ou parte do nome)", key="aud_aluno")
    if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
        de, ate = periodo
    elif isinstance(periodo, (tuple, list)) and len(periodo) == 1:
        de, ate = periodo[0], periodo[0]
    else:
        de = ate = periodo
    filtros = dict(login=login, eventos=eventos or None, aluno=aluno, de=de, ate=ate)
    total = auditoria.contar(**filtros)
    linhas = auditoria.listar(**filtros)
    st.write(f"**{total:,}** registro(s) no filtro".replace(",", ".") + (f" — mostrando os {len(linhas):,} mais recentes.".replace(",", ".") if total > len(linhas) else "."))
    if linhas:
        def quem(l):
            return f"{l['nome_usuario']} ({l['login']})" if l["nome_usuario"] else (l["login"] or "—")
        def qual_aluno(l):
            return " — ".join(x for x in (l["matricula"], l["nome_aluno"]) if x) or "—"
        tabela = pd.DataFrame([{"Data/hora": _fmt_data_segundos(l["data_hora_brasilia"]), "Usuário": quem(l),
                                "Perfil": usuarios.PERFIS.get(l["perfil"], "—"), "Evento": auditoria.EVENTOS.get(l["evento"], l["evento"]),
                                "Aluno": qual_aluno(l), "Detalhe": l["detalhe"] or ""} for l in linhas])
        st.dataframe(tabela, hide_index=True, width="stretch")
        st.download_button("Baixar o que está na tela (CSV)", tabela.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           f"auditoria_{hoje:%Y%m%d}.csv", "text/csv")
    else:
        st.info("Nenhum registro com esses filtros.")

    st.subheader("Prazo de guarda")
    r = auditoria.resumo_retencao()
    st.write(f"A trilha tem **{r['total']:,}** registro(s)".replace(",", ".")
             + (f", o mais antigo de {_fmt_data(pd.to_datetime(r['mais_antigo']) - pd.Timedelta(hours=3))}." if r["mais_antigo"] else "."))
    if r["vencidos"]:
        st.warning(f"**{r['vencidos']:,}** registro(s) têm mais de {auditoria.MESES_RETENCAO} meses.".replace(",", "."))
        ok = st.checkbox(f"Entendo que apagar registros com mais de {auditoria.MESES_RETENCAO} meses não pode ser desfeito", key="aud_confirma_limpeza")
        if st.button("Apagar registros antigos", disabled=not ok, key="aud_limpar"):
            apagados = auditoria.apagar_anteriores_a(usuario=usuario)
            st.session_state["_msg_auditoria"] = f"{apagados} registro(s) antigos apagados."
            st.rerun()
    else:
        st.caption(f"Nenhum registro passou do prazo de {auditoria.MESES_RETENCAO} meses.")


# ----------------------------------------------------------------- app
def main():
    traducao.ativar()   # textos fixos do Streamlit em português (antes do login, para a tela de login também)
    usuario = exigir_login()
    manter_estado()
    garantir_banco_demo()
    usuario = usuarios.obter_usuario(usuario["id_usuario"])   # as turmas do professor podem ter acabado de chegar com a demonstração
    st.session_state["usuario"] = usuario

    try:
        carregar_modelo()
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível carregar o modelo (modelo/modelo_risco.pkl): {e}")
        st.caption("Isso costuma acontecer quando a versão do scikit-learn do app é diferente da usada para salvar o modelo.")
        st.stop()

    # Divergências: só quem pode resolvê-las (coordenação e administrador) as vê
    if permissoes.pode(usuario, "resolver_divergencias"):
        divergencias = pd.DataFrame(database.buscar_divergencias(incluir_resolvidas=True))
    else:
        divergencias = pd.DataFrame()
    n_div = int((~divergencias["resolvida"]).sum()) if not divergencias.empty else 0
    n_res = len(divergencias) - n_div
    # o item do menu aparece enquanto há pendentes (ou se a pessoa já está na tela e ainda há resolvidas para consultar)
    na_tela = st.session_state.get("tela") == TELA_DIVERGENCIAS
    mostrar_menu = bool(n_div) or (na_tela and bool(n_res))
    telas = [t for t in permissoes.telas_permitidas(usuario) if t != TELA_DIVERGENCIAS or mostrar_menu]
    if st.session_state.get("tela") not in telas:
        st.session_state["tela"] = "Visão geral"   # tela sem permissão, ou que sumiu do menu (sem divergências)

    with st.sidebar:
        st.title("🎓 Evasão Escolar")
        tela = st.radio("Telas", telas, key="tela", label_visibility="collapsed")
        if tela != "Ficha do aluno":
            st.session_state.pop("_ficha_auditada", None)   # ao voltar para a ficha, a abertura é registrada de novo
        st.divider()
        st.caption(f"**{usuario['nome']}** · {usuarios.PERFIS[usuario['perfil']]}")
        st.caption("Dados sensíveis de alunos (muitos menores de idade — LGPD). Use apenas para ação pedagógica de apoio.")
        st.button("Sair", on_click=_sair)

    limite_freq = database.obter_limite_frequencia()
    visao_escola = enriquecer_visao(pd.DataFrame(database.buscar_visao_geral()), limite_freq)
    visao = permissoes.restringir_alunos(visao_escola, usuario)   # professor: só as turmas dele
    if not visao.empty and visao["matricula"].str.startswith("DEMO-").all():
        st.warning("Exibindo **dados fictícios de demonstração**.")

    if tela == "Minha conta":
        tela_trocar_senha(usuario)
    elif tela == "Usuários":
        tela_usuarios(usuario)
    elif tela == "Auditoria":
        tela_auditoria(usuario)
    elif tela == "Configurações":
        tela_configuracoes(limite_freq)
    elif tela == "Upload de dados":
        tela_upload(pode_apagar=permissoes.pode(usuario, "apagar_dados"))
    elif tela == TELA_DIVERGENCIAS:
        tela_divergencias(divergencias, usuario)
    elif visao.empty and not visao_escola.empty:   # professor sem turmas atribuídas
        st.header(tela)
        st.info("Você ainda não tem turmas atribuídas. A atribuição vem da coluna `professores` da planilha enviada pela coordenação: "
                f"peça para incluir o seu login (`{usuario['login']}`) nas turmas em que você leciona.")
    elif tela == "Visão geral":
        tela_visao_geral(visao, n_div, limite_freq, n_res, permissoes.pode(usuario, "resolver_divergencias"))
    elif tela == "Lista priorizada":
        tela_lista(visao, limite_freq)
    elif tela == "Ficha do aluno":
        tela_ficha(visao, limite_freq, usuario)
    elif tela == "Relatórios":
        tela_relatorios(visao, limite_freq, restrito=not permissoes.pode(usuario, "ver_todos_os_alunos"))


main()
