"""Autenticação por PIN + token de sessão assinado (HMAC) com expiração.

O token vai no URL (?t=...) só para sobreviver a F5. Não se pode forjar sem o
segredo guardado no servidor (data/.segredo_sessao), ao contrário do antigo
?autenticado=true&user=x.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from . import config

_FALHAS: dict[str, list[float]] = {}
MAX_FALHAS = 5
JANELA_S = 300


def _segredo() -> bytes:
    f = config.FICHEIRO_SEGREDO_SESSAO
    if not f.exists():
        f.write_bytes(secrets.token_bytes(32))
        try:
            f.chmod(0o600)
        except Exception:
            pass
    return f.read_bytes()


def _assinar(payload: str) -> str:
    return hmac.new(_segredo(), payload.encode(), hashlib.sha256).hexdigest()


def criar_token(utilizador: str, agora: float | None = None) -> str:
    agora = agora or time.time()
    expira = int(agora + config.SESSAO_HORAS * 3600)
    u64 = base64.urlsafe_b64encode(utilizador.encode()).decode().rstrip("=")
    payload = f"{u64}.{expira}"
    return f"{payload}.{_assinar(payload)}"


def validar_token(token: str, agora: float | None = None) -> str | None:
    """Devolve o nome do utilizador se o token for válido e não expirado."""
    try:
        u64, expira, assinatura = token.split(".")
        payload = f"{u64}.{expira}"
        if not hmac.compare_digest(assinatura, _assinar(payload)):
            return None
        if int(expira) < (agora or time.time()):
            return None
        pad = "=" * (-len(u64) % 4)
        return base64.urlsafe_b64decode(u64 + pad).decode()
    except Exception:
        return None


def verificar_login(utilizador: str, pin: str, agora: float | None = None) -> tuple[bool, str]:
    """(ok, mensagem). Limita tentativas por utilizador."""
    agora = agora or time.time()
    chave = utilizador.strip().lower()
    recentes = [t for t in _FALHAS.get(chave, []) if agora - t < JANELA_S]
    if len(recentes) >= MAX_FALHAS:
        return False, "Demasiadas tentativas. Aguarde alguns minutos."
    if not utilizador.strip():
        return False, "Indique o seu nome."
    if config.LISTA_TECNICOS and utilizador.strip() not in config.LISTA_TECNICOS:
        return False, "Utilizador não autorizado."
    if not hmac.compare_digest(pin.strip().encode(), config.pin_acesso().encode()):
        recentes.append(agora)
        _FALHAS[chave] = recentes
        return False, "PIN incorreto."
    _FALHAS.pop(chave, None)
    return True, "ok"


def nome_seguro(utilizador: str) -> str:
    """Para usar em nomes de ficheiro."""
    return "".join(c if c.isalnum() else "_" for c in utilizador.strip())[:40] or "anon"
