"""Assistente MGC - FICHEIRO UNICO (app + modulos). Basta este app.py e o requirements.txt no GitHub."""
from __future__ import annotations

import sys as _sys
import types as _types
from pathlib import Path as _Path

# ======================= MODULOS EMBUTIDOS (nao e preciso criar a pasta core) =======================
_FONTES = {}

# ----------------------- core/config.py -----------------------
_FONTES['config'] = r'''
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
GEMINI_MODEL = obter("GEMINI_MODEL", "gemini-3.8-flash")
# modo "Rápido" da app: modelo mais leve (responde mais depressa; compare a exatidão no modo Qualidade)
GEMINI_MODEL_RAPIDO = obter("GEMINI_MODEL_RAPIDO", "gemini-3.5-flash-lite")
# modelos de reserva, usados por ordem se o principal estiver sobrecarregado (erro 503/429)
GEMINI_FALLBACKS = [m.strip() for m in obter("GEMINI_FALLBACKS", "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-2.5-flash").split(",") if m.strip()]
# esforço de "pensar" do Gemini: minimal/low/medium/high ("" = não enviar). low = bem mais rápido.
GEMINI_THINKING = obter("GEMINI_THINKING", "low").lower()
LLM_TIMEOUT_S = int(obter("LLM_TIMEOUT_S", "180"))
LLM_MAX_TOKENS = int(obter("LLM_MAX_TOKENS", "1400"))

# --- Embeddings (pesquisa por significado, só com Gemini) ---------------------
EMBED_MODEL = obter("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(obter("EMBED_DIM", "768"))
EMBED_LOTE = int(obter("EMBED_LOTE", "50"))

# --- Pesquisa -------------------------------------------------------------
CHUNK_PALAVRAS = int(obter("CHUNK_PALAVRAS", "220"))
CHUNK_SOBREPOSICAO = int(obter("CHUNK_SOBREPOSICAO", "40"))
TOP_CHUNKS_MANUAL = int(obter("TOP_CHUNKS_MANUAL", "5"))
TOP_CASOS = int(obter("TOP_CASOS", "5"))

# --- Visualização ---------------------------------------------------------
ZOOM_RENDER = float(obter("ZOOM_RENDER", "3.0"))
'''

# ----------------------- core/textutil.py -----------------------
_FONTES['textutil'] = r'''
"""Utilitários de texto: normalização, tokenização, glossário técnico PT <-> EN/DE."""
from __future__ import annotations

import re
import unicodedata

_STOP = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "um", "uma", "em", "no", "na", "nos", "nas",
    "que", "com", "para", "por", "se", "ao", "mas", "ja", "já", "esta", "está", "tem", "foi", "ser",
    "the", "of", "and", "to", "in", "is", "for", "on", "with", "der", "die", "das", "und", "den", "zu",
}


def sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sem acentos, preserva códigos tipo -999, E-102, 4-20ma, X1.3."""
    t = sem_acentos(texto.lower())
    t = re.sub(r"[^\w\-\.\s]", " ", t)
    toks = []
    for tok in t.split():
        tok = tok.strip(".-_") if not re.fullmatch(r"-\d+", tok) else tok
        if not tok or tok in _STOP:
            continue
        toks.append(tok)
        # também indexa as partes de tokens compostos (x1.3 -> x1, 3 ; e-102 -> e, 102)
        partes = [p for p in re.split(r"[\-\.]", tok) if len(p) >= 2 and p != tok]
        toks.extend(partes)
    return toks


def codigos_numericos(texto: str) -> list[str]:
    """Números de 3+ dígitos (códigos de erro, endereços). Evita '1', '24', etc."""
    return re.findall(r"(?<![\w.])-?\d{3,}(?![\w.])", texto)


# Glossário mínimo para ponte de idiomas na pesquisa (PT -> EN/DE). Expandir conforme os manuais.
GLOSSARIO = {
    "borne": ["terminal", "klemme"],
    "bornes": ["terminals", "klemmen"],
    "malha": ["shield", "schirm"],
    "disjuntor": ["breaker", "circuit breaker", "leistungsschalter"],
    "rele": ["relay", "relais"],
    "contactor": ["contactor", "schutz"],
    "fusivel": ["fuse", "sicherung"],
    "sonda": ["probe", "sensor", "fuehler"],
    "temperatura": ["temperature", "temperatur"],
    "pressao": ["pressure", "druck"],
    "motor": ["motor", "drive"],
    "variador": ["inverter", "drive", "frequenzumrichter"],
    "alimentacao": ["supply", "power supply", "versorgung"],
    "fonte": ["power supply", "netzteil"],
    "tensao": ["voltage", "spannung"],
    "corrente": ["current", "strom"],
    "cartao": ["card", "module", "karte", "baugruppe"],
    "analogico": ["analog", "analogue"],
    "entrada": ["input", "eingang"],
    "saida": ["output", "ausgang"],
    "paragem": ["stop", "emergency", "halt"],
    "emergencia": ["emergency", "not-aus", "e-stop"],
    "seguranca": ["safety", "sicherheit"],
    "falha": ["fault", "failure", "error", "stoerung"],
    "erro": ["error", "fault", "fehler"],
    "alarme": ["alarm", "alarm"],
    "cabo": ["cable", "kabel"],
    "esquema": ["diagram", "schematic", "schaltplan"],
    "lista": ["list", "liste"],
    "agulha": ["needle", "nadel"],
    "fio": ["thread", "yarn", "wire", "faden"],
    "tear": ["loom", "knitting machine", "webmaschine", "strickmaschine"],
    "sensor": ["sensor", "sensor"],
    "encoder": ["encoder", "geber"],
    "ventilador": ["fan", "luefter"],
    "bomba": ["pump", "pumpe"],
    "comunicacao": ["communication", "kommunikation"],
    "profibus": ["profibus"],
    "reset": ["reset", "ruecksetzen"],
}


GLOSSARIO.update({
    "malha": ["shield", "schirm", "knit", "masche"],
    "contador": ["counter", "zaehler"],
    "contagem": ["count", "counter", "zaehlung"],
    "vapor": ["steam", "dampf"],
    "caldeira": ["boiler", "kessel"],
    "queimador": ["burner", "brenner"],
    "zerado": ["zero", "null"],
    "zero": ["zero", "null"],
    "nivel": ["level", "niveau", "fuellstand"],
    "valvula": ["valve", "ventil"],
    "caudal": ["flow", "durchfluss"],
    "leitura": ["reading", "value", "wert"],
    "sinal": ["signal", "signal"],
    "interruptor": ["switch", "schalter"],
    "botao": ["button", "pushbutton", "taster"],
    "aquecimento": ["heating", "heater", "heizung"],
    "resistencia": ["resistor", "heater", "widerstand"],
    "fuso": ["spindle", "spindel"],
    "cilindro": ["cylinder", "zylinder"],
    "parado": ["stopped", "stop", "stillstand"],
    "tampa": ["cover", "door", "abdeckung"],
    "porta": ["door", "port", "tuer"],
    "rede": ["network", "netzwerk"],
    "ligacao": ["connection", "wiring", "verbindung"],
    "cablagem": ["wiring", "verdrahtung"],
    "terra": ["earth", "ground", "erde"],
    "contactos": ["contacts", "kontakte"],
    "bobina": ["coil", "spule"],
    "pressostato": ["pressure switch", "druckschalter"],
    "termostato": ["thermostat", "thermostat"],
})


def palavras_chave(texto: str, max_n: int = 8) -> tuple[list[str], list[str]]:
    """(palavras da pergunta, termos equivalentes do glossário) para mostrar ao técnico o que se procurou."""
    vistos, base = set(), []
    for w in re.findall(r"[\wÀ-ÿ\-\.]+", texto.lower()):
        w = w.strip(".-_")
        k = sem_acentos(w)
        if not w or k in _STOP or k in vistos or (len(k) < 3 and not any(c.isdigit() for c in k)):
            continue
        vistos.add(k)
        base.append(w)
    extra: list[str] = []
    for w in base:
        for e in GLOSSARIO.get(sem_acentos(w), [])[:2]:
            if e not in extra and e not in base:
                extra.append(e)
    return base[:max_n], extra[:max_n]


def expandir_com_glossario(texto: str, limite: int = 12) -> list[str]:
    extra: list[str] = []
    for tok in tokenizar(texto):
        if tok in GLOSSARIO:
            for e in GLOSSARIO[tok]:
                extra.extend(tokenizar(e))
    return extra[:limite * 3]


_PALAVRAS_IDIOMA = {
    "pt": {"de", "do", "da", "que", "para", "com", "nao", "uma", "os", "as", "em", "por", "ao", "se"},
    "en": {"the", "and", "of", "to", "is", "for", "with", "on", "not", "check", "connect", "must"},
    "de": {"der", "die", "und", "nicht", "ist", "mit", "fuer", "von", "den", "das", "ein", "zu"},
    "es": {"el", "los", "las", "con", "para", "por", "una", "del", "que", "no"},
    "it": {"il", "della", "con", "per", "non", "una", "che", "di", "sono"},
    "fr": {"le", "les", "des", "est", "pour", "avec", "une", "pas", "de", "du"},
}


def detetar_idioma(texto: str) -> str:
    """Heurística offline por stopwords. Devolve pt/en/de/es/it/fr (defeito pt)."""
    palavras = re.findall(r"[a-z]+", sem_acentos(texto.lower()))
    if len(palavras) < 20:
        return "pt"
    pontos = {l: sum(1 for p in palavras if p in conj) for l, conj in _PALAVRAS_IDIOMA.items()}
    melhor = max(pontos, key=pontos.get)
    return melhor if pontos[melhor] > 0 else "pt"
'''

# ----------------------- core/auth.py -----------------------
_FONTES['auth'] = r'''
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
'''

# ----------------------- core/search.py -----------------------
_FONTES['search'] = r'''
"""Pesquisa BM25 em Python puro (sem dependências), sobre chunks com metadados."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import textutil


@dataclass
class Chunk:
    texto: str
    meta: dict = field(default_factory=dict)  # ex.: {"pagina": 12} ou {"os": "1234", "data": ...}


class BM25:
    def __init__(self, textos_tokenizados: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(textos_tokenizados)
        self.tf = [Counter(d) for d in textos_tokenizados]
        self.dl = [len(d) for d in textos_tokenizados]
        self.avgdl = (sum(self.dl) / self.N) if self.N else 0.0
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, consulta: list[str]) -> list[float]:
        out = [0.0] * self.N
        if not self.N:
            return out
        for t in set(consulta):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                out[i] += idf * f * (self.k1 + 1) / denom
        return out


class Indice:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25([textutil.tokenizar(c.texto) for c in chunks])

    def procurar(self, consulta: str, k: int = 5, usar_glossario: bool = True,
                 bonus_codigos: float = 3.0, filtro=None) -> list[tuple[Chunk, float]]:
        toks = textutil.tokenizar(consulta)
        if usar_glossario:
            toks = toks + textutil.expandir_com_glossario(consulta)
        sc = self.bm25.scores(toks)

        # Códigos exatos (3+ dígitos) com limites de palavra: reforço forte
        for cod in textutil.codigos_numericos(consulta):
            padrao = re.compile(r"(?<![\w.])" + re.escape(cod) + r"(?![\w.])")
            for i, c in enumerate(self.chunks):
                if padrao.search(c.texto):
                    sc[i] += bonus_codigos

        ordem = sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)
        res = []
        for i in ordem:
            if sc[i] <= 0:
                break
            if filtro and not filtro(self.chunks[i]):
                continue
            res.append((self.chunks[i], sc[i]))
            if len(res) >= k:
                break
        return res


def dividir_em_chunks(texto: str, palavras: int = 220, sobreposicao: int = 40) -> list[str]:
    """Chunks por janelas de palavras com sobreposição; respeita linhas curtas (esquemas)."""
    ps = texto.split()
    if len(ps) <= palavras:
        return [texto.strip()] if texto.strip() else []
    passo = max(1, palavras - sobreposicao)
    return [" ".join(ps[i:i + palavras]) for i in range(0, len(ps), passo)
            if ps[i:i + palavras]]


def reescrever_consulta_simples(historico: list[dict], pergunta: str, n: int = 3) -> str:
    """Fallback sem LLM: junta as últimas perguntas do técnico, para 'e agora?' ter contexto."""
    anteriores = [m["content"] for m in historico if m.get("role") == "user"][-n:]
    return " ".join(anteriores + [pergunta])
'''

