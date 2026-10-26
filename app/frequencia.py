"""
Regras de frequência do app: alertas por avaliação, histórico de alertas e faixas prontas para filtrar.

A frequência NÃO entra no modelo de risco. O alerta é uma regra simples: frequência abaixo do limite que a escola
define em Configurações. O limite vale para todo o histórico (se a escola mudar o limite, os alertas passados são
recalculados com o limite novo).
"""

SEM_FREQUENCIA = "Sem frequência informada"

# Situação do alerta de cada aluno, considerando as avaliações em ordem
SITUACAO_NOVO = "Novo alerta"
SITUACAO_REINCIDENTE = "Reincidente (2 ou mais seguidas)"
SITUACAO_SAIU = "Saiu do alerta"
SITUACAO_SEM = "Sem alerta"
OPCOES_SITUACAO = ["Todos", SITUACAO_NOVO, SITUACAO_REINCIDENTE, SITUACAO_SAIU]


def _fmt(valor):
    return f"{valor:g}".replace(".", ",")


def situacao_alerta(frequencias, limite):
    """
    `frequencias`: frequência (%) de cada avaliação do aluno, da mais antiga para a mais recente (None/NaN = não
    informada, ignorada). Devolve (alertas_seguidos, situacao):

    - alertas_seguidos: quantas avaliações consecutivas, até a mais recente, ficaram abaixo do limite (0 se a última está ok);
    - situacao: "Novo alerta" (abaixo do limite agora, e não estava antes), "Reincidente (2 ou mais seguidas)",
      "Saiu do alerta" (estava abaixo antes e agora está no limite ou acima), "Sem alerta" ou "Sem frequência informada".
    """
    valores = [float(v) for v in (frequencias or []) if v is not None and v == v]
    if not valores:
        return 0, SEM_FREQUENCIA
    alertas = [v < limite for v in valores]
    seguidos = 0
    for a in reversed(alertas):
        if not a:
            break
        seguidos += 1
    if seguidos >= 2:
        return seguidos, SITUACAO_REINCIDENTE
    if seguidos == 1:
        return 1, SITUACAO_NOVO
    return 0, (SITUACAO_SAIU if any(alertas) else SITUACAO_SEM)


def faixas_frequencia(limite):
    """
    Faixas prontas para o filtro, calculadas a partir do limite configurado. Devolve uma lista ordenada de
    (rótulo, minimo, maximo_exclusivo); o intervalo é [minimo, maximo). A faixa "sem frequência" tem minimo None.
    Ex.: com limite 75 -> "Abaixo de 60%", "60% a menos de 75%", "75% ou mais", "Sem frequência informada".
    """
    meio = max(round(limite - 15, 1), 0)
    faixas = []
    if meio > 0:
        faixas.append((f"Abaixo de {_fmt(meio)}%", 0.0, meio))
        faixas.append((f"De {_fmt(meio)}% a menos de {_fmt(limite)}%", meio, float(limite)))
    else:
        faixas.append((f"Abaixo de {_fmt(limite)}%", 0.0, float(limite)))
    faixas.append((f"{_fmt(limite)}% ou mais", float(limite), 1e9))
    faixas.append((SEM_FREQUENCIA, None, None))
    return faixas


def rotulo_faixa(valor, faixas):
    """Rótulo da faixa em que a frequência `valor` cai (ou 'Sem frequência informada')."""
    if valor is None or valor != valor:
        return SEM_FREQUENCIA
    for rotulo, minimo, maximo in faixas:
        if minimo is not None and minimo <= valor < maximo:
            return rotulo
    return SEM_FREQUENCIA
