"""
Logout por inatividade.

Como funciona (duas camadas):
1. No navegador, um pequeno script conta o tempo sem cliques, digitação, toque ou rolagem. No último minuto mostra um aviso com
   contagem regressiva e o botão "Continuar conectado"; se o tempo acaba, aciona o encerramento da sessão no servidor
   (a tela volta ao login). Enquanto a pessoa usa a página, o script avisa o servidor (no máximo a cada 30 s) para que ele saiba
   que a sessão está viva.
2. No servidor, cada execução confere o horário da última atividade: se passou do prazo (mais uma folga de 2 minutos para os avisos
   do navegador), a sessão é encerrada mesmo que o script do navegador tenha sido bloqueado ou a aba estivesse suspensa.

O prazo padrão é de 15 minutos para todos os perfis. O Secret opcional `inatividade_minutos` muda o valor (mínimo 1,5; serve
para testes e para escolas que queiram um prazo diferente).
"""
import json
import time

import streamlit as st

MINUTOS_PADRAO = 15
MINUTOS_MINIMO = 1.5
AVISO_SEGUNDOS = 60
FOLGA_SERVIDOR_SEGUNDOS = 120
PING_MINIMO_SEGUNDOS = 30


def minutos_validos(valor):
    """Converte o valor configurado em minutos (padrão 15; nunca menos de 1,5)."""
    try:
        minutos = float(valor)
    except (TypeError, ValueError):
        return float(MINUTOS_PADRAO)
    if minutos != minutos:   # NaN
        return float(MINUTOS_PADRAO)
    return max(minutos, MINUTOS_MINIMO)


def expirou(ultima_atividade, agora, minutos):
    """True se passou do prazo (mais a folga) desde a última atividade registrada. Sem registro, não expira."""
    if ultima_atividade is None:
        return False
    return (agora - ultima_atividade) > minutos * 60 + FOLGA_SERVIDOR_SEGUNDOS


_ESTILO = """
<style>
.st-key-inat_ping, .st-key-inat_expirar { display: none !important; }
#inat-overlay { position: fixed; inset: 0; z-index: 999999; background: rgba(20, 30, 40, 0.65); backdrop-filter: blur(8px); display: flex;
  align-items: center; justify-content: center; font-family: inherit; }
#inat-overlay .inat-caixa { background: #fff; color: #1f2d3a; border-radius: 12px; padding: 28px 32px; max-width: 420px;
  text-align: center; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35); }
#inat-overlay .inat-caixa p { margin: 0 0 18px; font-size: 1.05rem; line-height: 1.4; }
#inat-overlay button { background: #2F6F82; color: #fff; border: 0; border-radius: 8px; padding: 10px 22px; font-size: 1rem; cursor: pointer; }
</style>
"""