# ----------------------- core/llm.py -----------------------
_FONTES['llm'] = r'''
"""Cliente LLM sem dependências externas (só urllib).

- ollama: modelo local (defeito). Sem chave, sem internet, dados ficam na empresa.
- gemini: API opcional. ATENÇÃO à privacidade: ver README (tier gratuito usa os dados).
"""
from __future__ import annotations

import base64
import json
import threading
import time
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
        "model": config.OLLAMA_MODEL, "stream": True,
        "messages": [{"role": m["role"], "content": m["content"]} for m in mensagens],
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


def _partes_gemini(m: dict) -> list[dict]:
    """Texto + imagens opcionais (m['imagens'] = [(mime, bytes), ...]), imagens primeiro."""
    partes = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(dados).decode("ascii")}}
              for mime, dados in (m.get("imagens") or [])]
    partes.append({"text": m["content"]})
    return partes


_LOCAL = threading.local()   # info da última chamada (modelo usado, falhas) para mostrar na app


def ultimo_info() -> dict | None:
    return getattr(_LOCAL, "info", None)


_TRANSITORIOS = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "Não consegui contactar")


def _gemini(mensagens: list[dict], stream: bool, max_tokens: int, temperatura: float,
            modelo_pedido: str | None = None) -> Iterator[str]:
    """Gemini em streaming (o texto aparece à medida que é gerado), com novas tentativas (1s, 2s),
    modelos de reserva em caso de sobrecarga (503/429) e 'pensar' reduzido para responder mais depressa."""
    if not config.GEMINI_API_KEY:
        raise LLMErro("GEMINI_API_KEY não definida.")
    sistema = "\n\n".join(m["content"] for m in mensagens if m["role"] == "system")
    conteudo = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": _partes_gemini(m)}
        for m in mensagens if m["role"] != "system"
    ]
    cfg = {"temperature": temperatura, "maxOutputTokens": max(max_tokens, 4096)}
    if config.GEMINI_THINKING:
        cfg["thinkingConfig"] = {"thinkingLevel": config.GEMINI_THINKING}
    corpo = {"contents": conteudo, "generationConfig": cfg}
    if sistema:
        corpo["systemInstruction"] = {"parts": [{"text": sistema}]}

    # o modelo pedido primeiro; se estiver sobrecarregado, o principal e depois as reservas
    modelos = list(dict.fromkeys([modelo_pedido or config.GEMINI_MODEL, config.GEMINI_MODEL] + list(config.GEMINI_FALLBACKS)))
    ultimo: Exception | None = None
    falhas = 0
    _LOCAL.info = None
    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:streamGenerateContent?alt=sse"
        for tentativa in range(3):
            emitido = False
            try:
                with _post(url, corpo, {"x-goog-api-key": config.GEMINI_API_KEY}) as resp:
                    for linha in resp:
                        linha = linha.decode("utf-8", "ignore").strip()
                        if not linha.startswith("data:"):
                            continue
                        dados = linha[5:].strip()
                        if not dados or dados == "[DONE]":
                            continue
                        for parte in json.loads(dados).get("candidates", [{}])[0].get("content", {}).get("parts", []):
                            t = parte.get("text", "")
                            if t and not parte.get("thought"):
                                if not emitido:
                                    _LOCAL.info = {"modelo": modelo, "falhas": falhas}
                                emitido = True
                                yield t
                if emitido:
                    return
                ultimo = LLMErro(f"{modelo}: resposta vazia")
                break                                   # tenta o modelo seguinte
            except (KeyError, IndexError, TypeError, ValueError):
                if emitido:
                    raise LLMErro("Resposta interrompida a meio. Tente de novo.")
                ultimo = LLMErro(f"{modelo}: resposta inesperada")
                break
            except LLMErro as e:
                if emitido:
                    raise LLMErro(f"Resposta interrompida a meio ({str(e)[:120]}). Tente de novo.")
                ultimo = e
                falhas += 1
                msg = str(e)
                if "HTTP 400" in msg and "thinking" in msg.lower() and "thinkingConfig" in corpo["generationConfig"]:
                    del corpo["generationConfig"]["thinkingConfig"]   # este modelo não aceita: repete sem isso
                    continue
                if any(t in msg for t in _TRANSITORIOS):
                    if tentativa < 2:
                        time.sleep(1 + tentativa)       # 1s, depois 2s
                    continue
                if "HTTP 404" in msg:                   # modelo inexistente: tenta o seguinte
                    break
                raise                                   # chave inválida (400/401/403), etc.
    raise LLMErro(f"Gemini indisponível (tentei {', '.join(modelos)}). Último erro: {str(ultimo)[:200]}")


def gerar_stream(mensagens: list[dict], max_tokens: int | None = None, temperatura: float = 0.1,
                 modelo: str | None = None) -> Iterator[str]:
    mt = max_tokens or config.LLM_MAX_TOKENS
    if config.LLM_PROVIDER == "ollama":
        return _ollama(mensagens, True, mt, temperatura)
    if config.LLM_PROVIDER == "gemini":
        return _gemini(mensagens, False, mt, temperatura, modelo)
    raise LLMErro(f"LLM_PROVIDER desconhecido: {config.LLM_PROVIDER}")


def gerar(mensagens: list[dict], max_tokens: int | None = None, temperatura: float = 0.1,
          modelo: str | None = None) -> str:
    return "".join(gerar_stream(mensagens, max_tokens, temperatura, modelo)).strip()
'''

# ----------------------- core/embeddings.py -----------------------
_FONTES['embeddings'] = r'''
"""Pesquisa por significado (embeddings do Gemini) combinada com BM25.

Os vetores de cada manual calculam-se UMA vez e ficam em data/cache. Se a API falhar, a pesquisa
continua só com BM25 (palavras). A fusão (Reciprocal Rank Fusion) junta as duas listas sem afinar pesos.
O modelo é multilingue: uma pergunta em português encontra texto de manuais em inglês ou alemão.
"""
from __future__ import annotations

import hashlib
import json
import time

from . import config
from .llm import LLMErro, _post
from .search import Indice


class EmbErro(Exception):
    pass


# Lembra o que a API aceita (muda só se a API recusar): campos no topo ou em embedContentConfig; com/sem dimensão.
_ESTADO = {"forma": "topo", "usar_dim": True}
_TRANSITORIOS = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "Não consegui contactar")


def _url(metodo: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{config.EMBED_MODEL}:{metodo}"


def _req(texto: str, tarefa: str, forma: str, dim: int | None) -> dict:
    r = {"model": f"models/{config.EMBED_MODEL}", "content": {"parts": [{"text": texto}]}}
    if forma == "config":
        cfg = {"taskType": tarefa}
        if dim:
            cfg["outputDimensionality"] = dim
        r["embedContentConfig"] = cfg
    else:
        r["taskType"] = tarefa
        if dim:
            r["outputDimensionality"] = dim
    return r


def _chamar(metodo: str, montar) -> dict:
    if not config.GEMINI_API_KEY:
        raise EmbErro("GEMINI_API_KEY em falta")
    ultimo = None
    for tent in range(6):
        corpo = montar(_ESTADO["forma"], config.EMBED_DIM if _ESTADO["usar_dim"] else None)
        try:
            with _post(_url(metodo), corpo, {"x-goog-api-key": config.GEMINI_API_KEY}, timeout=60) as r:
                return json.loads(r.read())
        except LLMErro as e:
            ultimo, msg = e, str(e)
            if "HTTP 400" in msg:
                if _ESTADO["usar_dim"] and "dimensionality" in msg.lower().replace("_", ""):
                    _ESTADO["usar_dim"] = False
                    continue
                if _ESTADO["forma"] == "topo":
                    _ESTADO["forma"] = "config"
                    continue
                raise EmbErro(msg)
            if any(t in msg for t in _TRANSITORIOS):
                time.sleep(min(2 ** tent, 20))
                continue
            raise EmbErro(msg)
    raise EmbErro(f"Embeddings indisponíveis: {str(ultimo)[:200]}")


def embed_textos(textos: list[str], tarefa: str = "RETRIEVAL_DOCUMENT", progresso=None) -> list[list[float]]:
    saida: list[list[float]] = []
    for i in range(0, len(textos), config.EMBED_LOTE):
        lote = textos[i:i + config.EMBED_LOTE]
        d = _chamar("batchEmbedContents",
                    lambda forma, dim: {"requests": [_req(t, tarefa, forma, dim) for t in lote]})
        embs = d.get("embeddings") or []
        if len(embs) != len(lote):
            raise EmbErro("resposta de embeddings incompleta")
        saida.extend(e["values"] for e in embs)
        if progresso:
            progresso(len(saida), len(textos))
    return saida


def embed_consulta(texto: str) -> list[float]:
    d = _chamar("embedContent", lambda forma, dim: _req(texto, "RETRIEVAL_QUERY", forma, dim))
    return d["embedding"]["values"]


def _normalizar(m):
    import numpy as np
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (m / n).astype("float32")


def obter_matriz(hash_manual: str, chunks, progresso=None):
    """Matriz (n_chunks x dim) normalizada. Usa cache em disco; só chama a API da primeira vez."""
    import numpy as np
    chave = hashlib.sha1(
        f"{hash_manual}|{config.EMBED_MODEL}|{config.EMBED_DIM}|{config.CHUNK_PALAVRAS}|"
        f"{config.CHUNK_SOBREPOSICAO}|{len(chunks)}".encode()).hexdigest()
    ficheiro = config.PASTA_CACHE / f"emb_{chave}.npy"
    if ficheiro.exists():
        try:
            m = np.load(ficheiro)
            if m.shape[0] == len(chunks):
                return m
        except Exception:
            pass
    vetores = embed_textos([c.texto for c in chunks], "RETRIEVAL_DOCUMENT", progresso)
    m = _normalizar(np.array(vetores, dtype="float32"))
    np.save(ficheiro, m)
    return m


class IndiceHibrido(Indice):
    """BM25 + embeddings. Sem matriz (ou com semantica=False, ou se a API falhar) = só BM25."""

    def __init__(self, chunks):
        super().__init__(chunks)
        self.matriz = None
        self.ultimo_erro: str | None = None
        self._pos = {id(c): i for i, c in enumerate(chunks)}

    def procurar(self, consulta, k=5, usar_glossario=True, bonus_codigos=3.0, filtro=None, semantica=True):
        n = max(k * 4, 20)
        lex = super().procurar(consulta, k=n, usar_glossario=usar_glossario,
                               bonus_codigos=bonus_codigos, filtro=filtro)
        if not semantica or self.matriz is None:
            return lex[:k]
        try:
            import numpy as np
            q = np.array(embed_consulta(consulta), dtype="float32")
            if q.shape[0] != self.matriz.shape[1]:
                raise EmbErro("dimensões diferentes")
            q = q / (np.linalg.norm(q) or 1.0)
            sims = self.matriz @ q
            ordem = [int(i) for i in np.argsort(-sims)[:n]]
        except Exception as e:                       # qualquer falha: continua só com palavras
            self.ultimo_erro = str(e)[:200]
            return lex[:k]
        pontos: dict[int, float] = {}
        for r, (c, _) in enumerate(lex):
            i = self._pos[id(c)]
            pontos[i] = pontos.get(i, 0.0) + 1.0 / (60 + r)
        rank = 0
        for i in ordem:
            if filtro and not filtro(self.chunks[i]):
                continue
            pontos[i] = pontos.get(i, 0.0) + 1.0 / (60 + rank)
            rank += 1
        top = sorted(pontos.items(), key=lambda x: x[1], reverse=True)[:k]
        return [(self.chunks[i], s) for i, s in top]
'''

