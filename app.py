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
LLM_TIMEOUT_S = int(obter("LLM_TIMEOUT_S", "180"))
LLM_MAX_TOKENS = int(obter("LLM_MAX_TOKENS", "1400"))

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

# ----------------------- core/casos.py -----------------------
_FONTES['casos'] = r'''
"""Histórico de avarias do próprio sistema: casos validados pelos técnicos (botão 'Resolveu')."""
from __future__ import annotations

from dataclasses import dataclass, field

from .search import Chunk, Indice


@dataclass
class Caso:
    id: str
    origem: str            # "Feedback"
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

# ----------------------- core/llm.py -----------------------
_FONTES['llm'] = r'''
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
        "generationConfig": {"temperature": temperatura, "maxOutputTokens": max(max_tokens, 4096)},  # folga: o "pensar" do modelo conta aqui
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
from .search import Chunk, Indice, dividir_em_chunks


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

    def construir_indice(self) -> Indice:
        chunks: list[Chunk] = []
        for i, t in enumerate(self.textos, start=1):
            for parte in dividir_em_chunks(t, config.CHUNK_PALAVRAS, config.CHUNK_SOBREPOSICAO):
                chunks.append(Chunk(parte, {"pagina": i}))
        return Indice(chunks)


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

Princípio: o sistema SUGERE, nunca ordena. Só afirma o que está nas fontes (manual e casos
validados por técnicos) ou rotula como conhecimento geral a confirmar.
"""
from __future__ import annotations

import re

from . import llm
from .casos import Caso
from .search import Chunk, reescrever_consulta_simples

PROMPT_SISTEMA = """És um assistente de apoio ao diagnóstico para técnicos de manutenção de máquinas têxteis e quadros elétricos. Falas Português de Portugal industrial (bornes, malha, disjuntor, cartão analógico).

O TEU PAPEL: SUGERIR, nunca decidir nem ordenar. O técnico é quem decide e executa; um erro teu pode causar danos ou acidentes.

REGRAS OBRIGATÓRIAS
1. Usa APENAS as fontes fornecidas: trechos do manual e casos já resolvidos e validados por técnicos. O conhecimento geral só pode aparecer rotulado como "(conhecimento geral – confirmar)".
2. NUNCA inventes bornes, pinos, referências, valores de tensão ou parâmetros. Se o manual não o indica, diz exatamente: "Não encontrei isso no manual fornecido."
3. Formula sempre como recomendação ou pergunta, por exemplo: "O que acha de medir a tensão entre os bornes X1.1 e X1.2? Deve rondar 24 V segundo [Manual p.12]." Nunca uses imperativos secos.
4. Cita a origem de cada afirmação: [Manual p.N] para o manual, [FBid] para casos validados por técnicos.
5. Lê a conversa: não repitas testes que o técnico já fez; avança para a hipótese seguinte.
6. Se vários casos antigos apontam a mesma causa, diz quantos e com que frequência; se são só vagamente parecidos, di-lo.
7. Os trechos do manual podem estar noutro idioma (inglês, alemão...). Responde sempre em português e traduz os termos técnicos.
8. Se a informação for insuficiente, faz UMA pergunta curta ao técnico (modelo da máquina, código de erro, o que mudou) em vez de adivinhar.

