"""Chamada ao LLM + validacao. Nunca levanta excecao para a interface:
sempre devolve uma RespostaTriagem (ok=True com resultado, ou ok=False com
mensagem pronta para exibir ao usuario).

Somente a funcao _chamar_modelo conhece o provedor (Gemini, via Interactions
API). Para trocar de provedor no futuro, basta reescrever essa funcao.

Resiliencia: se um modelo estiver indisponivel (ex.: 503 por sobrecarga),
o codigo passa automaticamente para o proximo modelo da lista.
"""
import json
import logging
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import ValidationError

from modelos import ResultadoTriagem
from prompt import PROMPT_SISTEMA

# Le o arquivo .env ANTES de criar o cliente: o SDK procura GEMINI_API_KEY
# nas variaveis de ambiente.
load_dotenv()

log = logging.getLogger(__name__)

# Lista de modelos em ordem de preferencia: o primeiro e o preferido, os
# seguintes sao reserva. No .env: MODELOS_TRIAGEM=modelo1,modelo2
MODELOS = [
    m.strip()
    for m in os.getenv(
        "MODELOS_TRIAGEM", "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    ).split(",")
    if m.strip()
]
TIMEOUT_SEGUNDOS = 20  # por tentativa (o SDK pode repetir por conta propria)
MAX_TENTATIVAS = 2     # por modelo, apenas quando a resposta vem fora do formato
MAX_CARACTERES = 4000

MSG_MANUAL = "Erro no processamento da IA. Encaminhando para triagem manual."
MSG_INDISPONIVEL = "Sistema de IA indisponivel no momento. Use a triagem manual."
MSG_LIMITE = "Limite de uso da IA atingido. Aguarde um minuto ou use a triagem manual."


@dataclass
class RespostaTriagem:
    ok: bool
    resultado: ResultadoTriagem | None = None
    mensagem: str = ""
    modelo: str = ""  # qual modelo respondeu (util para a tela e para o README)


def _extrair_json(texto: str) -> dict:
    """Tolera cercas de codigo ou texto extra ao redor do JSON."""
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim == -1:
        raise json.JSONDecodeError("JSON nao encontrado", texto, 0)
    return json.loads(texto[inicio : fim + 1])


def _montar_entrada(relato: str) -> str:
    # Impede que o usuario "feche" a tag e escape do bloco de dados
    limpo = relato.replace("<relato>", "").replace("</relato>", "")
    return f"<relato>\n{limpo}\n</relato>"


def _chamar_modelo(relato: str, modelo: str) -> str:
    """Unico ponto que fala com o Gemini. Devolve o texto bruto da resposta."""
    cliente = genai.Client(
        http_options=types.HttpOptions(timeout=TIMEOUT_SEGUNDOS * 1000)  # milissegundos
    )
    interacao = cliente.interactions.create(
        model=modelo,
        system_instruction=PROMPT_SISTEMA,
        input=_montar_entrada(relato),
        generation_config={"max_output_tokens": 4000},
    )
    return interacao.output_text or ""


def triar(relato: str) -> RespostaTriagem:
    relato = (relato or "").strip()
    if not relato:
        return RespostaTriagem(False, mensagem="Digite o relato do chamado.")
    if len(relato) > MAX_CARACTERES:
        return RespostaTriagem(
            False, mensagem=f"Relato muito longo (maximo {MAX_CARACTERES} caracteres)."
        )

    ultima_falha = MSG_MANUAL

    for modelo in MODELOS:  # laco de fora: qual modelo tentar
        for tentativa in range(1, MAX_TENTATIVAS + 1):  # laco de dentro: quantas vezes
            try:
                texto = _chamar_modelo(relato, modelo)
                dados = _extrair_json(texto)
                return RespostaTriagem(
                    True,
                    resultado=ResultadoTriagem.model_validate(dados),
                    modelo=modelo,
                )

            except (json.JSONDecodeError, ValidationError) as e:
                # Resposta fora do formato: tenta de novo o MESMO modelo
                log.warning(
                    "%s, tentativa %d: resposta invalida (%s)", modelo, tentativa, e
                )
                continue

            except Exception as e:
                # Falha na chamada (sobrecarga, limite, timeout, rede): nao adianta
                # repetir neste modelo. Sai do laco de dentro e passa ao proximo.
                codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
                log.warning(
                    "Modelo %s indisponivel (%s, codigo=%s). Tentando o proximo.",
                    modelo,
                    type(e).__name__,
                    codigo,
                )
                ultima_falha = MSG_LIMITE if codigo == 429 else MSG_INDISPONIVEL
                break

    return RespostaTriagem(False, mensagem=ultima_falha)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    exemplo = (
        "Bom dia, a minha assinatura digital no e-SAJ parou de funcionar de repente. "
        "O token acende a luz, mas o sistema diz que o certificado e invalido. "
        "Tenho urgencia pois preciso assinar mandados ate as 15h, e a impressora "
        "do gabinete 3 tambem esta atolando folha."
    )
    r = triar(exemplo)
    if r.ok:
        print(f"Modelo que respondeu: {r.modelo}")
        print(r.resultado.model_dump_json(indent=2))
    else:
        print("FALHA:", r.mensagem)
