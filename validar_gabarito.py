"""Confere se o gabarito esta bem formado ANTES de gastar chamadas de API.

Pega erros de digitacao (ex.: "Hardware e periféricos" com acento), ids
repetidos, campos faltando e categorias/equipes que nao existem em modelos.py.

Uso:
    python validar_gabarito.py
    python validar_gabarito.py dados/outro_arquivo.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

from modelos import Categoria, Equipe, Prioridade

CAMINHO_PADRAO = "dados/chamados_exemplo.json"
CAMPOS_OBRIGATORIOS = ("id", "tipo", "relato", "gabarito_esperado")
CONJUNTOS_VALIDOS = ("desenvolvimento", "reservado")


def validar(caminho: Path) -> tuple[list[str], list[dict]]:
    erros: list[str] = []
    try:
        chamados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"Arquivo não encontrado: {caminho}"], []
    except json.JSONDecodeError as e:
        return [f"JSON inválido na linha {e.lineno}, coluna {e.colno}: {e.msg} "
                "(procure vírgula faltando ou sobrando perto dessa linha)"], []

    categorias_validas = {c.value for c in Categoria}
    equipes_validas = {e.value for e in Equipe}

    for id_, n in Counter(c.get("id") for c in chamados).items():
        if n > 1:
            erros.append(f"id repetido: {id_} aparece {n} vezes")

    for c in chamados:
        cid = c.get("id", "?")
        for campo in CAMPOS_OBRIGATORIOS:
            if campo not in c:
                erros.append(f"[{cid}] falta o campo '{campo}'")
        if not str(c.get("relato", "")).strip():
            erros.append(f"[{cid}] relato vazio")
        if c.get("conjunto", "desenvolvimento") not in CONJUNTOS_VALIDOS:
            erros.append(f"[{cid}] conjunto inválido: {c.get('conjunto')!r} "
                         f"(use {CONJUNTOS_VALIDOS})")

        gab = c.get("gabarito_esperado", {})
        if not isinstance(gab.get("revisao_humana"), bool):
            erros.append(f"[{cid}] 'revisao_humana' precisa ser true ou false")
        if "categorias" in gab or "equipes" in gab:
            erros.append(f"[{cid}] ainda está no formato ANTIGO (categorias/equipes). "
                         "Converta para 'problemas_esperados'.")

        problemas = gab.get("problemas_esperados", [])
        limite = gab.get("prioridade_maxima")
        if limite is not None and limite not in {p.value for p in Prioridade}:
            erros.append(f"[{cid}] prioridade_maxima inválida: {limite!r}. "
                         f"Válidas: {[p.value for p in Prioridade]}")
        minimo = gab.get("problemas_min", len(problemas))
        maximo = gab.get("problemas_max", len(problemas))
        if not (isinstance(minimo, int) and isinstance(maximo, int)):
            erros.append(f"[{cid}] problemas_min e problemas_max precisam ser números inteiros")
        elif gab.get("avaliar_classificacao", True) and not (minimo <= len(problemas) <= maximo):
            erros.append(f"[{cid}] a faixa {minimo}..{maximo} não inclui os "
                         f"{len(problemas)} problemas_esperados")
        if gab.get("avaliar_classificacao", True) and not problemas:
            erros.append(f"[{cid}] avaliar_classificacao é true, mas não há problemas_esperados")
        for k, p in enumerate(problemas, 1):
            for chave, validos in (("categorias_aceitas", categorias_validas),
                                   ("equipes_aceitas", equipes_validas)):
                lista = p.get(chave)
                if not lista:
                    erros.append(f"[{cid}] problema {k}: falta '{chave}'")
                    continue
                for valor in lista:
                    if valor not in validos:
                        erros.append(f"[{cid}] problema {k}: '{valor}' não existe em {chave}. "
                                     f"Válidos: {sorted(validos)}")
    return erros, chamados


def main() -> None:
    caminho = Path(sys.argv[1] if len(sys.argv) > 1 else CAMINHO_PADRAO)
    erros, chamados = validar(caminho)

    if erros:
        print(f"{len(erros)} problema(s) encontrado(s) em {caminho}:\n")
        for e in erros:
            print(f"  - {e}")
        raise SystemExit(1)

    por_tipo = Counter(c["tipo"] for c in chamados)
    reservados = [c["id"] for c in chamados if c.get("conjunto") == "reservado"]
    print(f"OK: {len(chamados)} chamados bem formados em {caminho}")
    print("Por tipo:", dict(por_tipo))
    print(f"Reservados: {len(reservados)}" + (f" {reservados}" if reservados else ""))
    if not reservados:
        print("Aviso: nenhum chamado marcado como 'reservado'.")


if __name__ == "__main__":
    main()