"""Histórico de conversa por utilizador e por manual (ficheiros separados, escrita atómica)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import auth, config

MAX_MENSAGENS = 200


def _caminho(utilizador: str, manual: str) -> Path:
    return config.PASTA_HISTORICO / f"{auth.nome_seguro(utilizador)}__{auth.nome_seguro(manual)}.json"


def carregar(utilizador: str, manual: str) -> list[dict]:
    f = _caminho(utilizador, manual)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def guardar(utilizador: str, manual: str, mensagens: list[dict]) -> None:
    f = _caminho(utilizador, manual)
    fd, tmp = tempfile.mkstemp(dir=f.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(mensagens[-MAX_MENSAGENS:], out, ensure_ascii=False)
        os.replace(tmp, f)        # atómico: nunca fica um ficheiro a meio
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apagar(utilizador: str, manual: str) -> None:
    f = _caminho(utilizador, manual)
    if f.exists():
        f.unlink()
