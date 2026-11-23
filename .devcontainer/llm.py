"""Cliente LLM sem dependências externas (só urllib).

- ollama: modelo local (defeito). Sem chave, sem internet, dados ficam na empresa.
- gemini: API opcional. ATENÇÃO à privacidade: ver README (tier gratuito usa os dados).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterator

from . import config


class LLMErro(Exception):
    pass


def _post(url: str, corpo: dict, cabecalhos: dict | None = None, timeout: int | None = None):
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", **(cabecalhos or {})}, method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout or config.LLM_TIMEOUT_S)
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "ignore")[:300]
        raise LLMErro(f"HTTP {e.code}: {detalhe}") from e
    except Exception as e:
        raise LLMErro(f"Não consegui contactar o modelo ({e})") from e


def estado() -> tuple[bool, str]:
    """Verifica se o fornecedor configurado está acessível. Para mostrar na barra lateral."""
    if config.LLM_PROVIDER == "ollama":
        try:
            with urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=4) as r:
                nomes = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        except Exception:
            return False, f"Ollama não responde em {config.OLLAMA_URL}"
        m = config.OLLAMA_MODEL
        if not any(n == m or (":" not in m and n.split(":")[0] == m) for n in nomes):
            return False, f"Modelo '{config.OLLAMA_MODEL}' não instalado (ollama pull {config.OLLAMA_MODEL})"
        return True, f"Local: {config.OLLAMA_MODEL}"
    if config.LLM_PROVIDER == "gemini":
        if not config.GEMINI_API_KEY:
            return False, "GEMINI_API_KEY em falta"
        return True, f"Gemini: {config.GEMINI_MODEL}"
    return False, f"LLM_PROVIDER desconhecido: {config.LLM_PROVIDER}"


def _ollama(mensagens: list[dict], stream: bool, max_tokens: int, temperatura: float) -> Iterator[str]:
    corpo = {
        "model": config.OLLAMA_MODEL, "messages": mensagens, "stream": True,
        "options": {"temperature": temperatura, "num_predict": max_tokens, "num_ctx": 8192},
    }
    with _post(config.OLLAMA_URL.rstrip("/") + "/api/chat", corpo) as resp:
        for linha in resp:
            if not linha.strip():
                continue
            d = json.loads(linha)
            if d.get("error"):
                raise LLMErro(d["error"])
            parte = d.get("message", {}).get("content", "")
            if parte:
                yield parte
            if d.get("done"):
                break


def _gemini(mensagens: list[dict], stream: bool, max_tokens: int, temperatura: float) -> Iterator[str]:
    if not config.GEMINI_API_KEY:
        raise LLMErro("GEMINI_API_KEY não definida.")
    sistema = "\n\n".join(m["content"] for m in mensagens if m["role"] == "system")
    conteudo = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in mensagens if m["role"] != "system"
    ]
    corpo = {
        "contents": conteudo,
        "generationConfig": {"temperature": temperatura, "maxOutputTokens": max_tokens},
    }
    if sistema:
        corpo["systemInstruction"] = {"parts": [{"text": sistema}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    with _post(url, corpo, {"x-goog-api-key": config.GEMINI_API_KEY}) as resp:
        d = json.loads(resp.read())
    try:
        partes = d["candidates"][0]["content"]["parts"]
        yield "".join(p.get("text", "") for p in partes)
    except (KeyError, IndexError) as e:
        raise LLMErro(f"Resposta inesperada do Gemini: {str(d)[:200]}") from e


def gerar_stream(mensagens: list[dict], max_tokens: int | None = None, temperatura: float = 0.1) -> Iterator[str]:
    mt = max_tokens or config.LLM_MAX_TOKENS
    if config.LLM_PROVIDER == "ollama":
        return _ollama(mensagens, True, mt, temperatura)
    if config.LLM_PROVIDER == "gemini":
        return _gemini(mensagens, False, mt, temperatura)
    raise LLMErro(f"LLM_PROVIDER desconhecido: {config.LLM_PROVIDER}")


def gerar(mensagens: list[dict], max_tokens: int | None = None, temperatura: float = 0.1) -> str:
    return "".join(gerar_stream(mensagens, max_tokens, temperatura)).strip()
