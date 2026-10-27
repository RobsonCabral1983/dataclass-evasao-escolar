"""Regras de frequência (alerta, faixas) e prazo de inatividade."""
import pytest

import frequencia
from frequencia import SITUACAO_NOVO, SITUACAO_REINCIDENTE, SITUACAO_SAIU, SITUACAO_SEM, SEM_FREQUENCIA


@pytest.mark.parametrize("serie,esperado", [
    ([], (0, SEM_FREQUENCIA)),
    ([None, float("nan")], (0, SEM_FREQUENCIA)),
    ([90, 80], (0, SITUACAO_SEM)),
    ([90, 70], (1, SITUACAO_NOVO)),
    ([70, 60], (2, SITUACAO_REINCIDENTE)),
    ([90, 70, 60, 50], (3, SITUACAO_REINCIDENTE)),
    ([70, 90], (0, SITUACAO_SAIU)),
    ([75], (0, SITUACAO_SEM)),        # exatamente no limite não é alerta
    ([70, None, 60], (2, SITUACAO_REINCIDENTE)),   # avaliação sem frequência é ignorada
])
def test_situacao_do_alerta(serie, esperado):
    assert frequencia.situacao_alerta(serie, 75) == esperado


def test_faixas_com_limite_75():
    faixas = frequencia.faixas_frequencia(75)
    assert [f[0] for f in faixas] == ["Abaixo de 60%", "De 60% a menos de 75%", "75% ou mais", SEM_FREQUENCIA]
    assert frequencia.rotulo_faixa(59.9, faixas) == "Abaixo de 60%"
    assert frequencia.rotulo_faixa(60, faixas) == "De 60% a menos de 75%"
    assert frequencia.rotulo_faixa(75, faixas) == "75% ou mais"
    assert frequencia.rotulo_faixa(None, faixas) == SEM_FREQUENCIA
    assert frequencia.rotulo_faixa(float("nan"), faixas) == SEM_FREQUENCIA


def test_faixas_com_limite_baixo_nao_ficam_negativas():
    faixas = frequencia.faixas_frequencia(10)
    assert faixas[0] == ("Abaixo de 10%", 0.0, 10.0)


@pytest.mark.parametrize("valor,esperado", [(None, 15.0), ("abc", 15.0), (float("nan"), 15.0), (0.5, 1.5), (20, 20.0), ("30", 30.0)])
def test_minutos_de_inatividade(valor, esperado):
    inatividade = pytest.importorskip("inatividade")   # exige o streamlit instalado
    assert inatividade.minutos_validos(valor) == esperado


def test_expiracao_por_inatividade():
    inatividade = pytest.importorskip("inatividade")
    folga = inatividade.FOLGA_SERVIDOR_SEGUNDOS
    assert inatividade.expirou(None, 10_000, 15) is False
    assert inatividade.expirou(0, 15 * 60 + folga, 15) is False       # no limite ainda vale
    assert inatividade.expirou(0, 15 * 60 + folga + 1, 15) is True