# ----------------------- core/casos.py -----------------------
_FONTES['casos'] = r'''
"""Base de casos de avarias: histórico importado (Excel) + casos validados pelos técnicos."""
from __future__ import annotations

from dataclasses import dataclass, field

from .search import Chunk, Indice


@dataclass
class Caso:
    id: str                # etiqueta usada nas citações: "OT 123", "FB7", "H12"
    origem: str            # "Histórico" (importado) ou "Feedback" (validado por técnico)
    data: str = ""
    equipamento: str = ""
    avaria: str = ""
    causa: str = ""
    solucao: str = ""
    tempo: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def texto(self) -> str:
        return " ".join([self.equipamento, self.avaria, self.causa, self.solucao])


class BaseCasos:
    def __init__(self, casos: list[Caso]):
        self.casos = casos
        self.indice = Indice([Chunk(c.texto, {"idx": i}) for i, c in enumerate(casos)])

    def equipamentos(self) -> list[str]:
        return sorted({c.equipamento for c in self.casos if c.equipamento})

    def procurar(self, consulta: str, equipamento: str | None = None, k: int = 5) -> list[tuple[Caso, float]]:
        if not self.casos:
            return []
        res = []
        for ch, sc in self.indice.procurar(consulta, k=k * 4):
            caso = self.casos[ch.meta["idx"]]
            if equipamento and equipamento.lower() in caso.equipamento.lower():
                sc *= 1.5
            if caso.origem == "Feedback":      # confirmado por um técnico
                sc *= 1.25
            res.append((caso, sc))
        res.sort(key=lambda x: x[1], reverse=True)
        return res[:k]
'''

# ----------------------- core/feedback.py -----------------------
_FONTES['feedback'] = r'''
"""Registo de feedback "resolveu / não resolveu" em SQLite (um ficheiro, sem servidor).

Os casos marcados como "resolveu" com solução real alimentam a pesquisa como casos validados.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from contextlib import contextmanager

from . import config
from .casos import Caso

RESULTADOS = ("resolveu", "parcial", "nao_resolveu")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    utilizador TEXT NOT NULL,
    manual TEXT,
    equipamento TEXT,
    pergunta TEXT,
    resposta TEXT,
    paginas TEXT,
    casos_usados TEXT,
    resultado TEXT,
    causa_real TEXT,
    solucao_real TEXT,
    nota TEXT
);
CREATE TABLE IF NOT EXISTS casos_importados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, origem TEXT, ref TEXT, data TEXT, equipamento TEXT,
    avaria TEXT, causa TEXT, solucao TEXT, tempo TEXT,
    chave TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS testes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual TEXT, equipamento TEXT, sintoma TEXT, causa_real TEXT,
    pagina_esperada INTEGER, palavras TEXT
);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, manual TEXT, modo TEXT, n INTEGER, hit REAL, mrr REAL, extra TEXT
);
"""


@contextmanager
def _ligar():
    con = sqlite3.connect(config.FICHEIRO_FEEDBACK_DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


ligar = _ligar


def registar_resposta(utilizador, manual, equipamento, pergunta, resposta, paginas, casos_usados) -> int:
    """Guarda cada resposta dada (resultado vazio até o técnico avaliar). Devolve o id."""
    with _ligar() as con:
        cur = con.execute(
            "INSERT INTO feedback (ts, utilizador, manual, equipamento, pergunta, resposta, paginas, casos_usados)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), utilizador, manual, equipamento or "", pergunta, resposta,
             json.dumps(list(paginas)), json.dumps(list(casos_usados))),
        )
        return cur.lastrowid


def avaliar(id_: int, resultado: str, causa_real: str = "", solucao_real: str = "", nota: str = "") -> None:
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado inválido: {resultado}")
    with _ligar() as con:
        con.execute(
            "UPDATE feedback SET resultado=?, causa_real=?, solucao_real=?, nota=? WHERE id=?",
            (resultado, causa_real.strip(), solucao_real.strip(), nota.strip(), id_),
        )


def obter(id_: int) -> dict | None:
    with _ligar() as con:
        r = con.execute("SELECT * FROM feedback WHERE id=?", (id_,)).fetchone()
        return dict(r) if r else None


def casos_validados() -> list[Caso]:
    """Casos 'resolveu' com solução escrita pelo técnico -> entram na pesquisa."""
    with _ligar() as con:
        linhas = con.execute(
            "SELECT * FROM feedback WHERE resultado='resolveu' AND TRIM(COALESCE(solucao_real,''))<>''"
        ).fetchall()
    return [
        Caso(id=f"FB{r['id']}", origem="Feedback", data=r["ts"][:10], equipamento=r["equipamento"] or "",
             avaria=r["pergunta"] or "", causa=r["causa_real"] or "", solucao=r["solucao_real"])
        for r in linhas
    ]


def estatisticas() -> dict:
    with _ligar() as con:
        tot = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        por = {r[0] or "sem avaliação": r[1] for r in
               con.execute("SELECT resultado, COUNT(*) FROM feedback GROUP BY resultado")}
    return {"total": tot, "por_resultado": por}


def exportar_csv() -> str:
    with _ligar() as con:
        linhas = con.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    buf = io.StringIO()
    if linhas:
        w = csv.DictWriter(buf, fieldnames=linhas[0].keys())
        w.writeheader()
        for r in linhas:
            w.writerow(dict(r))
    return buf.getvalue()
'''

# ----------------------- core/importar.py -----------------------
_FONTES['importar'] = r'''
"""Importação de avarias antigas (Excel/CSV do Manwinwin ou folha própria) para a base de casos.

Só LÊ o ficheiro carregado e guarda uma cópia em SQLite. Não liga ao Manwinwin.
"""
from __future__ import annotations

import hashlib
import io
import re
import time

from . import textutil
from .casos import Caso
from .feedback import ligar

CAMPOS = [
    ("avaria", "Descrição da avaria *"),
    ("solucao", "Solução / trabalho realizado"),
    ("causa", "Causa"),
    ("equipamento", "Equipamento / máquina"),
    ("id", "Nº da ordem (OT)"),
    ("data", "Data"),
    ("tempo", "Tempo de paragem"),
]

ALIASES = {
    "id": ["n ot", "n o ot", "no ot", "numero ot", "ordem", "n ordem", "numero", "codigo", "ot", "id"],
    "data": ["data fim", "data conclusao", "data inicio", "data abertura", "data"],
    "equipamento": ["designacao equipamento", "equipamento", "maquina", "ativo", "cod equipamento"],
    "avaria": ["descricao avaria", "descricao do problema", "avaria", "problema", "sintoma", "pedido", "descricao"],
    "causa": ["causa raiz", "causa avaria", "causa"],
    "solucao": ["trabalho realizado", "descricao intervencao", "intervencao", "solucao",
                "acao corretiva", "accao", "observacoes", "resolucao"],
    "tempo": ["tempo paragem", "horas paragem", "duracao", "tempo"],
}


def _norm_cab(c) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", textutil.sem_acentos(str(c).lower())).strip()


def mapear_colunas(colunas) -> dict[str, str]:
    """campo -> nome real da coluna (exata primeiro, depois 'contém')."""
    colunas = [str(c) for c in colunas]
    norm = {c: _norm_cab(c) for c in colunas}
    mapa: dict[str, str] = {}
    usadas: set[str] = set()
    for campo, aliases in ALIASES.items():
        escolha = None
        for al in aliases:
            escolha = next((c for c, n in norm.items() if n == al and c not in usadas), None)
            if escolha:
                break
        if not escolha:
            for al in aliases:
                escolha = next((c for c, n in norm.items() if al in n and c not in usadas), None)
                if escolha:
                    break
        if escolha:
            mapa[campo] = escolha
            usadas.add(escolha)
    return mapa


def _detetar_cabecalho(bruto):
    """Exports têm por vezes linhas de título antes do cabeçalho: escolhe a linha que mais parece um cabeçalho."""
    melhor, melhor_i = -1, 0
    for i in range(min(15, len(bruto))):
        cel = [str(x) for x in bruto.iloc[i].tolist() if str(x) != "nan"]
        pts = len(mapear_colunas(cel))
        if pts > melhor:
            melhor, melhor_i = pts, i
    cab, vistos = [], {}
    for j, x in enumerate(bruto.iloc[melhor_i].tolist()):
        nome = str(x).strip() if str(x) != "nan" else f"coluna_{j + 1}"
        vistos[nome] = vistos.get(nome, 0) + 1
        cab.append(nome if vistos[nome] == 1 else f"{nome}_{vistos[nome]}")
    df = bruto.iloc[melhor_i + 1:].reset_index(drop=True)
    df.columns = cab
    return df


def ler_tabela(dados: bytes, nome: str):
    import pandas as pd
    suf = nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if suf in ("xlsx", "xlsm"):
        return _detetar_cabecalho(pd.read_excel(io.BytesIO(dados), dtype=str, header=None))
    if suf == "xls":
        raise ValueError("Ficheiro .xls antigo: abra no Excel e use 'Guardar como' .xlsx")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(dados), dtype=str, sep=None, engine="python", encoding=enc)
            df.columns = [str(c) for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError("Não consegui ler o ficheiro (codificação desconhecida).")


def importar_df(df, escolhas: dict, origem: str) -> tuple[int, int, int]:
    """escolhas: campo -> nome da coluna (ou None). Devolve (novos, duplicados, ignorados)."""
    novos = dup = ign = 0
    agora = time.strftime("%Y-%m-%d %H:%M:%S")
    with ligar() as con:
        for _, row in df.iterrows():
            def v(campo):
                col = escolhas.get(campo)
                x = row.get(col) if col else ""
                return "" if x is None or str(x).strip().lower() in ("nan", "none", "nat") else str(x).strip()
            avaria, solucao = v("avaria"), v("solucao")
            if not (avaria or solucao):
                ign += 1
                continue
            ref, equip, causa, data, tempo = v("id"), v("equipamento"), v("causa"), v("data")[:10], v("tempo")
            chave = hashlib.sha1("|".join(textutil.sem_acentos(x.lower())
                                          for x in (ref, equip, avaria, causa, solucao)).encode()).hexdigest()
            cur = con.execute(
                "INSERT OR IGNORE INTO casos_importados (ts, origem, ref, data, equipamento, avaria, causa, solucao, tempo, chave)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", (agora, origem, ref, data, equip, avaria, causa, solucao, tempo, chave))
            if cur.rowcount:
                novos += 1
            else:
                dup += 1
    return novos, dup, ign


def carregar_importados() -> list[Caso]:
    with ligar() as con:
        linhas = con.execute("SELECT * FROM casos_importados ORDER BY id").fetchall()
    return [Caso(id=(f"OT {r['ref']}" if r["ref"] else f"H{r['id']}"), origem="Histórico", data=r["data"] or "",
                 equipamento=r["equipamento"] or "", avaria=r["avaria"] or "", causa=r["causa"] or "",
                 solucao=r["solucao"] or "", tempo=r["tempo"] or "") for r in linhas]


def contar() -> int:
    with ligar() as con:
        return con.execute("SELECT COUNT(*) FROM casos_importados").fetchone()[0]


def listar_origens() -> list[tuple[str, int]]:
    with ligar() as con:
        return [(r[0], r[1]) for r in con.execute(
            "SELECT origem, COUNT(*) FROM casos_importados GROUP BY origem ORDER BY MAX(id) DESC")]


def apagar_origem(origem: str) -> int:
    with ligar() as con:
        return con.execute("DELETE FROM casos_importados WHERE origem=?", (origem,)).rowcount
'''

