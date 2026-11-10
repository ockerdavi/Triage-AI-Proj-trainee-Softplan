"""Testes unitarios do supervisor (regras.py). Nao chamam a API."""
import pytest

import regras
from modelos import Categoria, Equipe, Prioridade, Problema, ResultadoTriagem
from regras import Severidade, avaliar

RELATO_PADRAO = "Este e um relato padrao longo o suficiente para passar no teste de contagem."


def problema(**ajustes) -> Problema:
    """Um problema valido; cada teste altera so o campo que quer provocar."""
    dados = dict(
        categoria=Categoria.SISTEMAS,
        equipe_destino=Equipe.SISTEMAS,
        prioridade_sugerida=Prioridade.BAIXA,
        justificativa="Justificativa",
        trecho_do_relato="relato padrao longo",
    )
    dados.update(ajustes)
    return Problema(**dados)


def montar(**ajustes) -> ResultadoTriagem:
    """Um resultado 'limpo' (sem motivos); cada teste altera so o que precisa."""
    base = {
        "problemas": [problema()],
        "informacoes_essenciais_faltantes": [],
        "informacoes_complementares": [],
        "ambiguidades": [],
        "confianca_autodeclarada": 0.9,
        "fora_do_escopo": False,
    }
    base.update(ajustes)
    return ResultadoTriagem(**base)


def codigos(avaliacao) -> set:
    return {m.codigo for m in avaliacao.motivos}


def test_caso_limpo_nao_gera_motivos():
    av = avaliar(montar(), RELATO_PADRAO)
    assert not av.requer_revisao
    assert len(av.motivos) == 0


def test_relato_curto_gera_aviso():
    # Relato curto que CONTEM o trecho citado: so a regra do relato curto dispara.
    # (Com "Curto demais", o trecho nao existiria e TRECHO_INVENTADO tambem dispararia.)
    av = avaliar(montar(), "relato padrao longo")
    assert not av.requer_revisao
    assert any(m.codigo == "RELATO_CURTO" and m.severidade == Severidade.AVISO
               for m in av.motivos)


@pytest.mark.parametrize("confianca, espera_revisao", [
    (0.69, True), (0.70, False), (0.95, False), (0.0, True),
])
def test_limite_de_confianca(confianca, espera_revisao):
    av = avaliar(montar(confianca_autodeclarada=confianca), RELATO_PADRAO)
    assert av.requer_revisao == espera_revisao
    if espera_revisao:
        assert "CONFIANCA_BAIXA" in codigos(av)


def test_fora_do_escopo_exige_revisao():
    av = avaliar(montar(fora_do_escopo=True), RELATO_PADRAO)
    assert av.requer_revisao
    assert "FORA_DO_ESCOPO" in codigos(av)


def test_info_essencial_gera_revisao():
    av = avaliar(montar(informacoes_essenciais_faltantes=["Falta nome do sistema"]), RELATO_PADRAO)
    assert av.requer_revisao
    assert any(m.codigo == "INFO_ESSENCIAL_FALTANTE" and m.severidade == Severidade.REVISAO
               for m in av.motivos)


def test_info_complementar_gera_apenas_aviso():
    av = avaliar(montar(informacoes_complementares=["Falta tombo", "Falta setor"]), RELATO_PADRAO)
    assert not av.requer_revisao
    assert any(m.codigo == "INFO_COMPLEMENTAR" and m.severidade == Severidade.AVISO
               for m in av.motivos)


@pytest.mark.parametrize("qtd, espera_sev", [
    (0, None), (1, Severidade.AVISO), (2, Severidade.REVISAO),
])
def test_ambiguidades_por_quantidade(qtd, espera_sev):
    av = avaliar(montar(ambiguidades=["A"] * qtd), RELATO_PADRAO)
    codigos_amb = ["AMBIGUIDADE_DETECTADA", "MUITAS_AMBIGUIDADES"]
    if not espera_sev:
        assert not any(m.codigo in codigos_amb for m in av.motivos)
    else:
        alerta = next(m for m in av.motivos if m.codigo in codigos_amb)
        assert alerta.severidade == espera_sev


def test_dois_problemas_nao_geram_aviso():
    av = avaliar(montar(problemas=[problema(), problema()]), RELATO_PADRAO)
    assert "MUITOS_PROBLEMAS" not in codigos(av)


def test_tres_problemas_geram_apenas_aviso():
    av = avaliar(montar(problemas=[problema(), problema(), problema()]), RELATO_PADRAO)
    assert not av.requer_revisao
    assert any(m.codigo == "MUITOS_PROBLEMAS" and m.severidade == Severidade.AVISO
               for m in av.motivos)


def test_prioridade_critica_exige_revisao():
    av = avaliar(montar(problemas=[problema(prioridade_sugerida=Prioridade.CRITICA)]), RELATO_PADRAO)
    assert av.requer_revisao
    assert "PRIORIDADE_CRITICA" in codigos(av)


def test_categoria_com_equipe_incoerente_exige_revisao():
    av = avaliar(montar(problemas=[problema(equipe_destino=Equipe.SEGURANCA)]), RELATO_PADRAO)
    assert av.requer_revisao
    assert "EQUIPE_INCOERENTE" in codigos(av)


def test_hardware_para_infraestrutura_e_aceito():
    av = avaliar(
        montar(problemas=[problema(categoria=Categoria.HARDWARE, equipe_destino=Equipe.INFRA)]),
        RELATO_PADRAO,
    )
    assert "EQUIPE_INCOERENTE" not in codigos(av)


def test_trecho_inventado_exige_revisao():
    av = avaliar(montar(problemas=[problema(trecho_do_relato="texto inventado")]), RELATO_PADRAO)
    assert av.requer_revisao
    assert "TRECHO_INVENTADO" in codigos(av)


def test_trecho_com_acento_e_pontuacao_diferentes_nao_gera_alerta():
    av = avaliar(
        montar(problemas=[problema(trecho_do_relato="rELATO! Padrao... LONGó;")]),
        RELATO_PADRAO,
    )
    assert "TRECHO_INVENTADO" not in codigos(av)


@pytest.mark.parametrize("relato, trecho", [
    ("A água pingou d’água na mesa", "pingou d'água na mesa"),
    ("Gabinete sala–3 sem rede", "sala 3 sem rede"),
])
def test_trecho_tolera_aspas_curvas_e_travessao(relato, trecho):
    av = avaliar(
        montar(problemas=[problema(trecho_do_relato=trecho)]),
        relato + " texto extra para passar do mínimo",
    )
    assert "TRECHO_INVENTADO" not in codigos(av)


def test_regra_que_quebra_pede_revisao_por_precaucao(monkeypatch):
    def regra_bugada(resultado, relato):
        raise ValueError("Bug injetado")

    monkeypatch.setattr(regras, "REGRAS", (regra_bugada,))
    av = regras.avaliar(montar(), RELATO_PADRAO)
    assert av.requer_revisao
    assert "ERRO_NA_REGRA" in codigos(av)