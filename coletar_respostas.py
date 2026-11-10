"""Coleta: chama a IA para cada chamado e SALVA as respostas num arquivo.

E a unica parte da avaliacao que usa a API (e a internet). Depois de coletar,
rode `python avaliar.py` quantas vezes quiser, sem gastar cota.

Uso:
    python coletar_respostas.py                       # coleta so o que falta
    python coletar_respostas.py --refazer             # recoleta tudo
    python coletar_respostas.py --ids T01 T05         # recoleta so estes
    python coletar_respostas.py --saida dados/respostas_ia_r2.json   # outra rodada
    python coletar_respostas.py --pausa 8             # mais espaco entre chamadas

Se voce mudar o prompt, o schema ou o modelo, use --refazer: as respostas
antigas deixam de representar o sistema atual.
"""
import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from triagem import MSG_LIMITE, triar

PAUSA_PADRAO = 5          # segundos entre chamadas (evita estourar o limite por minuto)
ESPERA_LIMITE_PADRAO = 60  # segundos de espera quando a API responde "limite de uso"
TENTATIVAS_LIMITE = 3

logging.basicConfig(level=logging.WARNING)  # esconde o ruido de INFO da biblioteca de rede


def carregar_json(caminho: Path, padrao):
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar(caminho: Path, respostas: dict) -> None:
    """Grava num arquivo temporario e troca de uma vez, para nunca deixar o
    arquivo pela metade se o programa for interrompido no meio da escrita."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(respostas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporario.replace(caminho)


def coletar_um(relato: str, espera_limite: int):
    """Chama triar(); se o limite de uso estourar, espera e tenta de novo."""
    for tentativa in range(1, TENTATIVAS_LIMITE + 1):
        r = triar(relato)
        if r.ok or r.mensagem != MSG_LIMITE:
            return r
        if tentativa < TENTATIVAS_LIMITE:
            print(f"    limite de uso atingido; aguardando {espera_limite}s...")
            time.sleep(espera_limite)
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description="Coleta as respostas da IA e salva em arquivo.")
    ap.add_argument("--chamados", default="dados/chamados_exemplo.json")
    ap.add_argument("--saida", default="dados/respostas_ia.json")
    ap.add_argument("--refazer", action="store_true", help="recoleta todos os chamados")
    ap.add_argument("--ids", nargs="+", help="recoleta apenas estes ids")
    ap.add_argument("--pausa", type=float, default=PAUSA_PADRAO)
    ap.add_argument("--espera-limite", type=int, default=ESPERA_LIMITE_PADRAO)
    args = ap.parse_args()

    chamados = carregar_json(Path(args.chamados), None)
    if chamados is None:
        raise SystemExit(f"Arquivo de chamados não encontrado: {args.chamados}")

    caminho_saida = Path(args.saida)
    respostas = carregar_json(caminho_saida, {})

    if args.ids:
        desconhecidos = set(args.ids) - {c["id"] for c in chamados}
        if desconhecidos:
            raise SystemExit(f"Ids que não existem no arquivo: {sorted(desconhecidos)}")
        alvo = [c for c in chamados if c["id"] in args.ids]
    elif args.refazer:
        alvo = chamados
    else:  # padrao: so o que ainda nao foi coletado com sucesso
        alvo = [c for c in chamados if not respostas.get(c["id"], {}).get("ok")]

    print(f"{len(alvo)} chamado(s) para coletar de {len(chamados)} no total.\n")

    for i, c in enumerate(alvo):
        print(f"[{c['id']}] ({c.get('tipo', '?')}) coletando...")
        r = coletar_um(c["relato"], args.espera_limite)
        respostas[c["id"]] = {
            "ok": r.ok,
            "modelo": r.modelo,
            "mensagem": r.mensagem,
            "coletado_em": datetime.now().isoformat(timespec="seconds"),
            "relato": c["relato"],  # permite detectar se o relato mudou depois
            "resultado": r.resultado.model_dump(mode="json") if r.ok else None,
        }
        salvar(caminho_saida, respostas)  # salva a cada chamado: nada se perde
        print(f"    {'ok (' + r.modelo + ')' if r.ok else 'FALHOU: ' + r.mensagem}")
        if i < len(alvo) - 1:
            time.sleep(args.pausa)

    falhas = [cid for cid, d in respostas.items() if not d.get("ok")]
    print(f"\nRespostas salvas em {caminho_saida}")
    if falhas:
        print(f"Chamados que falharam: {', '.join(falhas)}")
        print("Rode de novo o mesmo comando: ele coleta só o que falta.")
    print(f"Próximo passo: python avaliar.py --respostas {caminho_saida}")


if __name__ == "__main__":
    main()