# ----------------------- core/history.py -----------------------
_FONTES['history'] = r'''
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
'''

# ----------------------- core/pdf_store.py -----------------------
_FONTES['pdf_store'] = r'''
"""Leitura de manuais PDF (PyMuPDF), cache em disco e chunks por página.

`fitz` só é importado dentro das funções, para o resto do projeto poder ser testado sem ele.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import config, textutil
from .embeddings import IndiceHibrido
from .search import Chunk, dividir_em_chunks


@dataclass
class Manual:
    nome: str
    caminho: Path
    hash: str
    textos: list[str]        # um por página (índice 0 = página 1)
    idioma: str
    paginas_sem_texto: list[int]

    @property
    def n_paginas(self) -> int:
        return len(self.textos)

    def construir_indice(self) -> IndiceHibrido:
        chunks: list[Chunk] = []
        for i, t in enumerate(self.textos, start=1):
            for parte in dividir_em_chunks(t, config.CHUNK_PALAVRAS, config.CHUNK_SOBREPOSICAO):
                chunks.append(Chunk(parte, {"pagina": i}))
        return IndiceHibrido(chunks)


def listar_manuais() -> dict[str, Path]:
    return {p.name: p for p in sorted(config.PASTA_MANUAIS.glob("*.pdf"))}


def _hash_ficheiro(caminho: Path) -> str:
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def carregar_manual(caminho: Path) -> Manual:
    """Lê o PDF uma única vez; seguintes aberturas usam a cache em data/cache/<hash>.json."""
    caminho = Path(caminho)
    h = _hash_ficheiro(caminho)
    cache = config.PASTA_CACHE / f"{h}.json"
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            return Manual(caminho.name, caminho, h, d["textos"], d["idioma"], d["sem_texto"])
        except Exception:
            pass

    import fitz  # PyMuPDF
    textos, sem_texto = [], []
    with fitz.open(caminho) as doc:
        for i, pag in enumerate(doc, start=1):
            t = pag.get_text("text", sort=True).strip()
            textos.append(t)
            if len(t) < 15:
                sem_texto.append(i)
    amostra = " ".join(t for t in textos if len(t) > 40)[:6000]
    idioma = textutil.detetar_idioma(amostra)
    cache.write_text(json.dumps({"textos": textos, "idioma": idioma, "sem_texto": sem_texto}), encoding="utf-8")
    return Manual(caminho.name, caminho, h, textos, idioma, sem_texto)
'''

# ----------------------- core/translate.py -----------------------
_FONTES['translate'] = r'''
"""Tradução de uma página de esquema para PT-PT, usando o mesmo LLM (sem serviços externos).

Estratégia:
  1. extrai blocos de texto horizontais da página (PyMuPDF);
  2. traduz em lotes numerados com glossário técnico fixo;
  3. guarda em cache (por manual+página);
  4. desenha a tradução sobre a página SEM apagar linhas/símbolos (redação só de texto, sem fundo branco).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import config, llm, textutil

GLOSSARIO_PROMPT = (
    "terminal=borne; shield=malha; breaker/circuit breaker=disjuntor; relay=relé; contactor=contactor; "
    "fuse=fusível; power supply=fonte de alimentação; analog input=entrada analógica; "
    "analog output=saída analógica; emergency stop=paragem de emergência; safety=segurança; "
    "inverter/drive=variador; probe/sensor=sonda/sensor; cable=cabo; wire=fio; fault=falha; "
    "supply voltage=tensão de alimentação; loom/knitting machine=tear/máquina de malha. "
    "Mantém INALTERADOS: referências (X1, K3, -F2, Q01), valores e unidades (24VDC, 4-20mA), siglas (PLC, PE, PT100)."
)

_RE_SO_CODIGO = re.compile(r"^[\W\d_A-Za-z]{0,6}$")


def precisa_traduzir(texto: str) -> bool:
    palavras = re.findall(r"[A-Za-zÀ-ÿ]{4,}", texto)
    return len(palavras) > 0 and not _RE_SO_CODIGO.match(texto.strip())


def _caminho_cache(hash_manual: str, pagina: int, idioma_origem: str) -> Path:
    chave = hashlib.sha1(f"{hash_manual}|{pagina}|{idioma_origem}|{config.LLM_PROVIDER}".encode()).hexdigest()
    return config.PASTA_CACHE / f"trad_{chave}.json"


def extrair_blocos(pdf_path: Path, pagina: int) -> list[dict]:
    """[{bbox:(x0,y0,x1,y1), texto, tamanho}] só de texto horizontal com letras."""
    import fitz
    blocos = []
    with fitz.open(pdf_path) as doc:
        d = doc.load_page(pagina - 1).get_text("dict")
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        linhas = b.get("lines", [])
        if not linhas or any(tuple(round(x, 2) for x in l.get("dir", (1, 0))) != (1.0, 0.0) for l in linhas):
            continue
        texto = " ".join("".join(s.get("text", "") for s in l.get("spans", [])).strip() for l in linhas).strip()
        if len(texto) < 3 or not precisa_traduzir(texto):
            continue
        tam = linhas[0]["spans"][0].get("size", 8.0) if linhas[0].get("spans") else 8.0
        blocos.append({"bbox": tuple(b["bbox"]), "texto": texto, "tamanho": tam})
    return blocos


def _traduzir_lote(textos: list[str], idioma_origem: str) -> list[str]:
    entrada = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(textos))
    sistema = (
        "És tradutor técnico de manuais de máquinas têxteis e quadros elétricos. "
        f"Traduz do idioma '{idioma_origem}' para Português de Portugal. Glossário: {GLOSSARIO_PROMPT} "
        "Responde APENAS com as linhas traduzidas, no mesmo formato '[n] texto', uma por linha, sem comentários."
    )
    saida = llm.gerar([{"role": "system", "content": sistema}, {"role": "user", "content": entrada}],
                      max_tokens=2500, temperatura=0.0)
    mapa = {int(n): t.strip() for n, t in re.findall(r"^\[(\d+)\]\s*(.+)$", saida, re.MULTILINE)}
    return [mapa.get(i + 1, textos[i]) for i in range(len(textos))]   # se faltar, mantém original


def traduzir_pagina(pdf_path: Path, hash_manual: str, pagina: int, idioma_origem: str) -> list[dict]:
    """Devolve blocos com campo 'traducao'. Usa cache em disco."""
    cache = _caminho_cache(hash_manual, pagina, idioma_origem)
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    blocos = extrair_blocos(pdf_path, pagina)
    for i in range(0, len(blocos), 25):
        lote = blocos[i:i + 25]
        for b, t in zip(lote, _traduzir_lote([b["texto"] for b in lote], idioma_origem)):
            b["traducao"] = t
    cache.write_text(json.dumps(blocos), encoding="utf-8")
    return blocos


def _latin1(t: str) -> str:
    for a, b in {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "º": "o", "ª": "a"}.items():
        t = t.replace(a, b)
    return t.encode("latin-1", "ignore").decode("latin-1")


def aplicar_traducao_na_pagina(pagina_fitz, blocos: list[dict]) -> None:
    """Substitui o texto original pela tradução, preservando desenho vetorial e imagens."""
    import fitz
    validos = [b for b in blocos if b.get("traducao") and b["traducao"].strip().lower() != b["texto"].strip().lower()]
    for b in validos:
        pagina_fitz.add_redact_annot(fitz.Rect(b["bbox"]), fill=False)   # sem fundo: não apaga fios
    pagina_fitz.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
    )
    for b in validos:
        r = fitz.Rect(b["bbox"])
        txt = _latin1(b["traducao"])
        tam = max(min(b["tamanho"], 12.0), 4.0)
        while tam >= 3.2:
            sobra = pagina_fitz.insert_textbox(r, txt, fontsize=tam, fontname="helv", color=(0, 0, 0.55))
            if sobra >= 0:
                break
            tam -= 0.5
        else:   # não coube: escreve em linha única, comprimida
            pagina_fitz.insert_text((r.x0, r.y1 - 1), txt, fontsize=3.2, fontname="helv", color=(0, 0, 0.55))
'''

# ----------------------- core/viewer.py -----------------------
_FONTES['viewer'] = r'''
"""Visualizador com zoom e arrastar (roda do rato, botões, duplo clique), em HTML+JS puro.

Não precisa de bibliotecas no PC do técnico: corre no browser. Aceita PNG ou SVG (vetorial,
nítido em qualquer zoom).
"""
from __future__ import annotations

import base64


def renderizar_pagina(pdf_path, pagina: int, zoom: float = 3.0, blocos_traduzidos: list[dict] | None = None,
                      formato: str = "png") -> tuple[bytes, str]:
    """(bytes, mime). Se houver blocos traduzidos, aplica-os numa cópia em memória da página."""
    import fitz
    from . import translate
    with fitz.open(pdf_path) as doc:
        pag = doc.load_page(pagina - 1)
        if blocos_traduzidos:
            translate.aplicar_traducao_na_pagina(pag, blocos_traduzidos)
        if formato == "svg":
            return pag.get_svg_image(text_as_path=True).encode("utf-8"), "image/svg+xml"
        pix = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png"), "image/png"


_TEMPLATE = """
<style>
 html,body{margin:0;height:100%;background:#0b1020;font-family:Segoe UI,Roboto,sans-serif}
 #wrap{position:relative;width:100%;height:__ALTURA__px;overflow:hidden;background:#fff;border:1px solid #334155;
       border-radius:8px;cursor:grab;touch-action:none}
 #wrap.arrasta{cursor:grabbing}
 #img{position:absolute;left:0;top:0;transform-origin:0 0;user-select:none;-webkit-user-drag:none;max-width:none}
 #bar{position:absolute;top:8px;right:8px;display:flex;gap:6px;z-index:5}
 #bar button{background:#0284c7;color:#fff;border:0;border-radius:6px;padding:6px 10px;font-size:15px;cursor:pointer}
 #bar button:hover{background:#0ea5e9}
 #dica{position:absolute;left:8px;bottom:6px;font-size:12px;color:#475569;background:rgba(255,255,255,.8);
       padding:2px 6px;border-radius:4px}
</style>
<div id="wrap">
  <div id="bar"><button id="mais" title="Aproximar">＋</button><button id="menos" title="Afastar">－</button>
  <button id="ajusta" title="Ajustar ao ecrã">⤢</button><button id="cheio" title="Ecrã inteiro">⛶</button></div>
  <img id="img" src="data:__MIME__;base64,__B64__" draggable="false">
  <div id="dica">Roda do rato = zoom · Arrastar = mover · Duplo clique = ajustar</div>
</div>
<script>
(function(){
 const w=document.getElementById('wrap'), im=document.getElementById('img');
 let s=1,x=0,y=0,drag=false,sx=0,sy=0;
 function ap(){im.style.transform='translate('+x+'px,'+y+'px) scale('+s+')';}
 function ajusta(){const iw=im.naturalWidth||1, ih=im.naturalHeight||1;
   s=Math.min(w.clientWidth/iw,w.clientHeight/ih); x=(w.clientWidth-iw*s)/2; y=(w.clientHeight-ih*s)/2; ap();}
 function zoomEm(f,cx,cy){const n=Math.min(Math.max(s*f,0.02),60); const k=n/s;
   x=cx-(cx-x)*k; y=cy-(cy-y)*k; s=n; ap();}
 im.onload=ajusta; if(im.complete) ajusta();
 w.addEventListener('wheel',e=>{e.preventDefault();const r=w.getBoundingClientRect();
   zoomEm(e.deltaY<0?1.2:1/1.2,e.clientX-r.left,e.clientY-r.top);},{passive:false});
 w.addEventListener('pointerdown',e=>{if(e.target.closest('#bar'))return;drag=true;sx=e.clientX-x;sy=e.clientY-y;
   w.classList.add('arrasta');w.setPointerCapture(e.pointerId);});
 w.addEventListener('pointermove',e=>{if(!drag)return;x=e.clientX-sx;y=e.clientY-sy;ap();});
 w.addEventListener('pointerup',()=>{drag=false;w.classList.remove('arrasta');});
 w.addEventListener('dblclick',ajusta);
 document.getElementById('mais').onclick=()=>zoomEm(1.4,w.clientWidth/2,w.clientHeight/2);
 document.getElementById('menos').onclick=()=>zoomEm(1/1.4,w.clientWidth/2,w.clientHeight/2);
 document.getElementById('ajusta').onclick=ajusta;
 document.getElementById('cheio').onclick=()=>{ if(document.fullscreenElement){document.exitFullscreen();}
   else{w.requestFullscreen&&w.requestFullscreen();} setTimeout(ajusta,250);};
 window.addEventListener('resize',ajusta);
})();
</script>
"""


def html_visualizador(imagem: bytes, mime: str, altura: int = 640) -> str:
    return (_TEMPLATE.replace("__ALTURA__", str(altura)).replace("__MIME__", mime)
            .replace("__B64__", base64.b64encode(imagem).decode("ascii")))
'''

