"""Configuração central. Lê, por esta ordem: variáveis de ambiente, .streamlit/secrets.toml.

Nada de segredos no código. Se faltar um segredo obrigatório, a app recusa arrancar.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

RAIZ = Path(os.environ.get("MGC_RAIZ", Path(__file__).resolve().parent.parent))
PASTA_MANUAIS = RAIZ / "manuais"
PASTA_DADOS = RAIZ / "data"
PASTA_CACHE = PASTA_DADOS / "cache"
PASTA_HISTORICO = PASTA_DADOS / "historico"
FICHEIRO_FEEDBACK_DB = PASTA_DADOS / "feedback.sqlite3"
FICHEIRO_SEGREDO_SESSAO = PASTA_DADOS / ".segredo_sessao"
FICHEIRO_SECRETS = RAIZ / ".streamlit" / "secrets.toml"

for _p in (PASTA_MANUAIS, PASTA_DADOS, PASTA_CACHE, PASTA_HISTORICO):
    _p.mkdir(parents=True, exist_ok=True)


def _ler_secrets() -> dict:
    if tomllib is None or not FICHEIRO_SECRETS.exists():
        return {}
    try:
        with open(FICHEIRO_SECRETS, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


_SECRETS = _ler_secrets()


def obter(nome: str, defeito: str = "") -> str:
    """Variável de ambiente > secrets.toml local > st.secrets (Streamlit Cloud) > defeito."""
    valor = os.environ.get(nome)
    if valor is None:
        valor = _SECRETS.get(nome)
    if valor is None:
        try:
            import streamlit as st
            valor = st.secrets.get(nome)
        except Exception:
            valor = None
    if valor is None:
        valor = defeito
    return str(valor).strip()


# --- Acesso ---------------------------------------------------------------
def pin_acesso() -> str:
    """PIN partilhado. Obrigatório: não existe valor por defeito."""
    pin = obter("PIN_ACESSO")
    if not pin:
        raise RuntimeError(
            "PIN_ACESSO não definido. Crie .streamlit/secrets.toml com PIN_ACESSO = \"...\" "
            "(ver secrets.toml.exemplo)."
        )
    return pin


SESSAO_HORAS = int(obter("SESSAO_HORAS", "12"))
LISTA_TECNICOS = [n.strip() for n in obter("TECNICOS", "").split(",") if n.strip()]  # vazio = nome livre

# --- LLM ------------------------------------------------------------------
# "ollama" (local, sem API, por defeito) ou "gemini" (API externa, opcional)
LLM_PROVIDER = obter("LLM_PROVIDER", "ollama").lower()
OLLAMA_URL = obter("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = obter("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_API_KEY = obter("GEMINI_API_KEY")
GEMINI_MODEL = obter("GEMINI_MODEL", "gemini-2.5-flash")
LLM_TIMEOUT_S = int(obter("LLM_TIMEOUT_S", "180"))
LLM_MAX_TOKENS = int(obter("LLM_MAX_TOKENS", "1400"))

# --- Pesquisa -------------------------------------------------------------
CHUNK_PALAVRAS = int(obter("CHUNK_PALAVRAS", "220"))
CHUNK_SOBREPOSICAO = int(obter("CHUNK_SOBREPOSICAO", "40"))
TOP_CHUNKS_MANUAL = int(obter("TOP_CHUNKS_MANUAL", "5"))
TOP_CASOS = int(obter("TOP_CASOS", "5"))

# --- Visualização ---------------------------------------------------------
ZOOM_RENDER = float(obter("ZOOM_RENDER", "3.0"))