FORMATO (curto, sem enrolar)
**Leitura do problema:** 1–2 frases.
**Hipóteses (da mais para a menos provável):** lista numerada, cada uma com o porquê e a fonte.
**Próximo passo sugerido:** UM só passo, em forma de pergunta/recomendação, de preferência o mais simples e seguro primeiro (inspeção visual, ligações, fusíveis) antes de medições.
**Fontes consultadas:** lista curta."""

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
        etiqueta = c.id
        linhas.append(
            f"[{etiqueta}] {c.data} | Equip.: {c.equipamento or '?'} | Avaria: {c.avaria or '?'} | "
            f"Causa: {c.causa or 'não registada'} | Solução: {c.solucao or 'não registada'}"
            + (" | VALIDADO por técnico" if c.origem == "Feedback" else "")
        )
    return "\n".join(linhas)


def montar_mensagens(pergunta: str, historico: list[dict], trechos, casos, manual_nome: str,
                     equipamento: str | None, idioma_manual: str, max_hist: int = 6) -> list[dict]:
    contexto = (
        f"MANUAL: {manual_nome} (idioma: {idioma_manual})\n"
        f"EQUIPAMENTO: {equipamento or 'não indicado'}\n\n"
        f"TRECHOS DO MANUAL:\n{formatar_trechos(trechos)}\n\n"
        f"CASOS PARECIDOS JÁ RESOLVIDOS:\n{formatar_casos(casos)}\n\n"
        f"MENSAGEM ATUAL DO TÉCNICO: {pergunta}"
    )
    msgs = [{"role": "system", "content": PROMPT_SISTEMA}]
    for m in historico[-max_hist:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": contexto})
    return msgs


def reescrever_consulta(pergunta: str, historico: list[dict], usar_llm: bool = True) -> str:
    """'E agora?' sozinho não pesquisa nada: junta contexto da conversa numa consulta autónoma."""
    if not historico:
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


def paginas_citadas(resposta: str, n_paginas: int) -> list[int]:
    pags = []
    for m in re.finditer(r"\[Manual p\.?\s*(\d+)\]", resposta, re.IGNORECASE):
        p = int(m.group(1))
        if 1 <= p <= n_paginas and p not in pags:
            pags.append(p)
    return pags
'''

_ORDEM = ['config', 'textutil', 'auth', 'search', 'casos', 'feedback', 'llm', 'history', 'pdf_store', 'translate', 'viewer', 'diagnosis']
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
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core import auth, casos as mod_casos, config, diagnosis, feedback, history, llm, pdf_store, translate, viewer

st.set_page_config(page_title="Assistente MGC", page_icon="⚡", layout="wide")

st.markdown("""
<style>
 .stApp{background:#050810;background-image:radial-gradient(circle at top right,#0a1128 0%,#050810 100%);color:#e2e8f0}
 section[data-testid="stSidebar"]{background:rgba(10,15,30,.9);border-right:1px solid rgba(56,189,248,.2)}
 h1,h2,h3{color:#38bdf8!important}
 div[data-testid="stChatMessage"]{background:rgba(30,41,59,.65);border:1px solid rgba(255,255,255,.05);border-radius:12px}
 .stButton button{border-radius:8px;font-weight:600}
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
    st.markdown("<h1 style='text-align:center'>⚡ Assistente MGC</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#94a3b8'>Apoio ao diagnóstico de avarias</p>", unsafe_allow_html=True)
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        with st.form("login"):
            if config.LISTA_TECNICOS:
                nome = st.selectbox("Técnico", config.LISTA_TECNICOS)
            else:
                nome = st.text_input("Nome do técnico")
            pin = st.text_input("PIN de acesso", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
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
    return len(feedback.casos_validados())


@st.cache_resource(show_spinner="A carregar casos resolvidos...")
def _base_casos(assinatura):
    return mod_casos.BaseCasos(feedback.casos_validados())


@st.cache_data(show_spinner=False, max_entries=12)
def _pagina_renderizada(caminho: str, hash_manual: str, pagina: int, zoom: float, formato: str,
                        traduzir: bool, idioma: str, provider: str):
    blocos = translate.traduzir_pagina(Path(caminho), hash_manual, pagina, idioma) if traduzir else None
    dados, mime = viewer.renderizar_pagina(caminho, pagina, zoom, blocos, formato)
    return dados, mime, blocos


@st.cache_data(ttl=30, show_spinner=False)
def _estado_llm(_chave: int):
    return llm.estado()


# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.markdown(f"### 👤 {utilizador}")
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
    st.caption(f"Casos resolvidos registados: {len(base.casos)}")

    ok_llm, msg_llm = _estado_llm(0)
    (st.success if ok_llm else st.error)("🧠 " + msg_llm)

    st.divider()
    st.markdown("**Visualização**")
    pode_traduzir = not manual.idioma.startswith("pt")
    traduzir = st.checkbox("🌐 Traduzir esta página para PT", value=False, disabled=not pode_traduzir,
                           help=None if pode_traduzir else "O manual já está em português.")
    formato = st.radio("Qualidade", ["png", "svg"], format_func=lambda x: "Imagem (rápida)" if x == "png"
                       else "Vetorial (zoom nítido)", horizontal=True)
    reescrever = st.checkbox("Usar IA para entender 'e agora?' (mais lento)", value=True)

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        history.apagar(utilizador, nome_manual)
        st.session_state.pop("mensagens", None)
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

# ------------------------------------------------------------------ estado da conversa
if st.session_state.get("_manual_atual") != (utilizador, nome_manual):
    st.session_state._manual_atual = (utilizador, nome_manual)
    st.session_state.mensagens = history.carregar(utilizador, nome_manual)
    st.session_state.pagina = 1
mensagens: list[dict] = st.session_state.mensagens


def _ir_pagina(p: int):
    st.session_state.pagina = int(p)


def _guardar():
    history.guardar(utilizador, nome_manual, mensagens)


pergunta = st.chat_input("Descreva o problema (ex.: 'erro -999 na sonda do tear 3; já medi a continuidade e está boa')")

col_chat, col_ver = st.columns([5, 6], gap="medium")

# ------------------------------------------------------------------ painel direito: esquema
if "pagina_pendente" in st.session_state:
    st.session_state.pagina = st.session_state.pop("pagina_pendente")

with col_ver:
    st.subheader("📐 Esquema / Manual")
    n = manual.n_paginas
    st.session_state.pagina = min(max(int(st.session_state.get("pagina", 1)), 1), n)
    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button("⬅️", on_click=_ir_pagina, args=(st.session_state.pagina - 1,),
              disabled=st.session_state.pagina <= 1, use_container_width=True)
    c2.number_input("Página", 1, n, key="pagina", label_visibility="collapsed")
    c3.button("➡️", on_click=_ir_pagina, args=(st.session_state.pagina + 1,),
              disabled=st.session_state.pagina >= n, use_container_width=True)
    pag = st.session_state.pagina
    if pag in manual.paginas_sem_texto:
        st.caption("Esta página não tem texto extraível (só desenho): a IA não a consegue ler, mas pode vê-la aqui.")
    try:
        with st.spinner("A preparar a página..." + (" (a traduzir)" if traduzir else "")):
            dados, mime, blocos = _pagina_renderizada(
                str(manual.caminho), manual.hash, pag, config.ZOOM_RENDER, formato,
                bool(traduzir and pode_traduzir), manual.idioma, config.LLM_PROVIDER)
        components.html(viewer.html_visualizador(dados, mime, 640), height=650)
        if blocos:
            with st.expander("Texto traduzido desta página"):
                for b in blocos:
                    st.markdown(f"- {b['texto']}  →  **{b.get('traducao', '')}**")
    except Exception as e:
        st.error(f"Não consegui mostrar a página: {e}")

# ------------------------------------------------------------------ painel esquerdo: conversa
with col_chat:
    st.subheader("💬 Diagnóstico")
    st.caption("O assistente apenas **sugere**. Valide sempre no esquema e siga o procedimento de segurança.")

    for i, msg in enumerate(mensagens):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] != "assistant":
                continue
            if msg.get("aviso"):
                st.warning(diagnosis.AVISO_SEGURANCA)
            if msg.get("paginas"):
                cols = st.columns(min(len(msg["paginas"]), 5) + 1)
                cols[0].caption("Abrir:")
                for c, p in zip(cols[1:], msg["paginas"][:5]):
                    c.button(f"📄 p.{p}", key=f"pg_{i}_{p}", on_click=_ir_pagina, args=(p,))
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

        with st.chat_message("assistant"):
            with st.spinner("A consultar o manual e os casos resolvidos..."):
                consulta = diagnosis.reescrever_consulta(pergunta, hist_antes, usar_llm=reescrever and ok_llm)
                trechos = indice.procurar(consulta, k=config.TOP_CHUNKS_MANUAL)
                casos = base.procurar(consulta, equipamento, k=config.TOP_CASOS)
            msgs = diagnosis.montar_mensagens(pergunta, hist_antes, trechos, casos, manual.nome,
                                              equipamento, manual.idioma)
            paginas_busca = []
            for ch, _ in trechos:
                if ch.meta["pagina"] not in paginas_busca:
                    paginas_busca.append(ch.meta["pagina"])
            casos_resumo = [{"id": c.id, "data": c.data,
                             "equipamento": c.equipamento, "avaria": c.avaria, "causa": c.causa,
                             "solucao": c.solucao} for c, _ in casos]
            try:
                resposta = st.write_stream(llm.gerar_stream(msgs))
                erro = None
            except llm.LLMErro as e:
                resposta, erro = "", str(e)

            if erro or not resposta.strip():
                resposta = ("⚠️ O modelo de IA não respondeu (" + (erro or "resposta vazia") + "). "
                            "Mostro-lhe apenas o que encontrei no manual e nos casos resolvidos — consulte as páginas e os casos abaixo.")
                st.markdown(resposta)

            citadas = diagnosis.paginas_citadas(resposta, manual.n_paginas)
            paginas = citadas or paginas_busca[:3]
            fb_id = feedback.registar_resposta(utilizador, manual.nome, equipamento, pergunta, resposta,
                                               paginas, [c["id"] for c in casos_resumo])
            mensagens.append({
                "role": "assistant", "content": resposta, "paginas": paginas, "casos": casos_resumo,
                "fb_id": fb_id, "aviso": diagnosis.precisa_aviso_seguranca(resposta),
            })
            if paginas:   # aplicado no início da próxima execução (o widget já foi criado nesta)
                st.session_state.pagina_pendente = paginas[0]
            _guardar()
        st.rerun()