_SCRIPT = """
<script>
(function () {
  if (window.__inatividade) window.__inatividade.parar();
  const LIMITE = %(limite)d * 1000, AVISO = %(aviso)d * 1000, PING_MIN = %(ping)d * 1000, PAUSA = 1500;
  const EVENTOS = ["mousedown", "keydown", "touchstart", "wheel", "scroll"];
  let ultima = Date.now(), ultimoPing = 0, pendente = false, avisando = false, encerrado = false, parado = false, ausentes = 0, timer = null;

  function clicar(chave) {
    const b = document.querySelector(".st-key-" + chave + " button");
    if (b) b.click();
    return !!b;
  }
  function ativo() {
    if (avisando || encerrado) return;
    ultima = Date.now();
    pendente = true;   // o aviso ao servidor sai no relógio (passo), nunca no meio de um clique do usuário
  }
  function caixa() {
    let o = document.getElementById("inat-overlay");
    if (!o) {
      // sem HTML em texto dentro do script: o sanitizador do Streamlit descarta scripts que contenham marcações
      o = document.createElement("div"); o.id = "inat-overlay";
      const cx = document.createElement("div"); cx.className = "inat-caixa";
      const tx = document.createElement("p");
      const bt = document.createElement("button"); bt.type = "button"; bt.textContent = "Continuar conectado";
      cx.appendChild(tx); cx.appendChild(bt); o.appendChild(cx);
      document.body.appendChild(o);
      bt.addEventListener("click", function () {
        avisando = false; ultima = Date.now(); ultimoPing = ultima; pendente = false; clicar("inat_ping"); remover();
      });
    }
    return o;
  }
  function remover() { const o = document.getElementById("inat-overlay"); if (o) o.remove(); }
  function avisar(segundos) {
    const o = caixa();
    o.querySelector("p").textContent = "Sua sessão vai ser encerrada por inatividade em " + segundos + " s.";
    if (!avisando) { avisando = true; o.querySelector("button").focus(); }
  }
  function expirar() {
    encerrado = true;
    const o = caixa();
    o.querySelector("p").textContent = "Sessão encerrada por inatividade. Voltando para a tela de login...";
    o.querySelector("button").style.display = "none";
    clicar("inat_expirar");
    // plano B: se o servidor não respondeu em 6 s (e este script ainda está valendo), recarrega a página, o que também encerra a sessão
    setTimeout(function () { if (!parado && document.querySelector(".st-key-inat_expirar")) window.location.reload(); }, 6000);
  }
  function parar() {
    parado = true;
    clearInterval(timer);
    EVENTOS.forEach(e => document.removeEventListener(e, ativo, true));
    remover();
    if (window.__inatividade && window.__inatividade.parar === parar) window.__inatividade = null;
  }
  function passo() {
    if (!document.querySelector(".st-key-inat_expirar")) {   // saiu da sessão: o servidor tirou os controles da página
      if (encerrado || ++ausentes >= 8) parar();   // depois de expirar, tira o aviso assim que a tela de login aparece
      return;
    }
    ausentes = 0;
    if (encerrado) return;
    const ocioso = Date.now() - ultima;
    // avisa o servidor que a sessão está viva: no máximo a cada PING_MIN e só quando a pessoa deu uma pausa (evita colidir com um clique)
    if (pendente && !avisando && ocioso >= PAUSA && Date.now() - ultimoPing > PING_MIN) { pendente = false; ultimoPing = Date.now(); clicar("inat_ping"); }
    if (ocioso >= LIMITE) expirar();
    else if (ocioso >= LIMITE - AVISO) avisar(Math.ceil((LIMITE - ocioso) / 1000));
  }
  EVENTOS.forEach(e => document.addEventListener(e, ativo, true));
  timer = setInterval(passo, 1000);
  window.__inatividade = { parar: parar };
})();
</script>
"""


@st.fragment
def _controles(ao_expirar, minutos):
    """Dois botões escondidos que o script do navegador aciona. Rodam como fragmento: não reexecutam a página inteira."""
    if st.button("ping", key="inat_ping"):
        # só renova se a sessão ainda estiver dentro do prazo (a verificação completa acontece na próxima execução da página)
        ultima = st.session_state.get("ultima_atividade")
        if not expirou(ultima, time.time(), minutos):
            st.session_state["ultima_atividade"] = time.time()
    if st.button("expirar", key="inat_expirar"):
        ao_expirar()
        st.rerun()


def vigiar(minutos, ao_expirar):
    """Liga a vigilância de inatividade para a sessão atual (chamar a cada execução, depois do login)."""
    minutos = minutos_validos(minutos)
    st.html(_ESTILO)   # em uma chamada à parte: o Streamlit só executa o script quando ele vem sozinho
    st.html(_SCRIPT % {"limite": int(minutos * 60), "aviso": AVISO_SEGUNDOS, "ping": PING_MINIMO_SEGUNDOS}, unsafe_allow_javascript=True)
    _controles(ao_expirar, minutos)
