"""Avaliacao OFFLINE: pontua respostas da IA ja salvas contra o gabarito.

Nao chama a API. Roda o supervisor (regras.py) de novo sobre as respostas
salvas, entao voce pode ajustar as regras e reavaliar em segundos.

Uso:
    python avaliar.py
    python avaliar.py --respostas dados/respostas_ia_r2.json
    python avaliar.py --todos                  # mostra tambem os chamados sem divergencia
    python avaliar.py --revelar-reservados     # mostra detalhes do conjunto reservado
"""
import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from modelos import Prioridade, ResultadoTriagem
from regras import avaliar as supervisor


@dataclass
class Linha:
    """Resultado da avaliacao de UM chamado."""

    id: str
    tipo: str
    conjunto: str
    revisao_esperada: bool
    status: str = "ok"  # ok | sem_resposta | falha_ia | desatualizada | incompativel
    modelo: str = ""    # qual modelo respondeu este chamado
    separacao_ok: bool | None = None
    categoria_ok: bool | None = None
    equipe_ok: bool | None = None
    prioridade_ok: bool | None = None
    revisao_obtida: bool | None = None
    divergencias: list[str] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)


def carregar_json(caminho: Path):
    if not caminho.exists():
        raise SystemExit(f"Arquivo não encontrado: {caminho}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def maior_pareamento(esperados: list, obtidos: list, aceita) -> int:
    """Quantos problemas esperados conseguem um problema obtido DIFERENTE e compativel.

    Nao depende da ordem em que a IA devolveu os problemas. `aceita(esperado,
    obtido)` diz se um par e compativel. Cada problema obtido so pode ser usado
    uma vez. Como ha no maximo 5 problemas, testar todas as combinacoes por
    recursao e barato (e mais correto que "pegar o primeiro compativel").
    """

    def buscar(i: int, usados: frozenset) -> int:
        if i == len(esperados):
            return 0
        melhor = buscar(i + 1, usados)  # opcao 1: este esperado fica sem par
        for j, obtido in enumerate(obtidos):  # opcao 2: tenta cada obtido livre
            if j not in usados and aceita(esperados[i], obtido):
                melhor = max(melhor, 1 + buscar(i + 1, usados | {j}))
        return melhor

    return buscar(0, frozenset())


def categoria_aceita(esperado: dict, obtido) -> bool:
    return obtido.categoria.value in esperado["categorias_aceitas"]


def equipe_aceita(esperado: dict, obtido) -> bool:
    return obtido.equipe_destino.value in esperado["equipes_aceitas"]


def avaliar_chamado(chamado: dict, resposta: dict | None) -> Linha:
    gab = chamado["gabarito_esperado"]
    linha = Linha(
        id=chamado["id"],
        tipo=chamado.get("tipo", "?"),
        conjunto=chamado.get("conjunto", "desenvolvimento"),
        revisao_esperada=gab["revisao_humana"],
    )

    # --- casos em que nao da para avaliar ---
    if resposta is None:
        linha.status = "sem_resposta"
        linha.divergencias.append("Sem resposta coletada. Rode coletar_respostas.py.")
        return linha
    if not resposta.get("ok"):
        linha.status = "falha_ia"
        linha.divergencias.append(f"A IA falhou na coleta: {resposta.get('mensagem', '')}")
        return linha
    if "relato" in resposta and resposta["relato"] != chamado["relato"]:
        linha.status = "desatualizada"
        linha.divergencias.append("O relato mudou desde a coleta. Recolha este chamado.")
        return linha
    try:
        resultado = ResultadoTriagem.model_validate(resposta["resultado"])
    except ValidationError:
        linha.status = "incompativel"
        linha.divergencias.append("A resposta salva não cabe no schema atual. Recolha.")
        return linha

    linha.modelo = resposta.get("modelo", "") or "?"

    # --- supervisor: roda de novo, offline, com as regras atuais ---
    avaliacao = supervisor(resultado, chamado["relato"])
    linha.revisao_obtida = avaliacao.requer_revisao
    linha.motivos = [f"{m.codigo}({m.severidade.value})" for m in avaliacao.motivos]
    if linha.revisao_obtida and not linha.revisao_esperada:
        linha.divergencias.append("Falso alarme: pediu revisão, mas o gabarito diz que não precisava.")
    elif not linha.revisao_obtida and linha.revisao_esperada:
        linha.divergencias.append("Alerta perdido: não pediu revisão, mas o gabarito diz que precisava.")

    # --- classificacao (so quando o gabarito pede; casos vagos avaliam so a revisao) ---
    if gab.get("avaliar_classificacao", True):
        esperados = gab.get("problemas_esperados", [])
        obtidos = resultado.problemas
        n = len(esperados)
        # Faixa aceita de problemas: por padrao exatamente n; o gabarito pode abrir
        # uma faixa com problemas_min / problemas_max (casos em que ha mais de uma
        # forma razoavel de separar o relato).
        minimo = gab.get("problemas_min", n)
        maximo = gab.get("problemas_max", n)
        linha.separacao_ok = minimo <= len(obtidos) <= maximo
        linha.categoria_ok = maior_pareamento(esperados, obtidos, categoria_aceita) == n
        linha.equipe_ok = maior_pareamento(esperados, obtidos, equipe_aceita) == n
        if not linha.separacao_ok:
            faixa = f"{minimo}" if minimo == maximo else f"{minimo} a {maximo}"
            linha.divergencias.append(f"Separação: esperado {faixa} problema(s), obtido {len(obtidos)}.")
        if not linha.categoria_ok:
            linha.divergencias.append(
                f"Categoria: aceitas {[e['categorias_aceitas'] for e in esperados]} | "
                f"obtidas {[p.categoria.value for p in obtidos]}"
            )
        if not linha.equipe_ok:
            linha.divergencias.append(
                f"Equipe: aceitas {[e['equipes_aceitas'] for e in esperados]} | "
                f"obtidas {[p.equipe_destino.value for p in obtidos]}"
            )
    # --- prioridade (opcional): detecta prioridade INFLADA, ex.: urgencia falsa ou injecao ---
    limite = gab.get("prioridade_maxima")
    if limite:
        ordem = [p.value for p in Prioridade]  # da mais baixa para a mais alta
        acima = [
            p.prioridade_sugerida.value
            for p in resultado.problemas
            if ordem.index(p.prioridade_sugerida.value) > ordem.index(limite)
        ]
        linha.prioridade_ok = not acima
        if acima:
            linha.divergencias.append(f"Prioridade inflada: limite '{limite}', obtida {acima}.")
    return linha


def fracao(acertos: int, total: int) -> str:
    return f"{acertos}/{total}" + (f" ({acertos / total * 100:.0f}%)" if total else "")


def carregar_linhas(caminho_chamados, caminho_respostas) -> list[Linha]:
    """Avalia todos os chamados contra um arquivo de respostas salvas."""
    chamados = carregar_json(Path(caminho_chamados))
    respostas = carregar_json(Path(caminho_respostas))
    return [avaliar_chamado(c, respostas.get(c["id"])) for c in chamados]


def resumir(linhas: list[Linha]) -> dict:
    """Calcula as metricas de um grupo de chamados (usado pelo terminal e pela interface)."""
    ok = [l for l in linhas if l.status == "ok"]
    nao_avaliados: dict[str, int] = defaultdict(int)
    for l in linhas:
        if l.status != "ok":
            nao_avaliados[l.status] += 1
    modelos: dict[str, int] = defaultdict(int)
    for l in ok:
        modelos[l.modelo] += 1

    classificados = [l for l in ok if l.separacao_ok is not None]
    com_limite = [l for l in ok if l.prioridade_ok is not None]
    nao_precisavam = [l for l in ok if not l.revisao_esperada]
    precisavam = [l for l in ok if l.revisao_esperada]
    return {
        "total": len(linhas),
        "avaliados": len(ok),
        "nao_avaliados": dict(nao_avaliados),
        "modelos": dict(modelos),
        "classificacao": {
            "n": len(classificados),
            "separacao": sum(l.separacao_ok for l in classificados),
            "categoria": sum(l.categoria_ok for l in classificados),
            "equipe": sum(l.equipe_ok for l in classificados),
        },
        "prioridade": {
            "n": len(com_limite),
            "infladas": [l.id for l in com_limite if not l.prioridade_ok],
        },
        "revisao": {
            "nao_precisavam": len(nao_precisavam),
            "falsos_alarmes": [l.id for l in nao_precisavam if l.revisao_obtida],
            "precisavam": len(precisavam),
            "perdidos": [l.id for l in precisavam if not l.revisao_obtida],
        },
    }


def _ids(ids: list[str], mostrar: bool) -> str:
    return f"  [{', '.join(ids)}]" if ids and mostrar else ""


def imprimir_resumo(titulo: str, linhas: list[Linha], mostrar_ids: bool) -> None:
    r = resumir(linhas)

    print(f"\n=== {titulo}: {r['total']} chamado(s) ===")
    detalhe = ""
    if r["nao_avaliados"]:
        detalhe = "  (" + ", ".join(f"{k}: {v}" for k, v in r["nao_avaliados"].items()) + ")"
    print(f"Avaliados: {r['avaliados']} | não avaliados: {sum(r['nao_avaliados'].values())}{detalhe}")
    if r["modelos"]:
        print("Modelos que responderam: " + ", ".join(f"{m}: {n}" for m, n in sorted(r["modelos"].items())))

    c = r["classificacao"]
    if c["n"]:
        print(f"\nClassificação (chamados com gabarito de classificação: {c['n']})")
        print(f"  Separação (nº de problemas): {fracao(c['separacao'], c['n'])}")
        print(f"  Categoria correta:           {fracao(c['categoria'], c['n'])}")
        print(f"  Equipe correta:              {fracao(c['equipe'], c['n'])}")

    p = r["prioridade"]
    if p["n"]:
        print(f"\nPrioridade (chamados com limite definido: {p['n']})")
        print(f"  Prioridade inflada: {len(p['infladas'])} de {p['n']}{_ids(p['infladas'], mostrar_ids)}")

    v = r["revisao"]
    print("\nRevisão humana")
    print(f"  Falsos alarmes:   {len(v['falsos_alarmes'])} de {v['nao_precisavam']} que NÃO precisavam"
          f"{_ids(v['falsos_alarmes'], mostrar_ids)}")
    print(f"  Alertas perdidos: {len(v['perdidos'])} de {v['precisavam']} que precisavam"
          f"{_ids(v['perdidos'], mostrar_ids)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pontua respostas salvas contra o gabarito (offline).")
    ap.add_argument("--chamados", "--gabarito", dest="chamados", default="dados/chamados_exemplo.json")
    ap.add_argument("--respostas", default="dados/respostas_ia.json")
    ap.add_argument("--todos", action="store_true", help="mostra também os chamados sem divergência")
    ap.add_argument("--revelar-reservados", action="store_true",
                    help="mostra os detalhes dos chamados do conjunto 'reservado'")
    args = ap.parse_args()

    linhas = carregar_linhas(args.chamados, args.respostas)

    print("DETALHES")
    for l in linhas:
        escondido = l.conjunto == "reservado" and not args.revelar_reservados
        com_problema = bool(l.divergencias) or l.status != "ok"
        if escondido or not (com_problema or args.todos):
            continue
        marca = "OK" if not com_problema else ("NÃO AVALIADO" if l.status != "ok" else "DIVERGÊNCIA")
        print(f"[{l.id}] ({l.tipo}) {marca}")
        for d in l.divergencias:
            print(f"    - {d}")
        if l.motivos:
            print(f"    - Motivos do supervisor: {', '.join(l.motivos)}")

    grupos = defaultdict(list)
    for l in linhas:
        grupos[l.conjunto].append(l)
    for nome in sorted(grupos):
        mostrar_ids = nome != "reservado" or args.revelar_reservados
        imprimir_resumo(nome, grupos[nome], mostrar_ids)


if __name__ == "__main__":
    main()