# ----------------------- core/diagnosis.py -----------------------
_FONTES['diagnosis'] = r'''
"""Montagem do prompt de diagnóstico, regras de segurança e formatação das fontes.

Princípio: o sistema SUGERE, nunca ordena. Só afirma o que está nas fontes (manual, casos
resolvidos) ou rotula como conhecimento geral a confirmar.
"""
from __future__ import annotations

import re

from . import config, llm, textutil
from .casos import Caso
from .search import Chunk, reescrever_consulta_simples

PROMPT_SISTEMA = """És um assistente de apoio ao diagnóstico para técnicos de manutenção de máquinas têxteis e quadros elétricos. Falas Português de Portugal industrial (bornes, malha, disjuntor, cartão analógico).

O TEU PAPEL: SUGERIR, nunca decidir nem ordenar. O técnico é quem decide e executa; um erro teu pode causar danos ou acidentes.

REGRAS OBRIGATÓRIAS
1. Usa APENAS as fontes fornecidas: trechos do manual, imagens de páginas do manual e casos já resolvidos (histórico importado e casos validados por técnicos). O conhecimento geral só pode aparecer rotulado como "(conhecimento geral – confirmar)".
2. NUNCA inventes bornes, pinos, referências, valores de tensão ou parâmetros. Se o manual não o indica, diz exatamente: "Não encontrei isso no manual fornecido."
3. Formula sempre como recomendação ou pergunta, por exemplo: "O que acha de medir a tensão entre os bornes X1.1 e X1.2? Deve rondar 24 V segundo [Manual p.12]." Nunca uses imperativos secos.
4. Cita a origem de cada afirmação: [Manual p.N] para o manual e, para os casos, exatamente a etiqueta que aparece na lista (por exemplo [OT 123] ou [FB7]).
5. Lê a conversa: não repitas testes que o técnico já fez; avança para a hipótese seguinte.
6. Se vários casos antigos apontam a mesma causa, diz quantos e com que frequência; se são só vagamente parecidos, di-lo.
7. Os trechos do manual podem estar noutro idioma (inglês, alemão...). Responde sempre em português e traduz os termos técnicos.
8. Se a informação for insuficiente, faz UMA pergunta curta ao técnico (modelo da máquina, código de erro, o que mudou) em vez de adivinhar.
9. Se receberes imagens de páginas (esquemas), só descreves bornes, ligações e referências que consigas LER com clareza; se algo estiver ilegível ou ambíguo, diz que não consegues confirmar na imagem e pede ao técnico para verificar no esquema.

FORMATO (curto, sem enrolar)
**Leitura do problema:** 1–2 frases.
**Hipóteses (da mais para a menos provável):** lista numerada, cada uma com o porquê e a fonte.
**Próximo passo sugerido:** UM só passo, em forma de pergunta/recomendação, de preferência o mais simples e seguro primeiro (inspeção visual, ligações, fusíveis) antes de medições.
**Fontes consultadas:** lista curta.
Máximo 180 palavras no total."""

AVISO_SEGURANCA = (
    "⚠️ **Segurança:** medições em quadros energizados só por pessoal habilitado e seguindo o procedimento da empresa "
    "(corte, bloqueio e verificação de ausência de tensão). Estas sugestões podem estar erradas — confirme no esquema "
    "e com o responsável antes de intervir."
)

_RE_MEDICAO = re.compile(
    r"\b(medi\w*|tens[aã]o|volt\w*|\d+\s?v\b|vdc|vac|ma\b|mult[ií]metro|continuidade|resist[eê]ncia|bornes?|cabo|alimenta\w*)",
    re.IGNORECASE,
)


def precisa_aviso_seguranca(resposta: str) -> bool:
    return bool(_RE_MEDICAO.search(resposta))


def formatar_trechos(trechos: list[tuple[Chunk, float]]) -> str:
    if not trechos:
        return "(nenhum trecho relevante encontrado no manual)"
    return "\n\n".join(f"[Manual p.{c.meta['pagina']}]\n{c.texto}" for c, _ in trechos)


def formatar_casos(casos: list[tuple[Caso, float]]) -> str:
    if not casos:
        return "(ainda sem casos parecidos registados)"
    linhas = []
    for c, _ in casos:
        linhas.append(
            f"[{c.id}] {c.data} | Equip.: {c.equipamento or '?'} | Avaria: {c.avaria or '?'} | "
            f"Causa: {c.causa or 'não registada'} | Solução: {c.solucao or 'não registada'}"
            + (" | VALIDADO por técnico" if c.origem == "Feedback" else "")
        )
    return "\n".join(linhas)


def montar_mensagens(pergunta: str, historico: list[dict], trechos, casos, manual_nome: str,
                     equipamento: str | None, idioma_manual: str, max_hist: int = 6,
                     imagens: list | None = None, paginas_imagem: list[int] | None = None) -> list[dict]:
    contexto = (
        f"MANUAL: {manual_nome} (idioma: {idioma_manual})\n"
        f"EQUIPAMENTO: {equipamento or 'não indicado'}\n\n"
        f"TRECHOS DO MANUAL:\n{formatar_trechos(trechos)}\n\n"
        f"CASOS PARECIDOS JÁ RESOLVIDOS:\n{formatar_casos(casos)}\n\n"
    )
    if imagens:
        pags = ", ".join(f"p.{p}" for p in (paginas_imagem or []))
        contexto += (f"IMAGENS ANEXAS: páginas do manual ({pags}) como imagem. Usa-as para ver esquemas, bornes e "
                     f"ligações; só afirma o que estiver legível.\n\n")
    contexto += f"MENSAGEM ATUAL DO TÉCNICO: {pergunta}"
    msgs = [{"role": "system", "content": PROMPT_SISTEMA}]
    for m in historico[-max_hist:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    ultimo = {"role": "user", "content": contexto}
    if imagens:
        ultimo["imagens"] = imagens
    msgs.append(ultimo)
    return msgs


def _ja_e_autonoma(pergunta: str) -> bool:
    """Pergunta completa (várias palavras ou com código de erro): não precisa de contexto nem de IA."""
    return len(pergunta.split()) >= 8 or bool(textutil.codigos_numericos(pergunta))


def reescrever_consulta(pergunta: str, historico: list[dict], usar_llm: bool = False) -> str:
    """'E agora?' sozinho não pesquisa nada. Por defeito junta as últimas perguntas (instantâneo, grátis).
    Só chama a IA se usar_llm=True e a pergunta for curta/dependente do contexto."""
    if not historico or _ja_e_autonoma(pergunta):
        return pergunta
    simples = reescrever_consulta_simples(historico, pergunta)
    if not usar_llm:
        return simples
    try:
        resumo = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in historico[-4:])
        saida = llm.gerar(
            [{"role": "system", "content": "Reescreve a última mensagem do técnico como UMA consulta de pesquisa "
                                           "autónoma (máx. 25 palavras, português, termos técnicos, códigos de erro "
                                           "exatos). Responde só com a consulta."},
             {"role": "user", "content": f"Conversa:\n{resumo}\n\nÚltima mensagem: {pergunta}"}],
            max_tokens=80, temperatura=0.0)
        return (saida.splitlines()[0].strip() if saida else simples) or simples
    except Exception:
        return simples


def preparar(pergunta, historico, manual, indice, base, equipamento, semantica=True,
             usar_llm_reescrita=False, escolher_imagens=None):
    """Pesquisa no manual e nos casos e monta as mensagens. Partilhado pela app e pelo teste de qualidade.
    escolher_imagens(trechos) -> (imagens, paginas) é opcional. Devolve (mensagens, trechos, casos)."""
    consulta = reescrever_consulta(pergunta, historico, usar_llm_reescrita)
    try:
        trechos = indice.procurar(consulta, k=config.TOP_CHUNKS_MANUAL, semantica=semantica)
    except TypeError:
        trechos = indice.procurar(consulta, k=config.TOP_CHUNKS_MANUAL)
    casos = base.procurar(consulta, equipamento, k=config.TOP_CASOS)
    imagens, paginas_img = escolher_imagens(trechos) if escolher_imagens else ([], [])
    msgs = montar_mensagens(pergunta, historico, trechos, casos, manual.nome, equipamento, manual.idioma,
                            imagens=imagens or None, paginas_imagem=paginas_img)
    return msgs, trechos, casos


def escolher_paginas_imagem(foco: int, trechos, textos: list[str], modo: str = "Auto",
                            maximo: int = 2, limite_palavras: int = 150) -> list[int]:
    """Páginas cuja IMAGEM vai para a IA.
    Auto: a melhor página encontrada pela pesquisa + páginas com pouco texto (esquemas) até ao máximo.
    Sempre: as melhores páginas encontradas (e a página em foco se sobrar lugar). Nunca: nenhuma."""
    if modo == "Nunca":
        return []
    encontradas: list[int] = []
    for ch, _ in trechos:
        if ch.meta["pagina"] not in encontradas:
            encontradas.append(ch.meta["pagina"])
    escolhidas: list[int] = []

    def juntar(p):
        if 1 <= p <= len(textos) and p not in escolhidas and len(escolhidas) < maximo:
            escolhidas.append(p)

    if modo == "Sempre":
        for p in encontradas:
            juntar(p)
        juntar(foco)
        return escolhidas
    if encontradas:
        juntar(encontradas[0])                      # a página que a pesquisa considera melhor
    for p in [foco] + encontradas[1:]:
        if 1 <= p <= len(textos) and len(textos[p - 1].split()) < limite_palavras:
            juntar(p)
    return escolhidas


def paginas_citadas(resposta: str, n_paginas: int) -> list[int]:
    pags = []
    for m in re.finditer(r"\[Manual p\.?\s*(\d+)\]", resposta, re.IGNORECASE):
        p = int(m.group(1))
        if 1 <= p <= n_paginas and p not in pags:
            pags.append(p)
    return pags
'''

