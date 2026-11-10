"""Schemas Pydantic: o contrato que a saida da IA precisa cumprir."""
from enum import Enum
from pydantic import BaseModel, Field

class Categoria(str, Enum):
    SISTEMAS = "Sistemas corporativos"
    HARDWARE = "Hardware e perifericos"
    REDE = "Rede e infraestrutura"
    ACESSO = "Acesso e contas"
    OUTROS = "Outros"

class Equipe(str, Enum):
    SISTEMAS = "Equipe de sistemas"
    CAMPO = "Suporte de campo"
    INFRA = "Infraestrutura"
    SEGURANCA = "Seguranca e acessos"
    MANUAL = "Triagem manual"

class Prioridade(str, Enum):
    BAIXA = "Baixa"
    MEDIA = "Media"
    ALTA = "Alta"
    CRITICA = "Critica"

class Problema(BaseModel):
    categoria: Categoria
    equipe_destino: Equipe
    prioridade_sugerida: Prioridade
    justificativa: str = Field(min_length=5, max_length=400)
    trecho_do_relato: str = Field(min_length=3, max_length=300)

class ResultadoTriagem(BaseModel):
    problemas: list[Problema] = Field(min_length=1, max_length=5)
    # Refatoração: divisão dos campos de informações faltantes
    informacoes_essenciais_faltantes: list[str] = Field(default_factory=list)
    informacoes_complementares: list[str] = Field(default_factory=list)
    ambiguidades: list[str] = Field(default_factory=list)
    confianca_autodeclarada: float = Field(ge=0.0, le=1.0)
    fora_do_escopo: bool = False