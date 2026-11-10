"""Supervisor deterministico: decide se o resultado da IA exige revisao humana."""
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from modelos import ResultadoTriagem, Categoria, Equipe

class Severidade(Enum):
    AVISO = "aviso"
    REVISAO = "revisao"

@dataclass(frozen=True)
class Motivo:
    codigo: str
    severidade: Severidade
    mensagem: str

@dataclass(frozen=True)
class Avaliacao:
    requer_revisao: bool
    motivos: tuple[Motivo, ...]

# Constantes centralizadas
LIMITE_CONFIANCA = 0.70
LIMITE_MUITOS_PROBLEMAS = 2
LIMITE_AMBIGUIDADES_AVISO = 1
LIMITE_AMBIGUIDADES_REVISAO = 2
MIN_PALAVRAS_RELATO = 6

# Matriz de negocio usando os Enums (Unica fonte de verdade)
EQUIPES_POR_CATEGORIA = {
    Categoria.SISTEMAS: {Equipe.SISTEMAS},
    Categoria.HARDWARE: {Equipe.CAMPO, Equipe.INFRA},
    Categoria.REDE: {Equipe.INFRA},
    Categoria.ACESSO: {Equipe.SEGURANCA},
    Categoria.OUTROS: {Equipe.MANUAL},
}

def regra_relato_curto(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    if len(relato.split()) < MIN_PALAVRAS_RELATO:
        return Motivo("RELATO_CURTO", Severidade.AVISO, "Relato curto. Recomendado atentar para a clareza do contexto.")
    return None

def regra_confianca_baixa(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    if resultado.confianca_autodeclarada < LIMITE_CONFIANCA:
        return Motivo("CONFIANCA_BAIXA", Severidade.REVISAO, "Modelo autodeclarou confianca baixa.")
    return None

def regra_fora_do_escopo(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    if resultado.fora_do_escopo:
        return Motivo("FORA_DO_ESCOPO", Severidade.REVISAO, "Chamado possivelmente fora do escopo de TI.")
    return None

def regra_informacoes_essenciais(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    qtd = len(resultado.informacoes_essenciais_faltantes)
    if qtd > 0:
        return Motivo("INFO_ESSENCIAL_FALTANTE", Severidade.REVISAO, f"Faltam {qtd} informacoes essenciais para triar.")
    return None

def regra_informacoes_complementares(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    qtd = len(resultado.informacoes_complementares)
    if qtd > 0:
        return Motivo("INFO_COMPLEMENTAR", Severidade.AVISO, f"Faltam {qtd} detalhes de atendimento para a equipe.")
    return None

def regra_ambiguidades(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    qtd = len(resultado.ambiguidades)
    if qtd >= LIMITE_AMBIGUIDADES_REVISAO:
        return Motivo("MUITAS_AMBIGUIDADES", Severidade.REVISAO, "Multiplas ambiguidades detectadas.")
    if qtd >= LIMITE_AMBIGUIDADES_AVISO:
        return Motivo("AMBIGUIDADE_DETECTADA", Severidade.AVISO, "Ha ambiguidade no relato original.")
    return None

def regra_muitos_problemas(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    if len(resultado.problemas) > LIMITE_MUITOS_PROBLEMAS:
        return Motivo("MUITOS_PROBLEMAS", Severidade.AVISO, f"Mais de {LIMITE_MUITOS_PROBLEMAS} problemas detectados simultaneamente.")
    return None

def regra_prioridade_critica(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    for p in resultado.problemas:
        if p.prioridade_sugerida.value == "Critica":
            return Motivo("PRIORIDADE_CRITICA", Severidade.REVISAO, "Prioridade critica requer validacao humana.")
    return None

def regra_categoria_incoerente(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    for p in resultado.problemas:
        equipes_validas = EQUIPES_POR_CATEGORIA.get(p.categoria, set())
        if p.equipe_destino not in equipes_validas:
            return Motivo("EQUIPE_INCOERENTE", Severidade.REVISAO, f"A equipe '{p.equipe_destino.value}' nao atende '{p.categoria.value}'.")
    return None

def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    sem_pontuacao = re.sub(r"[^\w\s]", " ", sem_acentos.casefold())
    return " ".join(sem_pontuacao.split())

def regra_trecho_nao_encontrado(resultado: ResultadoTriagem, relato: str) -> Optional[Motivo]:
    relato_norm = _normalizar(relato)
    for p in resultado.problemas:
        trecho_norm = _normalizar(p.trecho_do_relato)
        if trecho_norm not in relato_norm:
            return Motivo("TRECHO_INVENTADO", Severidade.REVISAO, "O modelo inventou justificativa que nao consta no texto.")
    return None

REGRAS = (
    regra_relato_curto,
    regra_confianca_baixa,
    regra_fora_do_escopo,
    regra_informacoes_essenciais,
    regra_informacoes_complementares,
    regra_ambiguidades,
    regra_muitos_problemas,
    regra_prioridade_critica,
    regra_categoria_incoerente,
    regra_trecho_nao_encontrado,
)

def avaliar(resultado: ResultadoTriagem, relato: str) -> Avaliacao:
    motivos = []
    for regra in REGRAS:
        try:
            motivo = regra(resultado, relato)
            if motivo:
                motivos.append(motivo)
        except Exception as e:
            motivos.append(Motivo("ERRO_NA_REGRA", Severidade.REVISAO, f"Falha ao executar {regra.__name__}: {e}"))
    
    requer = any(m.severidade == Severidade.REVISAO for m in motivos)
    return Avaliacao(requer_revisao=requer, motivos=tuple(motivos))