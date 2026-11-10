"""Testes da logica de pareamento usada na avaliacao (nao chamam a API)."""
from avaliar import maior_pareamento


def aceita(esperado, obtido):
    # esperado = conjunto de valores aceitos; obtido = um valor
    return obtido in esperado


def test_ordem_nao_importa():
    esperados = [{"rede"}, {"sistemas"}]
    assert maior_pareamento(esperados, ["sistemas", "rede"], aceita) == 2


def test_um_obtido_nao_atende_dois_esperados():
    esperados = [{"rede"}, {"rede"}]
    assert maior_pareamento(esperados, ["rede"], aceita) == 1


def test_sem_par_compativel():
    assert maior_pareamento([{"rede"}], ["hardware"], aceita) == 0


def test_escolha_gulosa_falharia_aqui():
    # O primeiro esperado aceita "a" ou "b"; o segundo so aceita "a".
    # Se o primeiro "roubar" o "a", o segundo fica sem par. A busca completa acerta.
    esperados = [{"a", "b"}, {"a"}]
    assert maior_pareamento(esperados, ["a", "b"], aceita) == 2


def test_sem_esperados():
    assert maior_pareamento([], ["a"], aceita) == 0