# ----------------------- core/avaliacao.py -----------------------
_FONTES['avaliacao'] = r'''
"""Teste de qualidade: casos reais com a resposta certa conhecida -> mede se a app acerta.

Dois testes:
  - pesquisa (grátis, instantâneo): a página certa aparece nos trechos encontrados?
  - com IA (usa a API): a resposta cita a página certa e menciona as palavras-chave da solução?
"""
from __future__ import annotations

import json
import time

from . import diagnosis, textutil
from .feedback import ligar


def adicionar_teste(manual, equipamento, sintoma, causa_real, pagina_esperada, palavras) -> int:
    with ligar() as con:
        return con.execute(
            "INSERT INTO testes (manual, equipamento, sintoma, causa_real, pagina_esperada, palavras) VALUES (?,?,?,?,?,?)",
            (manual, (equipamento or "").strip(), sintoma.strip(), (causa_real or "").strip(),
             int(pagina_esperada) if pagina_esperada else None, (palavras or "").strip())).lastrowid


def listar_testes(manual) -> list[dict]:
    with ligar() as con:
        return [dict(r) for r in con.execute("SELECT * FROM testes WHERE manual=? ORDER BY id", (manual,))]


def apagar_teste(id_: int) -> None:
    with ligar() as con:
        con.execute("DELETE FROM testes WHERE id=?", (id_,))


def _paginas(resultados) -> list[int]:
    pags: list[int] = []
    for c, _ in resultados:
        if c.meta["pagina"] not in pags:
            pags.append(c.meta["pagina"])
    return pags


def avaliar_recuperacao(indice, testes, k=5, semantica=False) -> dict:
    linhas, n, hits, rr = [], 0, 0, 0.0
    for t in testes:
        try:
            pags = _paginas(indice.procurar(t["sintoma"], k=k, semantica=semantica))
        except TypeError:                      # índice simples, sem parâmetro 'semantica'
            pags = _paginas(indice.procurar(t["sintoma"], k=k))
        esp = t["pagina_esperada"]
        ok = None
        if esp:
            n += 1
            ok = esp in pags
            if ok:
                hits += 1
                rr += 1.0 / (pags.index(esp) + 1)
        linhas.append({"teste": t["id"], "sintoma": t["sintoma"][:70], "página certa": esp,
                       "páginas encontradas": ", ".join(map(str, pags)), "acertou": {True: "✅", False: "❌", None: "—"}[ok]})
    return {"n": n, "hit": hits / n if n else 0.0, "mrr": rr / n if n else 0.0, "linhas": linhas}


def avaliar_com_ia(testes, manual, indice, base, semantica, gerar, pausa=1.0, progresso=None) -> dict:
    linhas, n_pag, cita, soma_pal, n_pal, erros = [], 0, 0, 0.0, 0, 0
    for i, t in enumerate(testes, start=1):
        resp, erro = "", ""
        try:
            msgs, _, _ = diagnosis.preparar(t["sintoma"], [], manual, indice, base, t["equipamento"] or None,
                                            semantica=semantica)
            resp = gerar(msgs)
        except Exception as e:
            erro = str(e)[:100]
            erros += 1
        pags = diagnosis.paginas_citadas(resp, manual.n_paginas)
        esp = t["pagina_esperada"]
        ok = None
        if esp:
            n_pag += 1
            ok = esp in pags
            cita += 1 if ok else 0
        palavras = [p.strip() for p in (t["palavras"] or "").split(",") if p.strip()]
        cob = None
        if palavras:
            texto = textutil.sem_acentos(resp.lower())
            cob = sum(1 for p in palavras if textutil.sem_acentos(p.lower()) in texto) / len(palavras)
            soma_pal += cob
            n_pal += 1
        linhas.append({"teste": t["id"], "sintoma": t["sintoma"][:60], "cita a página certa": {True: "✅", False: "❌", None: "—"}[ok],
                       "palavras-chave": "—" if cob is None else f"{cob * 100:.0f}%", "erro": erro})
        if progresso:
            progresso(i, len(testes))
        if pausa and i < len(testes):
            time.sleep(pausa)
    return {"n": n_pag, "hit": cita / n_pag if n_pag else 0.0, "mrr": soma_pal / n_pal if n_pal else 0.0,
            "erros": erros, "linhas": linhas}


def registar_execucao(manual, modo, r: dict) -> None:
    with ligar() as con:
        con.execute("INSERT INTO execucoes (ts, manual, modo, n, hit, mrr, extra) VALUES (?,?,?,?,?,?,?)",
                    (time.strftime("%Y-%m-%d %H:%M"), manual, modo, r["n"], r["hit"], r["mrr"],
                     json.dumps({"erros": r.get("erros", 0)})))


def listar_execucoes(manual, limite=12) -> list[dict]:
    with ligar() as con:
        return [{"quando": r["ts"], "teste": r["modo"], "casos": r["n"], "acerto": f"{r['hit'] * 100:.0f}%",
                 "MRR / palavras": f"{r['mrr']:.2f}"} for r in con.execute(
            "SELECT * FROM execucoes WHERE manual=? ORDER BY id DESC LIMIT ?", (manual, limite))]
'''

_ORDEM = ['config', 'textutil', 'auth', 'search', 'llm', 'embeddings', 'casos', 'feedback', 'importar', 'history', 'pdf_store', 'translate', 'viewer', 'diagnosis', 'avaliacao']
_pkg = _types.ModuleType("core")
_pkg.__path__ = []
_sys.modules["core"] = _pkg
for _n in _ORDEM:
    _m = _types.ModuleType("core." + _n)
    _m.__package__ = "core"
    _m.__file__ = str(_Path(__file__).resolve().parent / "core" / (_n + ".py"))
    _sys.modules["core." + _n] = _m
    setattr(_pkg, _n, _m)
    exec(compile(_FONTES[_n], "core/" + _n + ".py", "exec"), _m.__dict__)

# ======================= APLICACAO =======================
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core import (auth, avaliacao, casos as mod_casos, config, diagnosis, embeddings, feedback, history,
                  importar, llm, pdf_store, textutil, translate, viewer)

st.set_page_config(page_title="Assistente MGC", page_icon="⚡", layout="wide", initial_sidebar_state="auto")

