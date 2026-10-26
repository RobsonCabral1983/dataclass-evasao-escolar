"""
Tradução para português dos textos fixos do Streamlit que não dá para trocar por parâmetro
(barra da tabela, menu da tabela, seleção de arquivo, menu ⋮ do app, "Choose options"...).

O Streamlit não tem tradução própria da interface, então um pequeno script no navegador troca o texto exato
(e os atributos placeholder, aria-label e title) por sua versão em português. Textos que não estão na tabela
continuam em inglês, sem erro. Os textos do próprio app já são escritos em português no código.
"""
import json

import streamlit as st

TRADUCOES = {
    # campos de seleção
    "Choose options": "Escolha as opções",
    "Choose an option": "Escolha uma opção",
    "No results": "Nenhum resultado",
    "No results found": "Nenhum resultado encontrado",
    "Select all": "Selecionar tudo",
    "Press Enter to apply": "Pressione Enter para aplicar",
    "Press Enter to submit form": "Pressione Enter para enviar",
    "Clear all": "Limpar tudo",
    # envio de arquivo
    "Upload": "Selecionar arquivo",
    "Browse files": "Procurar arquivos",
    "Drag and drop file here": "Arraste e solte o arquivo aqui",
    "Drag and drop files here": "Arraste e solte os arquivos aqui",
    "Remove file": "Remover arquivo",
    "file upload": "envio de arquivo",
    # barra e menus da tabela
    "Show/hide columns": "Mostrar/ocultar colunas",
    "Download as CSV": "Baixar como CSV",
    "Search": "Pesquisar",
    "Type to search": "Digite para pesquisar",
    "Fullscreen": "Tela cheia",
    "Exit fullscreen": "Sair da tela cheia",
    "Close fullscreen": "Sair da tela cheia",
    "Sort ascending": "Ordem crescente",
    "Sort descending": "Ordem decrescente",
    "Clear sort": "Limpar ordenação",
    "Pin column": "Fixar coluna",
    "Unpin column": "Desafixar coluna",
    "Hide column": "Ocultar coluna",
    "Autosize": "Ajustar largura",
    "Format": "Formato",
    "Automatic": "Automático",
    "Plain": "Simples",
    "Localized": "Local",
    "Percent": "Porcentagem",
    "Hide all": "Ocultar tudo",
    "Show all": "Mostrar tudo",
    "Next match": "Próxima ocorrência",
    "Previous match": "Ocorrência anterior",
    "Close": "Fechar",
    # menu do app (⋮) e barra superior
    "Rerun": "Executar novamente",
    "Auto rerun": "Executar automaticamente",
    "Clear cache": "Limpar cache",
    "Print": "Imprimir",
    "Record screen": "Gravar tela",
    "Record a screencast": "Gravar a tela",
    "Settings": "Configurações do Streamlit",
    "About": "Sobre",
    "Deploy": "Publicar",
    "Stop": "Parar",
    "Running...": "Executando...",
    "Made with Streamlit": "Feito com Streamlit",
    "Copy": "Copiar",
    "Copied": "Copiado",
    "Download": "Baixar",
}

# textos com números: expressão regular -> modelo (\\1 é o primeiro trecho capturado)
PADROES = [
    [r"^(\d+(?:\.\d+)?)\s?([KMG]?B) per file(?: • (.*))?$", "Limite de $1 $2 por arquivo • $3"],
    [r"^Made with Streamlit v([\d.]+)$", "Feito com Streamlit v$1"],
    [r"^Limit (\d+(?:\.\d+)?)\s?([KMG]?B) per file(?: • (.*))?$", "Limite de $1 $2 por arquivo • $3"],
]

_SCRIPT = """
<script>
(function () {
  if (window.__traducaoAtiva) return;
  window.__traducaoAtiva = true;
  const mapa = %(mapa)s;
  const padroes = %(padroes)s.map(p => [new RegExp(p[0]), p[1]]);
  const atributos = ["placeholder", "aria-label", "title"];

  function traduzir(texto) {
    const t = texto.trim();
    if (!t) return null;
    if (Object.prototype.hasOwnProperty.call(mapa, t)) return texto.replace(t, mapa[t]);
    for (const [re, modelo] of padroes) {
      if (re.test(t)) return texto.replace(t, t.replace(re, modelo).replace(/ • $/, ""));
    }
    return null;
  }
  function varrer(raiz) {
    if (!raiz) return;
    if (raiz.nodeType === 3) {
      const novo = traduzir(raiz.nodeValue);
      if (novo !== null && novo !== raiz.nodeValue) raiz.nodeValue = novo;
      return;
    }
    if (raiz.nodeType !== 1 || ["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"].includes(raiz.tagName)) return;
    if (raiz.closest && raiz.closest("[data-testid='stMarkdownContainer'], [data-testid='stDataFrameResizable'] canvas")) {
      // texto escrito pelo próprio app (já em português): só os atributos dos elementos de interface são tocados
    }
    for (const a of atributos) {
      const v = raiz.getAttribute && raiz.getAttribute(a);
      if (v) { const novo = traduzir(v); if (novo !== null && novo !== v) raiz.setAttribute(a, novo); }
    }
    const filhos = raiz.childNodes;
    for (let i = 0; i < filhos.length; i++) varrer(filhos[i]);
  }
  let agendado = false;
  function agendar() {
    if (agendado) return;
    agendado = true;
    requestAnimationFrame(() => { agendado = false; varrer(document.body); });
  }
  new MutationObserver(agendar).observe(document.body, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: atributos});
  agendar();
})();
</script>
"""


def ativar():
    """Liga a tradução da interface (rodar uma vez por página)."""
    st.html(_SCRIPT % {"mapa": json.dumps(TRADUCOES, ensure_ascii=False),
                       "padroes": json.dumps(PADROES, ensure_ascii=False)}, unsafe_allow_javascript=True)