st.markdown("""
<style>
/* ===== MOBILE RESPONSIVE ===== */
@media (max-width: 768px) {
  /* Stack columns vertically on mobile */
  .stHorizontalBlock, .stColumns {
    flex-direction: column !important;
  }
  .stHorizontalBlock > div, .stColumns > div {
    width: 100% !important;
    min-width: 0 !important;
  }
  
  /* Chat input full width on mobile */
  [data-testid="stChatInput"] {
    width: 100% !important;
  }
  [data-testid="stChatInput"] > div {
    width: 100% !important;
  }
  
  /* Viewer height responsive */
  #wrap {
    height: 400px !important;
  }
  
  /* Sidebar spacing */
  section[data-testid="stSidebar"] {
    padding-top: 1rem !important;
  }
  
  /* Reduce padding on mobile */
  .block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
  }
  
  /* Chat messages more compact */
  div[data-testid="stChatMessage"] {
    padding: 0.75rem !important;
    margin-bottom: 0.5rem !important;
  }
  
  /* Buttons full width on mobile */
  .stButton > button {
    width: 100% !important;
  }
  
  /* Number input compact */
  .stNumberInput > div > div > input {
    padding: 0.5rem !important;
  }
  
  /* Expander more compact */
  .streamlit-expanderHeader {
    padding: 0.5rem 0.75rem !important;
  }
}

/* ===== BASE STYLES ===== */
.stApp {
  background: #050810;
  background-image: radial-gradient(circle at top right, #0a1128 0%, #050810 100%);
  color: #e2e8f0;
}

section[data-testid="stSidebar"] {
  background: rgba(10, 15, 30, .9);
  border-right: 1px solid rgba(56, 189, 248, .2);
}

h1, h2, h3 {
  color: #38bdf8 !important;
}

div[data-testid="stChatMessage"] {
  background: rgba(30, 41, 59, .65);
  border: 1px solid rgba(255, 255, 255, .05);
  border-radius: 12px;
}

.stButton button {
  border-radius: 8px;
  font-weight: 600;
}

/* Viewer container responsive */
.viewer-container {
  width: 100%;
  min-height: 300px;
}

/* Ensure horizontal container wraps properly */
.stHorizontalBlock {
  gap: 1rem;
}

/* Chat input submit mode for better UX */
[data-testid="stChatInput"] {
  position: sticky;
  bottom: 0;
  background: inherit;
  padding-top: 0.5rem;
  z-index: 100;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ configuração obrigatória
try:
    config.pin_acesso()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

# ------------------------------------------------------------------ sessão / login
if "utilizador" not in st.session_state:
    token = st.query_params.get("t", "")
    st.session_state.utilizador = auth.validar_token(token) if token else None

if not st.session_state.utilizador:
    # Login page responsiva
    with st.container(horizontal_alignment="center"):
        st.markdown("# ⚡ Assistente MGC")
        st.caption("Apoio ao diagnóstico de avarias")
        
        with st.form("login", border=True):
            if config.LISTA_TECNICOS:
                nome = st.selectbox("Técnico", config.LISTA_TECNICOS)
            else:
                nome = st.text_input("Nome do técnico")
            pin = st.text_input("PIN de acesso", type="password")
            if st.form_submit_button("Entrar", use_container_width=True, type="primary"):
                ok, msg = auth.verificar_login(nome, pin)
                if ok:
                    st.session_state.utilizador = nome.strip()
                    st.query_params["t"] = auth.criar_token(nome.strip())
                    st.rerun()
                else:
                    st.error(msg)
    st.stop()

utilizador: str = st.session_state.utilizador


# ------------------------------------------------------------------ recursos em cache
@st.cache_resource(show_spinner="A ler o manual...")
def _abrir_manual(caminho: str, mtime: float):
    m = pdf_store.carregar_manual(Path(caminho))
    return m, m.construir_indice()


def _assinatura_casos():
    return (len(feedback.casos_validados()), importar.contar())


@st.cache_resource(show_spinner="A carregar casos resolvidos...")
def _base_casos(assinatura):
    return mod_casos.BaseCasos(importar.carregar_importados() + feedback.casos_validados())


@st.cache_data(show_spinner=False, max_entries=12)
def _pagina_renderizada(caminho: str, hash_manual: str, pagina: int, zoom: float, formato: str,
                        traduzir: bool, idioma: str, provider: str):
    blocos = translate.traduzir_pagina(Path(caminho), hash_manual, pagina, idioma) if traduzir else None
    dados, mime = viewer.renderizar_pagina(caminho, pagina, zoom, blocos, formato)
    return dados, mime, blocos


@st.cache_data(show_spinner=False, max_entries=20)
def _imagem_para_ia(caminho: str, pagina: int) -> bytes:
    dados, _ = viewer.renderizar_pagina(caminho, pagina, 1.8, None, "png")
    return dados


@st.cache_data(ttl=30, show_spinner=False)
def _estado_llm(_chave: int):
    return llm.estado()


# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.markdown(f"### 👤 {utilizador}")
    modo = st.radio("Modo", ["💬 Diagnóstico", "🧪 Qualidade"], horizontal=True, label_visibility="collapsed")
    manuais = pdf_store.listar_manuais()

    with st.expander("➕ Adicionar manual (PDF)"):
        up = st.file_uploader("Ficheiro PDF", type="pdf", key="upload_pdf")
        if up is not None:
            destino = config.PASTA_MANUAIS / Path(up.name).name
            if not destino.exists():
                destino.write_bytes(up.getbuffer())
                st.success("Manual guardado.")
                st.rerun()
            else:
                st.info("Já existe um manual com esse nome.")

    if not manuais:
        st.warning("Sem manuais. Adicione um PDF acima ou copie para a pasta 'manuais'.")
        st.stop()

    nome_manual = st.selectbox("📚 Manual da máquina", list(manuais.keys()))
    manual, indice = _abrir_manual(str(manuais[nome_manual]), manuais[nome_manual].stat().st_mtime)

    base = _base_casos(_assinatura_casos())
    equip_sel = st.text_input("🏭 Equipamento / máquina", placeholder="ex.: Tear 3",
                              help="Opcional. Fica registado nos casos resolvidos e melhora a pesquisa.")
    equipamento = equip_sel.strip() or None

    st.caption(f"Manual: {manual.n_paginas} págs · idioma detetado: **{manual.idioma}**")
    if manual.paginas_sem_texto:
        st.caption(f"{len(manual.paginas_sem_texto)} págs sem texto pesquisável (só desenho).")
    n_imp = importar.contar()
    st.caption(f"Casos: {n_imp} importados · {len(base.casos) - n_imp} validados pelos técnicos")

    ok_llm, msg_llm = _estado_llm(0)
    (st.success if ok_llm else st.error)("🧠 " + msg_llm)

    # ---- pesquisa por significado (embeddings) e imagens dos esquemas: só com Gemini
    tem_gemini = config.LLM_PROVIDER == "gemini" and bool(config.GEMINI_API_KEY)
    st.divider()
    st.markdown("**Inteligência**")
    usar_semantica = st.checkbox("🔎 Pesquisa por significado (mais precisa)", value=tem_gemini and not manual.idioma.startswith("pt"),
                                 disabled=not tem_gemini,
                                 help="Junta à pesquisa por palavras uma pesquisa por significado (embeddings do Gemini). "
                                      "Útil quando o manual está noutro idioma. Por defeito só liga se o manual não estiver em português.")
    chave_falha = f"emb_falhou_{manual.hash}"
    if usar_semantica and indice.matriz is None and not st.session_state.get(chave_falha):
        barra = st.progress(0.0, text="A preparar a pesquisa por significado (só na 1.ª vez)...")
        try:
            indice.matriz = embeddings.obter_matriz(
                manual.hash, indice.chunks, lambda a, b: barra.progress(a / b, text=f"A preparar... {a}/{b}"))
        except Exception as e:
            st.session_state[chave_falha] = str(e)[:300]
        barra.empty()
    if usar_semantica and st.session_state.get(chave_falha):
        st.warning("Pesquisa por significado indisponível; a usar só palavras. " + st.session_state[chave_falha][:150])
        if st.button("Tentar de novo", key="emb_retry"):
            st.session_state.pop(chave_falha, None)
            st.rerun()
    modo_img = st.radio("👁️ A IA vê a página (imagem)", ["Auto", "Sempre", "Nunca"], horizontal=True,
                        disabled=not tem_gemini,
                        help="Auto: a IA lê a imagem da melhor página encontrada (e de páginas só com esquema). "
                             "Sempre: lê as 2 melhores páginas. Nunca: só texto (mais rápido).") if tem_gemini else "Nunca"
    velocidade = st.radio("⚡ Velocidade da IA", ["Rápido", "Preciso"], horizontal=True,
                          help="Rápido: modelo mais leve. Preciso: modelo maior, mais lento. "
                               "Compare os dois no modo Qualidade.") if tem_gemini else "Preciso"
    modelo_sel = config.GEMINI_MODEL_RAPIDO if (tem_gemini and velocidade == "Rápido") else None
    reescrever = st.checkbox("Usar IA para entender perguntas curtas (mais lento)", value=False)

    st.divider()
    st.markdown("**Visualização**")
    pode_traduzir = not manual.idioma.startswith("pt")
    traduzir = st.checkbox("🌐 Traduzir esta página para PT", value=False, disabled=not pode_traduzir,
                           help=None if pode_traduzir else "O manual já está em português.")
    formato = st.radio("Qualidade", ["png", "svg"], format_func=lambda x: "Imagem (rápida)" if x == "png"
                       else "Vetorial (zoom nítido)", horizontal=True)

    # ---- importar avarias antigas (Excel / CSV)
    st.divider()
    with st.expander("📥 Importar avarias (Excel do Manwinwin)"):
        if st.session_state.get("msg_imp"):
            st.success(st.session_state.pop("msg_imp"))
        st.caption("Carregue um Excel (.xlsx) ou CSV com avarias e soluções antigas. "
                   "A app reconhece as colunas; confirme abaixo.")
        fich = st.file_uploader("Excel (.xlsx) ou CSV", type=["xlsx", "xlsm", "csv", "txt"], key="up_av")
        if fich is not None:
            df_imp = None
            try:
                df_imp = importar.ler_tabela(fich.getvalue(), fich.name)
            except Exception as e:
                st.error(f"Não consegui ler o ficheiro: {e}")
            if df_imp is not None:
                colunas = [str(c) for c in df_imp.columns]
                auto = importar.mapear_colunas(colunas)
                opcoes = ["(nenhuma)"] + colunas
                escolhas = {}
                for campo, rotulo in importar.CAMPOS:
                    padrao = auto.get(campo)
                    escolhas[campo] = st.selectbox(
                        rotulo, opcoes, index=opcoes.index(padrao) if padrao in opcoes else 0,
                        key=f"map_{campo}_{fich.name}_{fich.size}")
                st.dataframe(df_imp.head(5), use_container_width=True)
                if escolhas["avaria"] == "(nenhuma)":
                    st.warning("Escolha a coluna com a descrição da avaria.")
                elif st.button(f"Importar {len(df_imp)} linhas", key="btn_importar", use_container_width=True):
                    novos, dup, ign = importar.importar_df(
                        df_imp, {k: (None if v == "(nenhuma)" else v) for k, v in escolhas.items()}, fich.name)
                    st.session_state.msg_imp = (f"{novos} avarias importadas · {dup} já existiam · "
                                                f"{ign} linhas vazias ignoradas.")
                    st.rerun()
        for origem, n in importar.listar_origens():
            with st.container(horizontal=True, horizontal_alignment="space-between", gap="small"):
                st.caption(f"📄 {origem} · {n} avarias")
                if st.button("🗑️", key=f"del_{origem}", help="Apagar esta importação", use_container_width=False):
                    importar.apagar_origem(origem)
                    st.rerun()

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        history.apagar(utilizador, nome_manual)
        st.session_state.mensagens = []
        st.rerun()
    if st.button("🚪 Terminar sessão", use_container_width=True):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

    with st.expander("📊 Feedback registado"):
        est = feedback.estatisticas()
        st.write(f"Respostas registadas: **{est['total']}**")
        for k, v in est["por_resultado"].items():
            st.write(f"- {k}: {v}")
        st.download_button("⬇️ Exportar CSV", feedback.exportar_csv(), "feedback.csv", "text/csv",
                           use_container_width=True)


# ------------------------------------------------------------------ modo qualidade
def _mostrar_resultado(r: dict, ia: bool = False):
    # Métricas em container horizontal responsivo
    with st.container(horizontal=True, horizontal_alignment="distribute", gap="small"):
        if ia:
            st.metric("Cita a página certa", f"{r['hit'] * 100:.0f}%")
            st.metric("Palavras-chave na resposta", f"{r['mrr'] * 100:.0f}%")
            st.metric("Erros da API", r.get("erros", 0))
        else:
            st.metric("Página certa nos trechos", f"{r['hit'] * 100:.0f}%")
            st.metric("Posição média (MRR, 1 = ótimo)", f"{r['mrr']:.2f}")
            st.metric("Casos medidos", r["n"])
    st.dataframe(r["linhas"], use_container_width=True)


def pagina_qualidade():
    st.title("🧪 Qualidade das respostas")
    st.caption("Registe avarias reais já resolvidas, com a página do manual onde está a pista. "
               "Repita o teste antes e depois de cada mudança para ver se melhorou ou piorou.")
    testes = avaliacao.listar_testes(nome_manual)
    with st.expander("➕ Adicionar caso de teste", expanded=not testes):
        with st.form("novo_teste", clear_on_submit=True):
            sint = st.text_area("Sintoma, como o técnico escreveria", height=80,
                                placeholder="ex.: contador de vapor zerado, o tear não conta")
            causa = st.text_input("Causa real (o que era)")
            pag = st.number_input("Página do manual onde está a pista (0 = não sei)", 0, manual.n_paginas, 0)
            palavras = st.text_input("Palavras-chave da solução certa, separadas por vírgula (opcional)",
                                     placeholder="ex.: sensor, X1.3, cabo")
            eq = st.text_input("Equipamento (opcional)")
            if st.form_submit_button("Guardar caso"):
                if sint.strip():
                    avaliacao.adicionar_teste(nome_manual, eq, sint, causa, pag, palavras)
                    st.rerun()
                else:
                    st.warning("Escreva o sintoma.")
    if not testes:
        st.info("Ainda não há casos de teste para este manual. Comece com 10 a 15 avarias reais.")
        return
    st.markdown(f"**{len(testes)} casos de teste** neste manual")
    st.dataframe([{"nº": t["id"], "sintoma": t["sintoma"], "causa real": t["causa_real"],
                   "página certa": t["pagina_esperada"] or "—"} for t in testes], use_container_width=True)
    with st.expander("🗑️ Apagar um caso"):
        alvo = st.selectbox("Caso", [t["id"] for t in testes], format_func=lambda i: next(
            f"{t['id']} – {t['sintoma'][:50]}" for t in testes if t["id"] == i))
        if st.button("Apagar"):
            avaliacao.apagar_teste(alvo)
            st.rerun()

    st.divider()
    st.markdown("#### 1) Teste da pesquisa (grátis e instantâneo)")
    if st.button("▶️ Testar pesquisa", use_container_width=True):
        res = {"Só palavras": avaliacao.avaliar_recuperacao(indice, testes, config.TOP_CHUNKS_MANUAL, False)}
        avaliacao.registar_execucao(nome_manual, "pesquisa: só palavras", res["Só palavras"])
        if usar_semantica and indice.matriz is not None:
            res["Palavras + significado"] = avaliacao.avaliar_recuperacao(
                indice, testes, config.TOP_CHUNKS_MANUAL, True)
            avaliacao.registar_execucao(nome_manual, "pesquisa: palavras + significado", res["Palavras + significado"])
        st.session_state.res_pesquisa = res
    for titulo, r in st.session_state.get("res_pesquisa", {}).items():
        st.markdown(f"**{titulo}**")
        _mostrar_resultado(r)

    st.markdown("#### 2) Teste com a IA (usa a API: 1 pedido por caso)")
    if st.button(f"▶️ Testar com a IA ({len(testes)} pedidos)", use_container_width=True, disabled=not ok_llm):
        barra = st.progress(0.0, text="A testar...")
        r = avaliacao.avaliar_com_ia(testes, manual, indice, base, usar_semantica,
                                     lambda msgs: llm.gerar(msgs, modelo=modelo_sel),
                                     progresso=lambda a, b: barra.progress(a / b, text=f"{a}/{b}"))
        barra.empty()
        avaliacao.registar_execucao(nome_manual, "IA", r)
        st.session_state.res_ia = r
    if st.session_state.get("res_ia"):
        _mostrar_resultado(st.session_state.res_ia, ia=True)

    hist = avaliacao.listar_execucoes(nome_manual)
    if hist:
        st.markdown("#### Histórico de testes")
        st.dataframe(hist, use_container_width=True)


if modo == "🧪 Qualidade":
    pagina_qualidade()
    st.stop()

# ------------------------------------------------------------------ estado da conversa
if "mensagens" not in st.session_state or st.session_state.get("_manual_atual") != (utilizador, nome_manual):
    st.session_state._manual_atual = (utilizador, nome_manual)
    st.session_state.mensagens = history.carregar(utilizador, nome_manual)
    st.session_state.pagina = 1
mensagens: list[dict] = st.session_state.mensagens


def _ir_pagina(p: int):
    st.session_state.pagina = int(p)


def _guardar():
    history.guardar(utilizador, nome_manual, mensagens)


def _pouco_texto(p: int) -> bool:
    return len(manual.textos[p - 1].split()) < 150


pergunta = st.chat_input(
    "Descreva o problema (ex.: 'erro -999 na sonda do tear 3; já medi a continuidade e está boa')",
    submit_mode="disable"  # Disable input while response is streaming
)

# Layout responsivo: usa container horizontal que empilha no mobile
# No desktop: chat à esquerda, esquema à direita
# No mobile: empilha verticalmente (chat em cima, esquema embaixo)
with st.container(horizontal=True, horizontal_alignment="distribute", gap="medium") as layout_cols:
    # Painel esquerdo: Chat (Diagnóstico)
    with st.container(border=True):
        st.subheader("💬 Diagnóstico")
        st.caption("O assistente apenas **sugere**. Valide sempre no esquema e siga o procedimento de segurança.")
        
        for i, msg in enumerate(mensagens):
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant" and msg.get("busca"):
                    st.caption(msg["busca"])
                st.markdown(msg["content"])
                if msg["role"] != "assistant":
                    continue
                if msg.get("info"):
                    st.caption(msg["info"])
                if msg.get("aviso"):
                    st.warning(diagnosis.AVISO_SEGURANCA)
                if msg.get("paginas_img"):
                    st.caption("👁️ A IA viu também como imagem: " + ", ".join(f"p.{p}" for p in msg["paginas_img"]))
                if msg.get("paginas"):
                    # Botões de página responsivos
                    paginas_mostrar = msg["paginas"][:5]
                    cols_pag = st.columns(len(paginas_mostrar) + 1)
                    cols_pag[0].caption("Abrir:")
                    for c, p in zip(cols_pag[1:], paginas_mostrar):
                        c.button(f"📄 p.{p}", key=f"pg_{i}_{p}", on_click=_ir_pagina, args=(p,), use_container_width=True)
                if msg.get("casos"):
                    with st.expander(f"📚 {len(msg['casos'])} casos parecidos já resolvidos"):
                        for c in msg["casos"]:
                            st.markdown(f"**{c['id']}** · {c['data']} · {c['equipamento']}  \n"
                                        f"Avaria: {c['avaria']}  \nCausa: {c['causa'] or '—'}  \n"
                                        f"Solução: {c['solucao'] or '—'}")
                # --- feedback
                if msg.get("fb_id"):
                    if msg.get("avaliacao"):
                        rot = {"resolveu": "✅ resolveu", "parcial": "🟡 ajudou em parte", "nao_resolveu": "❌ não resolveu"}
                        st.caption(f"Avaliação: {rot[msg['avaliacao']]}")
                    else:
                        pend = st.session_state.get("fb_pendente")
                        if pend and pend[0] == i:
                            with st.form(f"fbf_{i}"):
                                st.markdown("**O que foi realmente?** (ajuda os colegas e melhora o sistema)")
                                causa = st.text_input("Causa real", key=f"causa_{i}")
                                solucao = st.text_area("O que fez para resolver", key=f"sol_{i}", height=80)
                                ok = st.form_submit_button("Guardar avaliação", use_container_width=True)
                                if ok:
                                    feedback.avaliar(msg["fb_id"], pend[1], causa, solucao)
                                    msg["avaliacao"] = pend[1]
                                    st.session_state.pop("fb_pendente", None)
                                    _guardar()
                                    st.rerun()
                        else:
                            b1, b2, b3 = st.columns(3)
                            for col, (res, rot) in zip((b1, b2, b3), (("resolveu", "✅ Resolveu"),
                                                                  ("parcial", "🟡 Em parte"),
                                                                  ("nao_resolveu", "❌ Não resolveu"))):
                                if col.button(rot, key=f"fb_{res}_{i}", use_container_width=True):
                                    st.session_state.fb_pendente = (i, res)
                                    st.rerun()

    # Painel direito: Esquema / Manual
    with st.container(border=True):
        st.subheader("📐 Esquema / Manual")
        
        # Navegação de página responsiva
        n = manual.n_paginas
        st.session_state.pagina = min(max(int(st.session_state.get("pagina", 1)), 1), n)
        c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="center")
        c1.button("⬅️", on_click=_ir_pagina, args=(st.session_state.pagina - 1,),
                  disabled=st.session_state.pagina <= 1, use_container_width=True)
        c2.number_input("Página", 1, n, key="pagina", label_visibility="collapsed")
        c3.button("➡️", on_click=_ir_pagina, args=(st.session_state.pagina + 1,),
                  disabled=st.session_state.pagina >= n, use_container_width=True)
        
        pag = st.session_state.pagina
        if pag in manual.paginas_sem_texto:
            st.caption("Esta página não tem texto extraível (só desenho): "
                       + ("a IA vê-a como imagem." if tem_gemini and modo_img != "Nunca" else "a IA não a consegue ler, mas pode vê-la aqui."))
        try:
            with st.spinner("A preparar a página..." + (" (a traduzir)" if traduzir else "")):
                dados, mime, blocos = _pagina_renderizada(
                    str(manual.caminho), manual.hash, pag, config.ZOOM_RENDER, formato,
                    bool(traduzir and pode_traduzir), manual.idioma, config.LLM_PROVIDER)
            
            # Altura responsiva do viewer: 640px desktop, 400px mobile (via CSS)
            viewer_height = 640
            components.html(viewer.html_visualizador(dados, mime, viewer_height), height=viewer_height + 10)
            
            if blocos:
                with st.expander("Texto traduzido desta página"):
                    for b in blocos:
                        st.markdown(f"- {b['texto']}  →  **{b.get('traducao', '')}**")
        except Exception as e:
            st.error(f"Não consegui mostrar a página: {e}")

    # --------------------------------------------------------------- nova pergunta
    if pergunta:
                    pend = st.session_state.get("fb_pendente")
                    if pend and pend[0] == i:
                        with st.form(f"fbf_{i}"):
                            st.markdown("**O que foi realmente?** (ajuda os colegas e melhora o sistema)")
                            causa = st.text_input("Causa real", key=f"causa_{i}")
                            solucao = st.text_area("O que fez para resolver", key=f"sol_{i}", height=80)
                            ok = st.form_submit_button("Guardar avaliação")
                            if ok:
                                feedback.avaliar(msg["fb_id"], pend[1], causa, solucao)
                                msg["avaliacao"] = pend[1]
                                st.session_state.pop("fb_pendente", None)
                                _guardar()
                                st.rerun()
                    else:
                        b1, b2, b3 = st.columns(3)
                        for col, (res, rot) in zip((b1, b2, b3), (("resolveu", "✅ Resolveu"),
                                                                 ("parcial", "🟡 Em parte"),
                                                                 ("nao_resolveu", "❌ Não resolveu"))):
                            if col.button(rot, key=f"fb_{res}_{i}", use_container_width=True):
                                st.session_state.fb_pendente = (i, res)
                                st.rerun()

    # --------------------------------------------------------------- nova pergunta
    if pergunta:
        with st.chat_message("user"):
            st.markdown(pergunta)
        hist_antes = list(mensagens)
        mensagens.append({"role": "user", "content": pergunta})
        estado_img = {"paginas": []}

        def escolher_imagens(trechos):
            """A IA lê a imagem da melhor página encontrada (e de páginas só com esquema); máx. 2."""
            paginas = diagnosis.escolher_paginas_imagem(int(st.session_state.pagina), trechos, manual.textos, modo_img)
            imgs, ok_pags = [], []
            for p in paginas:
                try:
                    imgs.append(("image/png", _imagem_para_ia(str(manual.caminho), p)))
                    ok_pags.append(p)
                except Exception:
                    pass
            estado_img["paginas"] = ok_pags
            return imgs, ok_pags

        with st.chat_message("assistant"):
            t0 = time.time()
            with st.spinner("A ver as palavras da pergunta e a procurar no manual..."):
                msgs, trechos, casos = diagnosis.preparar(
                    pergunta, hist_antes, manual, indice, base, equipamento, semantica=usar_semantica,
                    usar_llm_reescrita=reescrever and ok_llm, escolher_imagens=escolher_imagens)
            t_busca = time.time() - t0
            paginas_busca = []
            for ch, _ in trechos:
                if ch.meta["pagina"] not in paginas_busca:
                    paginas_busca.append(ch.meta["pagina"])
            palavras, extra = textutil.palavras_chave(pergunta)
            busca_txt = ("🔎 Procurei: " + " · ".join(palavras)
                         + (f"  (+ {', '.join(extra)})" if extra else "")
                         + (" → encontrei nas páginas " + ", ".join(f"p.{p}" for p in paginas_busca[:4])
                            if paginas_busca else " → nada encontrado no manual"))
            st.caption(busca_txt)
            casos_resumo = [{"id": c.id, "data": c.data,
                             "equipamento": c.equipamento, "avaria": c.avaria, "causa": c.causa,
                             "solucao": c.solucao} for c, _ in casos]
            t_llm = time.time()
            marcas = {}

            def _fluxo():
                for parte in llm.gerar_stream(msgs, modelo=modelo_sel):
                    marcas.setdefault("primeira", time.time() - t_llm)
                    yield parte

            try:
                resposta = st.write_stream(_fluxo())
                erro = None
            except llm.LLMErro as e:
                resposta, erro = "", str(e)

            if erro or not resposta.strip():
                excertos = "\n\n".join(
                    f"**[Manual p.{c.meta['pagina']}]** {c.texto[:400]}…" for c, _ in trechos[:3]) or "(nada encontrado no manual)"
                resposta = ("⚠️ A IA está temporariamente indisponível (" + (erro or "resposta vazia")[:160] + "). "
                            "Tente de novo daqui a alguns segundos. Entretanto, isto é o que encontrei no manual:\n\n" + excertos)
                st.markdown(resposta)

            t_total = t_busca + (time.time() - t_llm)
            info = f"⏱ pesquisa {t_busca:.1f}s · 1.ª palavra {marcas.get('primeira', 0) + t_busca:.1f}s · total {t_total:.1f}s"
            info_llm = llm.ultimo_info() or {}
            if info_llm.get("modelo"):
                info += f" · {info_llm['modelo']}" + (f" (depois de {info_llm['falhas']} falhas)" if info_llm.get("falhas") else "")
            if estado_img["paginas"]:
                info += f" · {len(estado_img['paginas'])} imagem(ns)"
            st.caption(info)
            citadas = diagnosis.paginas_citadas(resposta, manual.n_paginas)
            paginas = citadas or paginas_busca[:3]
            falhou = bool(erro) or resposta.startswith("⚠️")
            fb_id = None if falhou else feedback.registar_resposta(
                utilizador, manual.nome, equipamento, pergunta, resposta, paginas, [c["id"] for c in casos_resumo])
            mensagens.append({
                "role": "assistant", "content": resposta, "paginas": paginas, "casos": casos_resumo,
                "fb_id": fb_id, "aviso": diagnosis.precisa_aviso_seguranca(resposta),
                "paginas_img": estado_img["paginas"], "busca": busca_txt, "info": info,
            })
            if paginas:   # aplicado no início da próxima execução (o widget já foi criado nesta)
                st.session_state.pagina_pendente = paginas[0]
            _guardar()
        st.rerun()
