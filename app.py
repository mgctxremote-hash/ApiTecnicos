"""Assistente MGC – Diagnóstico de avarias com Manual + Histórico ManWinWin + Feedback (Google Gemini API)."""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from rank_bm25 import BM25Okapi

# ------------------------------------------------------------------ CONFIGURAÇÃO DE PÁGINA & ESTILO
st.set_page_config(page_title="Assistente MGC", page_icon="⚡", layout="wide")

st.markdown("""
<style>
 .stApp{background:#050810;background-image:radial-gradient(circle at top right,#0a1128 0%,#050810 100%);color:#e2e8f0}
 section[data-testid="stSidebar"]{background:rgba(10,15,30,.92);border-right:1px solid rgba(56,189,248,.2)}
 h1,h2,h3{color:#38bdf8!important}
 div[data-testid="stChatMessage"]{background:rgba(30,41,59,.65);border:1px solid rgba(255,255,255,.06);border-radius:12px}
 .stButton button{border-radius:8px;font-weight:600}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ CONSTANTES E DIRETÓRIOS
PIN_ACESSO_PADRAO = "tecnicos4321"

PASTA_MANUAIS = Path("manuais")
PASTA_DATA = Path("data")
PASTA_MANWINWIN = PASTA_DATA / "manwinwin"
PASTA_HISTORY = PASTA_DATA / "history"
FICHEIRO_FEEDBACK = PASTA_DATA / "feedback.json"
FICHEIRO_KEY_LOCAL = Path(".google_key.json")

for pasta in (PASTA_MANUAIS, PASTA_DATA, PASTA_MANWINWIN, PASTA_HISTORY):
    pasta.mkdir(parents=True, exist_ok=True)

LISTA_TECNICOS = ["Bruno Silva", "Alexandre Pimenta", "João Faria", "Outro técnico..."]
ZOOM_RENDER = 2.5
TOP_CHUNKS_MANUAL = 6
TOP_CASOS_MANWINWIN = 4
AVISO_SEGURANCA = (
    "⚠️ **Segurança Industrial:** O assistente apenas sugere hipóteses. "
    "Confirme sempre no esquema elétrico, aplique consignação (LOTO) e verifique ausência de tensão/pressão antes de intervir."
)
CACHE_TRADUCOES: dict[str, str] = {}


# ------------------------------------------------------------------ CREDENCIAIS E SEGURANÇA
def obter_pin_acesso() -> str:
    try:
        if "PIN_ACESSO" in st.secrets and str(st.secrets["PIN_ACESSO"]).strip():
            return str(st.secrets["PIN_ACESSO"]).strip()
    except Exception:
        pass
    return os.environ.get("PIN_ACESSO", PIN_ACESSO_PADRAO).strip()


def obter_google_api_key() -> str:
    # 1. Prioridade máxima: chave introduzida diretamente no site nesta sessão
    chave_sessao = str(st.session_state.get("google_api_key_site", "")).strip()
    if chave_sessao:
        return chave_sessao

    # 2. Ficheiro local guardado pelo site
    if FICHEIRO_KEY_LOCAL.exists():
        try:
            dados = json.loads(FICHEIRO_KEY_LOCAL.read_text(encoding="utf-8"))
            if dados.get("google_api_key"):
                return str(dados["google_api_key"]).strip()
        except Exception:
            pass

    # 3. Secrets do Streamlit Cloud ou variáveis de ambiente (opcional)
    for nome_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        try:
            if nome_var in st.secrets and str(st.secrets[nome_var]).strip():
                return str(st.secrets[nome_var]).strip()
        except Exception:
            pass
        val_env = os.environ.get(nome_var, "").strip()
        if val_env:
            return val_env

    return ""


def guardar_google_api_key(chave: str) -> None:
    limpa = chave.strip()
    st.session_state["google_api_key_site"] = limpa
    try:
        FICHEIRO_KEY_LOCAL.write_text(json.dumps({"google_api_key": limpa}), encoding="utf-8")
    except Exception:
        pass


def remover_google_api_key() -> None:
    st.session_state.pop("google_api_key_site", None)
    try:
        if FICHEIRO_KEY_LOCAL.exists():
            FICHEIRO_KEY_LOCAL.unlink()
    except Exception:
        pass


def criar_token(nome: str) -> str:
    segredo = obter_pin_acesso().encode("utf-8")
    assinatura = hmac.new(segredo, nome.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{nome}|{assinatura}".encode("utf-8")).decode("ascii")


def validar_token(token: str) -> str | None:
    try:
        decodificado = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        nome, assinatura = decodificado.rsplit("|", 1)
        segredo = obter_pin_acesso().encode("utf-8")
        esperada = hmac.new(segredo, nome.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(assinatura, esperada) and nome.strip():
            return nome.strip()
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ SESSÃO / LOGIN PERSISTENTE
if "utilizador" not in st.session_state:
    token_url = st.query_params.get("t", "")
    st.session_state.utilizador = validar_token(token_url) if token_url else None

if not st.session_state.utilizador:
    st.markdown("<h1 style='text-align:center'>⚡ Assistente MGC</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#94a3b8'>Apoio ao diagnóstico de avarias e esquemas técnicos</p>", unsafe_allow_html=True)
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        with st.form("login"):
            escolha_tec = st.selectbox("Técnico", LISTA_TECNICOS)
            nome_custom = st.text_input("Nome de Utilizador (se escolheu 'Outro técnico...')")
            pin = st.text_input("Chave de Acesso MGC", type="password")

            chave_existente = obter_google_api_key()
            api_key_login = ""
            if not chave_existente:
                api_key_login = st.text_input(
                    "Google Gemini API Key (opcional — também pode colocar depois na barra lateral)",
                    type="password",
                    placeholder="Cole aqui a sua chave da Google...",
                )

            if st.form_submit_button("Entrar no Sistema", use_container_width=True):
                nome_final = nome_custom.strip() if escolha_tec == "Outro técnico..." else escolha_tec
                if not nome_final:
                    st.error("Indique o nome do técnico.")
                elif pin.strip() != obter_pin_acesso():
                    st.error("Chave de Acesso MGC incorreta.")
                else:
                    if api_key_login.strip():
                        guardar_google_api_key(api_key_login.strip())
                    st.session_state.utilizador = nome_final
                    st.query_params["t"] = criar_token(nome_final)
                    st.rerun()
    st.stop()

utilizador: str = st.session_state.utilizador


# ------------------------------------------------------------------ MOTOR LLM (GOOGLE GEMINI REST + STREAMING)
def _abrir_pedido_google(url_sem_key: str, chave: str, payload_bytes: bytes | None = None, timeout: int = 25):
    """Autentica via ?key= e, caso seja um token OAuth/Cloud (não-AIza), tenta Bearer automaticamente."""
    sep = "&" if "?" in url_sem_key else "?"
    url_com_key = f"{url_sem_key}{sep}key={urllib.parse.quote(chave)}"
    headers_base = {"User-Agent": "AssistenteMGC/1.0"}
    if payload_bytes is not None:
        headers_base["Content-Type"] = "application/json"

    req1 = urllib.request.Request(
        url_com_key,
        data=payload_bytes,
        headers=headers_base,
        method="POST" if payload_bytes is not None else "GET",
    )
    try:
        return urllib.request.urlopen(req1, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403) and not chave.startswith("AIza"):
            headers_bearer = dict(headers_base)
            headers_bearer["Authorization"] = f"Bearer {chave}"
            req2 = urllib.request.Request(
                url_sem_key,
                data=payload_bytes,
                headers=headers_bearer,
                method="POST" if payload_bytes is not None else "GET",
            )
            return urllib.request.urlopen(req2, timeout=timeout)
        raise


@st.cache_data(ttl=120, show_spinner=False)
def listar_modelos_gemini(api_key: str) -> tuple[list[str], str]:
    if not api_key:
        return [], "Sem chave API configurada."
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    try:
        with _abrir_pedido_google(url, api_key, timeout=10) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        validos = []
        bloqueados = ("embedding", "aqa", "imagen", "veo", "tts", "robotics", "computer-use")
        for m in dados.get("models", []):
            nome_raw = m.get("name", "")
            metodos = m.get("supportedGenerationMethods", [])
            nome_limpo = nome_raw.replace("models/", "")
            if "generateContent" in metodos and "gemini" in nome_limpo.lower():
                if not any(b in nome_limpo.lower() for b in bloqueados):
                    validos.append(nome_limpo)

        def _prioridade(n: str) -> int:
            nl = n.lower()
            if "2.5-flash" in nl and "lite" not in nl:
                return 0
            if "2.0-flash" in nl and "lite" not in nl:
                return 1
            if "1.5-flash" in nl:
                return 2
            if "flash" in nl:
                return 3
            if "pro" in nl:
                return 4
            return 5

        validos.sort(key=_prioridade)
        if not validos:
            return [], "Nenhum modelo Gemini disponível nesta conta."
        return validos, ""
    except urllib.error.HTTPError as e:
        return [], f"Erro HTTP {e.code} na chave Google (verifique se a chave é válida em aistudio.google.com/apikey)."
    except Exception as e:
        return [], f"Erro de ligação: {e}"


def estado_llm() -> tuple[bool, str]:
    chave = obter_google_api_key()
    if not chave:
        return False, "Insira a Google API Key abaixo para ativar a IA."
    modelos, erro = listar_modelos_gemini(chave)
    if not modelos:
        return False, erro or "Chave Google inválida ou sem ligação."
    return True, f"Google Gemini ativo ({modelos[0]})"


def _converter_mensagens_gemini(msgs: list[dict]) -> tuple[str, list[dict]]:
    system_parts = []
    contents = []
    for m in msgs:
        role = m.get("role", "user")
        texto = m.get("content", "")
        if not texto:
            continue
        if role == "system":
            system_parts.append(texto)
        else:
            g_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == g_role:
                contents[-1]["parts"][0]["text"] += "\n\n" + texto
            else:
                contents.append({"role": g_role, "parts": [{"text": texto}]})
    return "\n\n".join(system_parts), contents


def gerar_stream_gemini(msgs: list[dict], temperatura: float = 0.2):
    chave = obter_google_api_key()
    if not chave:
        raise RuntimeError("Insira a sua Google Gemini API Key na barra lateral.")
    modelos, _ = listar_modelos_gemini(chave)
    if not modelos:
        modelos = ["gemini-2.5-flash", "gemini-2.0-flash"]
    system_instruction, contents = _converter_mensagens_gemini(msgs)

    payload_dict: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperatura,
            "maxOutputTokens": 950,
        },
    }
    if system_instruction:
        payload_dict["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    ultimo_erro = "Sem resposta dos modelos."

    for modelo in modelos[:4]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:streamGenerateContent?alt=sse"
        try:
            emitiu = False
            with _abrir_pedido_google(url, chave, payload_bytes=payload_bytes, timeout=30) as resp:
                for raw_line in resp:
                    linha = raw_line.decode("utf-8", errors="ignore").strip()
                    if not linha.startswith("data:"):
                        continue
                    json_str = linha[5:].strip()
                    if not json_str or json_str == "[DONE]":
                        continue
                    chunk = json.loads(json_str)
                    for cand in chunk.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            txt = part.get("text", "")
                            if txt:
                                emitiu = True
                                yield txt
            if emitiu:
                return
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", errors="ignore")[:180]
            ultimo_erro = f"HTTP {e.code} ({modelo}): {detalhe}"
            continue
        except Exception as e:
            ultimo_erro = f"{modelo}: {e}"
            continue

    raise RuntimeError(ultimo_erro)


def gerar_texto_gemini(msgs: list[dict], temperatura: float = 0.1) -> str:
    return "".join(list(gerar_stream_gemini(msgs, temperatura=temperatura)))


# ------------------------------------------------------------------ TRADUÇÃO (PT-PT)
def traduzir_texto_pt(texto: str, retornar_idioma: bool = False):
    texto_limpo = texto.strip()
    if not texto_limpo:
        return ("", "pt") if retornar_idioma else ""
    if not retornar_idioma and texto_limpo in CACHE_TRADUCOES:
        return CACHE_TRADUCOES[texto_limpo]

    blocos = [texto_limpo[i : i + 950] for i in range(0, len(texto_limpo), 950)]
    resultado = []
    idioma_det = "pt"
    try:
        for bloco in blocos:
            url = (
                "https://translate.googleapis.com/translate_a/single?client=gtx"
                f"&sl=auto&tl=pt-PT&dt=t&q={urllib.parse.quote(bloco)}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
                resultado.append("".join(p[0] for p in dados[0] if p[0]))
                if len(dados) > 2 and dados[2]:
                    idioma_det = str(dados[2]).lower()
        final = "".join(resultado)
        CACHE_TRADUCOES[texto_limpo] = final
        return (final, idioma_det) if retornar_idioma else final
    except Exception:
        return (texto, "pt") if retornar_idioma else texto


def _precisa_traduzir(texto: str) -> bool:
    palavras = re.findall(r"[A-Za-zÀ-ÿ]{3,}", texto)
    fixos = {"vdc", "vac", "pe", "eco", "mgc", "plc", "cpu", "liycy", "pt100", "gnd", "com", "nc", "no"}
    reais = [p for p in palavras if p.lower() not in fixos]
    return len(reais) > 0


def traduzir_pagina_blocos(caminho: Path, _hash_manual: str, pagina_1idx: int, idioma: str) -> list[dict]:
    if idioma.startswith("pt"):
        return []
    with fitz.open(str(caminho)) as doc:
        page = doc.load_page(pagina_1idx - 1)
        estrutura = page.get_text("dict")

    itens = []
    for bloco in estrutura.get("blocks", []):
        if bloco.get("type") != 0:
            continue
        for linha in bloco.get("lines", []):
            if linha.get("dir", (1.0, 0.0)) != (1.0, 0.0):
                continue
            spans = linha.get("spans", [])
            txt = "".join(s.get("text", "") for s in spans).strip()
            if len(txt) >= 3 and _precisa_traduzir(txt):
                tam = spans[0].get("size", 8.0) if spans else 8.0
                itens.append({"bbox": linha["bbox"], "texto": txt, "size": tam})

    if not itens:
        return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        traducoes = list(ex.map(traduzir_texto_pt, [it["texto"] for it in itens]))

    for it, tr in zip(itens, traducoes):
        it["traducao"] = tr.strip()
    return [it for it in itens if it["traducao"] and it["traducao"].lower() != it["texto"].lower()]


# ------------------------------------------------------------------ INDEXAÇÃO PDF (BM25 + CÓDIGOS EXATOS)
class ChunkManual:
    def __init__(self, texto: str, pagina: int):
        self.texto = texto
        self.meta = {"pagina": pagina}


class IndiceManual:
    def __init__(self, paginas_texto: list[str]):
        self.chunks: list[ChunkManual] = []
        corpus = []
        for idx, txt in enumerate(paginas_texto, start=1):
            if not txt or "[Página sem texto" in txt:
                continue
            self.chunks.append(ChunkManual(txt, idx))
            tokens = re.sub(r"[^\w\s\-/\.]", " ", txt.lower()).split()
            corpus.append(tokens)
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def procurar(self, consulta: str, k: int = 6) -> list[tuple[ChunkManual, float]]:
        if not self.chunks or not self.bm25:
            return []

        scores_extra = {c.meta["pagina"]: 0.0 for c in self.chunks}

        for m in re.finditer(r"p[áa]g(?:ina)?\.?\s*(\d+)", consulta, re.IGNORECASE):
            p_cit = int(m.group(1))
            if p_cit in scores_extra:
                scores_extra[p_cit] += 50.0

        codigos = re.findall(r"(?:\-\d+|[A-Za-z]{1,4}\d+[A-Za-z0-9\-\./]*|\d+[A-Za-z]+\d*)", consulta)
        for c in self.chunks:
            txt_low = c.texto.lower()
            for cod in codigos:
                if len(cod) >= 2 and cod.lower() in txt_low:
                    scores_extra[c.meta["pagina"]] += 25.0

        q_tokens = re.sub(r"[^\w\s\-/\.]", " ", consulta.lower()).split()
        bm25_scores = self.bm25.get_scores(q_tokens) if q_tokens else np.zeros(len(self.chunks))

        combinados = []
        for i, c in enumerate(self.chunks):
            total_sc = float(bm25_scores[i]) + scores_extra[c.meta["pagina"]]
            if total_sc > 0:
                combinados.append((c, total_sc))

        combinados.sort(key=lambda x: x[1], reverse=True)
        return combinados[:k]


class ManualPDF:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.nome = caminho.name
        dados = caminho.read_bytes()
        self.hash = hashlib.md5(dados).hexdigest()[:12]
        self.paginas_texto: list[str] = []
        self.paginas_sem_texto: list[int] = []

        with fitz.open(stream=dados, filetype="pdf") as doc:
            self.n_paginas = len(doc)
            for i in range(self.n_paginas):
                t = doc.load_page(i).get_text("text").strip()
                if len(t) < 15:
                    self.paginas_sem_texto.append(i + 1)
                    t = "[Página sem texto pesquisável, apenas esquema/desenho]"
                self.paginas_texto.append(t)

        amostra = " ".join(t[:300] for t in self.paginas_texto if not t.startswith("[Página sem"))[:1000]
        if amostra.strip():
            _, idioma = traduzir_texto_pt(amostra, retornar_idioma=True)
            self.idioma = idioma
        else:
            self.idioma = "pt"

    def construir_indice(self) -> IndiceManual:
        return IndiceManual(self.paginas_texto)


def listar_manuais() -> dict[str, Path]:
    encontrados: dict[str, Path] = {}
    for p in sorted(PASTA_MANUAIS.glob("*.pdf")):
        encontrados[p.name] = p
    for p in sorted(Path(".").glob("*.pdf")):
        if p.name not in encontrados:
            encontrados[p.name] = p
    return encontrados


# ------------------------------------------------------------------ VISUALIZADOR INTERATIVO (PINCH / WHEEL ZOOM)
def _limpar_latin1(txt: str) -> str:
    mapa = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."}
    for k, v in mapa.items():
        txt = txt.replace(k, v)
    return txt.encode("latin-1", "ignore").decode("latin-1")


def renderizar_pagina(caminho: str, pagina: int, zoom: float, blocos_trad: list[dict] | None, formato: str) -> tuple[bytes, str]:
    with fitz.open(caminho) as doc:
        page = doc.load_page(pagina - 1)

        if blocos_trad:
            for b in blocos_trad:
                tr_limpa = _limpar_latin1(b.get("traducao", ""))
                if not tr_limpa:
                    continue
                rect = fitz.Rect(b["bbox"])
                largura = max(rect.width, 10.0)
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
                tam = min(b.get("size", 8.0), max(rect.height * 0.85, 4.5))
                try:
                    w_txt = fitz.get_text_length(tr_limpa, fontname="helv", fontsize=tam)
                except Exception:
                    w_txt = len(tr_limpa) * tam * 0.55
                if w_txt > largura and w_txt > 0:
                    tam = max(3.8, tam * (largura / w_txt))
                pt = fitz.Point(rect.x0, rect.y1 - max(1.0, (rect.height - tam) * 0.25))
                page.insert_text(pt, tr_limpa, fontsize=tam, fontname="helv", color=(0, 0, 0))

        if formato == "svg":
            svg_str = page.get_svg_image(text_as_path=False)
            return svg_str.encode("utf-8"), "image/svg+xml"

        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png"), "image/png"


def html_visualizador(dados: bytes, mime: str, altura: int = 640) -> str:
    b64 = base64.b64encode(dados).decode("ascii")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
    <style>
      html, body {{
        margin: 0; padding: 0; width: 100%; height: {altura}px;
        background: #0f172a; overflow: hidden; touch-action: none;
        font-family: system-ui, sans-serif;
      }}
      #toolbar {{
        position: absolute; top: 10px; right: 12px; z-index: 20;
        display: flex; gap: 6px; background: rgba(15,23,42,0.85);
        padding: 5px 8px; border-radius: 8px; border: 1px solid rgba(56,189,248,0.35);
      }}
      #toolbar button {{
        background: #1e293b; color: #38bdf8; border: 1px solid #334155;
        border-radius: 6px; padding: 4px 10px; font-weight: bold; cursor: pointer;
      }}
      #toolbar button:hover {{ background: #0284c7; color: #fff; }}
      #viewport {{
        width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
        cursor: grab;
      }}
      #viewport:active {{ cursor: grabbing; }}
      #sheet {{
        max-width: 98%; max-height: 98%; background: #fff;
        box-shadow: 0 8px 30px rgba(0,0,0,0.6);
        transform-origin: center center; transition: transform 0.04s linear;
        user-select: none; -webkit-user-drag: none;
      }}
    </style>
    </head>
    <body>
      <div id="toolbar">
        <button onclick="zoomStep(1.25)" title="Aproximar">+</button>
        <button onclick="zoomStep(0.8)" title="Afastar">-</button>
        <button onclick="resetView()" title="Repor">100%</button>
      </div>
      <div id="viewport">
        <img id="sheet" src="data:{mime};base64,{b64}" draggable="false" />
      </div>
      <script>
        const vp = document.getElementById('viewport');
        const img = document.getElementById('sheet');
        let scale = 1, tx = 0, ty = 0;
        let dragging = false, startX = 0, startY = 0;
        let lastDist = 0;

        function apply() {{
          img.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
        }}
        function zoomStep(f) {{
          scale = Math.min(Math.max(0.5, scale * f), 10);
          apply();
        }}
        function resetView() {{
          scale = 1; tx = 0; ty = 0; apply();
        }}

        vp.addEventListener('wheel', (e) => {{
          e.preventDefault();
          const factor = e.deltaY < 0 ? 1.15 : 0.87;
          scale = Math.min(Math.max(0.5, scale * factor), 10);
          apply();
        }}, {{ passive: false }});

        vp.addEventListener('mousedown', (e) => {{
          dragging = true; startX = e.clientX - tx; startY = e.clientY - ty;
        }});
        window.addEventListener('mousemove', (e) => {{
          if (!dragging) return;
          tx = e.clientX - startX; ty = e.clientY - startY; apply();
        }});
        window.addEventListener('mouseup', () => dragging = false);

        vp.addEventListener('touchstart', (e) => {{
          if (e.touches.length === 1) {{
            dragging = true;
            startX = e.touches[0].clientX - tx;
            startY = e.touches[0].clientY - ty;
          }} else if (e.touches.length === 2) {{
            dragging = false;
            lastDist = Math.hypot(
              e.touches[0].clientX - e.touches[1].clientX,
              e.touches[0].clientY - e.touches[1].clientY
            );
          }}
        }}, {{ passive: false }});

        vp.addEventListener('touchmove', (e) => {{
          e.preventDefault();
          if (e.touches.length === 1 && dragging) {{
            tx = e.touches[0].clientX - startX;
            ty = e.touches[0].clientY - startY;
            apply();
          }} else if (e.touches.length === 2) {{
            const dist = Math.hypot(
              e.touches[0].clientX - e.touches[1].clientX,
              e.touches[0].clientY - e.touches[1].clientY
            );
            if (lastDist > 0) {{
              scale = Math.min(Math.max(0.5, scale * (dist / lastDist)), 10);
              apply();
            }}
            lastDist = dist;
          }}
        }}, {{ passive: false }});

        vp.addEventListener('touchend', () => {{ dragging = false; lastDist = 0; }});
      </script>
    </body>
    </html>
    """


# ------------------------------------------------------------------ MANWINWIN & FEEDBACK
class CasoHistorico:
    def __init__(self, id_caso: str, data: str, equipamento: str, avaria: str, causa: str, solucao: str, origem: str):
        self.id = id_caso
        self.data = data
        self.equipamento = equipamento
        self.avaria = avaria
        self.causa = causa
        self.solucao = solucao
        self.origem = origem


class BaseCasos:
    def __init__(self, casos: list[CasoHistorico]):
        self.casos = casos
        corpus = []
        for c in casos:
            txt = f"{c.equipamento} {c.avaria} {c.causa} {c.solucao}".lower()
            corpus.append(re.sub(r"[^\w\s\-]", " ", txt).split())
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def equipamentos(self) -> list[str]:
        return sorted({c.equipamento.strip() for c in self.casos if c.equipamento and c.equipamento.strip()})

    def procurar(self, consulta: str, equipamento: str | None = None, k: int = 4) -> list[tuple[CasoHistorico, float]]:
        if not self.casos or not self.bm25:
            return []
        q_tokens = re.sub(r"[^\w\s\-]", " ", consulta.lower()).split()
        scores = self.bm25.get_scores(q_tokens) if q_tokens else np.zeros(len(self.casos))
        res = []
        for i, c in enumerate(self.casos):
            sc = float(scores[i])
            if equipamento and c.equipamento.lower() == equipamento.lower():
                sc += 5.0
            if sc > 0:
                res.append((c, sc))
        res.sort(key=lambda x: x[1], reverse=True)
        return res[:k]


def carregar_casos_manwinwin() -> tuple[list[CasoHistorico], list[str]]:
    casos: list[CasoHistorico] = []
    avisos: list[str] = []
    for f in sorted(PASTA_MANWINWIN.glob("*")):
        ext = f.suffix.lower()
        linhas: list[dict] = []
        try:
            if ext == ".csv":
                for enc in ("utf-8-sig", "latin-1"):
                    try:
                        txt = f.read_text(encoding=enc)
                        delim = ";" if txt.count(";") > txt.count(",") else ","
                        linhas = list(csv.DictReader(io.StringIO(txt), delimiter=delim))
                        break
                    except Exception:
                        continue
            elif ext in (".xlsx", ".xls"):
                try:
                    import pandas as pd
                    df = pd.read_excel(f).fillna("")
                    linhas = df.to_dict(orient="records")
                except ImportError:
                    avisos.append(f"Instale 'pandas' e 'openpyxl' para ler {f.name}, ou exporte em CSV.")
                    continue
        except Exception as e:
            avisos.append(f"Erro ao ler {f.name}: {e}")
            continue

        for idx, row in enumerate(linhas, start=1):
            norm = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}
            id_ot = next((norm[k] for k in norm if k in ("ot", "id", "número", "numero", "nº ot", "ordem")), f"MW-{idx}")
            data_ot = next((norm[k] for k in norm if "data" in k), "")
            equip = next((norm[k] for k in norm if any(w in k for w in ("equip", "ativo", "máquina", "maquina", "tag"))), "Geral")
            avaria = next((norm[k] for k in norm if any(w in k for w in ("avaria", "sintoma", "descri", "pedido", "falha"))), "")
            causa = next((norm[k] for k in norm if "causa" in k), "")
            solucao = next((norm[k] for k in norm if any(w in k for w in ("solu", "trabalho", "ação", "acao", "interven"))), "")
            if avaria or solucao:
                casos.append(CasoHistorico(id_ot, data_ot, equip, avaria, causa, solucao, "Manwinwin"))

    return casos, avisos


def _ler_feedback_raw() -> list[dict]:
    if not FICHEIRO_FEEDBACK.exists():
        return []
    try:
        return json.loads(FICHEIRO_FEEDBACK.read_text(encoding="utf-8"))
    except Exception:
        return []


def _gravar_feedback_raw(lista: list[dict]) -> None:
    FICHEIRO_FEEDBACK.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def registar_resposta_fb(tec: str, manual: str, equip: str | None, pergunta: str, resposta: str,
                         paginas: list[int], casos_ids: list[str]) -> str:
    lista = _ler_feedback_raw()
    fb_id = f"FB-{len(lista) + 1:04d}"
    lista.append({
        "id": fb_id,
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tecnico": tec,
        "manual": manual,
        "equipamento": equip or "Geral",
        "pergunta": pergunta,
        "resposta": resposta[:1200],
        "paginas": paginas,
        "casos_citados": casos_ids,
        "resultado": "",
        "causa_real": "",
        "solucao_real": "",
    })
    _gravar_feedback_raw(lista)
    return fb_id


def avaliar_fb(fb_id: str, resultado: str, causa: str, solucao: str) -> None:
    lista = _ler_feedback_raw()
    for item in lista:
        if item.get("id") == fb_id:
            item["resultado"] = resultado
            item["causa_real"] = causa.strip()
            item["solucao_real"] = solucao.strip()
            break
    _gravar_feedback_raw(lista)


def casos_validados_fb() -> list[CasoHistorico]:
    res = []
    for item in _ler_feedback_raw():
        if item.get("resultado") in ("resolveu", "parcial") and (item.get("causa_real") or item.get("solucao_real")):
            res.append(CasoHistorico(
                id_caso=item["id"],
                data=item.get("data", ""),
                equipamento=item.get("equipamento", "Geral"),
                avaria=item.get("pergunta", ""),
                causa=item.get("causa_real", ""),
                solucao=item.get("solucao_real", ""),
                origem="Feedback",
            ))
    return res


def estatisticas_fb() -> dict:
    lista = _ler_feedback_raw()
    cont = {"resolveu": 0, "parcial": 0, "nao_resolveu": 0, "sem_avaliacao": 0}
    for it in lista:
        r = it.get("resultado", "")
        if r in cont:
            cont[r] += 1
        else:
            cont["sem_avaliacao"] += 1
    return {"total": len(lista), "por_resultado": cont}


def exportar_csv_fb() -> str:
    lista = _ler_feedback_raw()
    buf = io.StringIO()
    campos = ["id", "data", "tecnico", "manual", "equipamento", "pergunta", "resultado", "causa_real", "solucao_real"]
    writer = csv.DictWriter(buf, fieldnames=campos, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(lista)
    return buf.getvalue()


# ------------------------------------------------------------------ HISTÓRICO DE CONVERSA POR TÉCNICO/MANUAL
def _ficheiro_hist(tec: str, manual: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{tec}_{manual}")[:80]
    return PASTA_HISTORY / f"{slug}.json"


def carregar_historico(tec: str, manual: str) -> list[dict]:
    p = _ficheiro_hist(tec, manual)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def guardar_historico(tec: str, manual: str, msgs: list[dict]) -> None:
    try:
        _ficheiro_hist(tec, manual).write_text(json.dumps(msgs[-40:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def apagar_historico(tec: str, manual: str) -> None:
    p = _ficheiro_hist(tec, manual)
    if p.exists():
        p.unlink()


# ------------------------------------------------------------------ MOTOR DE DIAGNÓSTICO
def reescrever_consulta(pergunta: str, hist_antes: list[dict], usar_llm: bool = True) -> str:
    if not usar_llm or not hist_antes:
        return pergunta
    ultimas = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in hist_antes[-4:])
    prompt = [
        {
            "role": "system",
            "content": (
                "Reescreve a última pergunta do técnico numa consulta de pesquisa técnica autónoma para procurar num manual industrial. "
                "Mantém códigos de erro (ex: -999), referências de sensores/cabos/bornes e o equipamento discutido no histórico. "
                "Devolve APENAS a frase de pesquisa curta, sem explicações."
            ),
        },
        {"role": "user", "content": f"Histórico recente:\n{ultimas}\n\nNova mensagem do técnico: {pergunta}"},
    ]
    try:
        reescrita = gerar_texto_gemini(prompt, temperatura=0.0).strip()
        return reescrita if len(reescrita) >= 3 else pergunta
    except Exception:
        return pergunta


def montar_mensagens_diagnostico(
    pergunta: str,
    hist_antes: list[dict],
    trechos: list[tuple[ChunkManual, float]],
    casos: list[tuple[CasoHistorico, float]],
    nome_manual: str,
    equipamento: str | None,
    idioma_manual: str,
    pagina_aberta: int,
    texto_pagina_aberta: str,
) -> list[dict]:
    system_prompt = """És um engenheiro eletromecânico e técnico sénior de manutenção e automação industrial em Portugal (especialista em centrais térmicas e caldeiras de biomassa).

REGRAS OBRIGATÓRIAS DE DIAGNÓSTICO:
1. Responde EXCLUSIVAMENTE em Português de Portugal (PT-PT) claro, direto e profissional (usa termos como "quadro elétrico", "bornes", "cablagem", "malha 4-20mA", "sonda PT100", "alimentação 24VDC", "cartão analógico do PLC").
2. CONTINUIDADE RIGOROSA: Lê o histórico da conversa. Se o técnico já realizou um teste (ex: "já medi a continuidade", "o cabo está bom"), NÃO repitas esse passo. Assume o resultado e avança imediatamente para a próxima verificação lógica.
3. CRUZAMENTO DE DADOS: Cruza os extratos do manual/esquema elétrico fornecidos com os casos históricos do ManWinWin/Feedback e o teu conhecimento de engenharia.
4. CÓDIGOS DE ERRO E ESQUEMAS: Se surgir um código como -999 ou dúvida de ligação, explica a causa física (circuito aberto, rotura na PT100, falha de alimentação 24VDC, polaridade invertida, canal analógico) e aponta os bornes, pinos e cabos exatos que constam nas páginas.
5. CITAÇÃO OBRIGATÓRIA: Sempre que usares informação de uma página do manual, cita no formato exato [Página X]."""

    bloco_manual = f"--- PÁGINA ATUALMENTE ABERTA NO VISUALIZADOR: [Página {pagina_aberta}] ---\n{texto_pagina_aberta[:3000]}\n"
    paginas_incluidas = {pagina_aberta}
    for ch, _ in trechos:
        p = ch.meta["pagina"]
        if p not in paginas_incluidas:
            paginas_incluidas.add(p)
            bloco_manual += f"\n--- EXTRATO DO MANUAL [Página {p}] ---\n{ch.texto[:3000]}\n"

    bloco_casos = ""
    if casos:
        linhas_c = []
        for c, _ in casos:
            linhas_c.append(
                f"- [{c.origem} {c.id}] Equipamento: {c.equipamento} | Avaria: {c.avaria} | "
                f"Causa: {c.causa or 'N/D'} | Solução: {c.solucao or 'N/D'}"
            )
        bloco_casos = "\nCASOS PARECIDOS NO HISTÓRICO (MANWINWIN / EQUIPA):\n" + "\n".join(linhas_c)

    msgs: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in hist_antes[-8:]:
        msgs.append({"role": m["role"], "content": m["content"]})

    user_content = (
        f"Manual ativo: {nome_manual} (idioma original: {idioma_manual})\n"
        f"Equipamento selecionado: {equipamento or 'Não especificado'}\n\n"
        f"{bloco_manual}\n{bloco_casos}\n\n"
        f"Pedido / relato atual do técnico ({utilizador}): {pergunta}"
    )
    msgs.append({"role": "user", "content": user_content})
    return msgs


def paginas_citadas(resposta: str, max_paginas: int) -> list[int]:
    encontradas = []
    for m in re.finditer(r"\[?P[áa]gina\s*(\d+)\]?", resposta, re.IGNORECASE):
        p = int(m.group(1))
        if 1 <= p <= max_paginas and p not in encontradas:
            encontradas.append(p)
    return encontradas


def precisa_aviso_seguranca(resposta: str) -> bool:
    termos_risco = ("230v", "400v", "trifásic", "quadro elétrico", "tensão", "vapor", "pressão", "queimador", "disjuntor", "fusível")
    r_low = resposta.lower()
    return any(t in r_low for t in termos_risco)


# ------------------------------------------------------------------ RECURSOS EM CACHE
@st.cache_resource(show_spinner="A ler e a indexar o manual...")
def _abrir_manual(caminho: str, _mtime: float):
    m = ManualPDF(Path(caminho))
    return m, m.construir_indice()


def _assinatura_manwinwin():
    fich = tuple((f.name, f.stat().st_mtime) for f in sorted(PASTA_MANWINWIN.glob("*")))
    return fich, len(casos_validados_fb())


@st.cache_resource(show_spinner="A carregar histórico de avarias...")
def _base_casos(_assinatura):
    casos, avisos = carregar_casos_manwinwin()
    n_mw = len(casos)
    casos += casos_validados_fb()
    return BaseCasos(casos), avisos, n_mw


@st.cache_data(show_spinner=False, max_entries=12)
def _pagina_renderizada(caminho: str, hash_manual: str, pagina: int, zoom: float, formato: str,
                        traduzir: bool, idioma: str):
    blocos = traduzir_pagina_blocos(Path(caminho), hash_manual, pagina, idioma) if traduzir else None
    dados, mime = renderizar_pagina(caminho, pagina, zoom, blocos, formato)
    return dados, mime, blocos


# ------------------------------------------------------------------ BARRA LATERAL
with st.sidebar:
    st.markdown(f"### 👤 {utilizador}")

    # --- Gestão direta da Chave API Google no site
    ok_llm, msg_llm = estado_llm()
    if ok_llm:
        st.success("🧠 " + msg_llm)
        with st.expander("🔑 Alterar / Remover Chave API Google"):
            nova_chave = st.text_input("Nova Google API Key", type="password", key="sb_gkey_ok")
            c_save, c_del = st.columns(2)
            if c_save.button("Guardar", use_container_width=True, key="btn_save_ok") and nova_chave.strip():
                guardar_google_api_key(nova_chave.strip())
                listar_modelos_gemini.clear()
                st.rerun()
            if c_del.button("Remover", use_container_width=True, key="btn_del_ok"):
                remover_google_api_key()
                listar_modelos_gemini.clear()
                st.rerun()
    else:
        st.error("🧠 " + msg_llm)
        with st.form("form_api_key_site"):
            chave_site = st.text_input(
                "🔑 Google Gemini API Key",
                type="password",
                placeholder="Cole aqui a chave (AIza...)",
                help="Obtenha em aistudio.google.com/apikey",
            )
            if st.form_submit_button("💾 Ativar Chave API", use_container_width=True):
                if chave_site.strip():
                    guardar_google_api_key(chave_site.strip())
                    listar_modelos_gemini.clear()
                    st.rerun()
                else:
                    st.warning("Cole uma chave válida antes de ativar.")

    st.divider()
    manuais = listar_manuais()

    with st.expander("➕ Adicionar manual (PDF)"):
        up = st.file_uploader("Ficheiro PDF", type="pdf", key="upload_pdf")
        if up is not None:
            destino = PASTA_MANUAIS / Path(up.name).name
            if not destino.exists():
                destino.write_bytes(up.getbuffer())
                st.success("Manual guardado.")
                st.rerun()
            else:
                st.info("Já existe um manual com esse nome.")

    with st.expander("📂 Importar histórico ManWinWin (.csv / .xlsx)"):
        up_mw = st.file_uploader("Exportação ManWinWin", type=["csv", "xlsx", "xls"], key="upload_mw")
        if up_mw is not None:
            dest_mw = PASTA_MANWINWIN / Path(up_mw.name).name
            dest_mw.write_bytes(up_mw.getbuffer())
            st.success("Histórico ManWinWin atualizado!")
            st.rerun()

    if not manuais:
        st.warning("Sem manuais. Adicione um PDF acima ou copie para a pasta 'manuais/'.")
        st.stop()

    nome_manual = st.selectbox("📚 Manual da máquina", list(manuais.keys()))
    manual, indice = _abrir_manual(str(manuais[nome_manual]), manuais[nome_manual].stat().st_mtime)

    base, avisos_mw, n_mw = _base_casos(_assinatura_manwinwin())
    equipamentos = ["(não indicado)"] + base.equipamentos()
    equip_sel = st.selectbox("🏭 Equipamento (melhora a pesquisa no histórico)", equipamentos)
    equipamento = None if equip_sel == "(não indicado)" else equip_sel

    st.caption(f"Manual: {manual.n_paginas} págs · idioma detetado: **{manual.idioma}**")
    if manual.paginas_sem_texto:
        st.caption(f"{len(manual.paginas_sem_texto)} págs sem texto pesquisável (só desenho).")
    st.caption(f"Histórico: {n_mw} avarias ManWinWin · {len(base.casos) - n_mw} casos validados")
    for a in avisos_mw:
        st.warning(a)

    st.divider()
    st.markdown("**Visualização**")
    pode_traduzir = not manual.idioma.startswith("pt")
    traduzir = st.checkbox(
        "🌐 Traduzir esta página para PT",
        value=False,
        disabled=not pode_traduzir,
        help=None if pode_traduzir else "O manual já está em português.",
    )
    formato = st.radio(
        "Qualidade",
        ["png", "svg"],
        format_func=lambda x: "Imagem (rápida)" if x == "png" else "Vetorial (zoom nítido)",
        horizontal=True,
    )
    reescrever = st.checkbox("Usar IA para entender 'e agora?' (mais lento)", value=True)

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        apagar_historico(utilizador, nome_manual)
        st.session_state.mensagens = []
        st.session_state.pop("fb_pendente", None)
        st.rerun()
    if st.button("🚪 Terminar sessão", use_container_width=True):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

    with st.expander("📊 Feedback registado"):
        est = estatisticas_fb()
        st.write(f"Respostas registadas: **{est['total']}**")
        for k, v in est["por_resultado"].items():
            st.write(f"- {k}: {v}")
        st.download_button(
            "⬇️ Exportar CSV",
            exportar_csv_fb(),
            "feedback_mgc.csv",
            "text/csv",
            use_container_width=True,
        )

# ------------------------------------------------------------------ ESTADO DA CONVERSA
if (
    st.session_state.get("_manual_atual") != (utilizador, nome_manual)
    or "mensagens" not in st.session_state
):
    st.session_state._manual_atual = (utilizador, nome_manual)
    st.session_state.mensagens = carregar_historico(utilizador, nome_manual)
    st.session_state.pagina = 1
    st.session_state.pop("fb_pendente", None)

mensagens: list[dict] = st.session_state.mensagens


def _ir_pagina(p: int):
    st.session_state.pagina = int(p)


def _guardar():
    guardar_historico(utilizador, nome_manual, mensagens)


pergunta = st.chat_input("Descreva o problema (ex.: 'erro -999 na sonda de temperatura; já medi a continuidade e está boa')")

col_chat, col_ver = st.columns([5, 6], gap="medium")

# ------------------------------------------------------------------ PAINEL DIREITO: ESQUEMA / MANUAL
if "pagina_pendente" in st.session_state:
    st.session_state.pagina = st.session_state.pop("pagina_pendente")

with col_ver:
    st.subheader("📐 Esquema / Manual")
    n = max(manual.n_paginas, 1)
    st.session_state.pagina = min(max(int(st.session_state.get("pagina", 1)), 1), n)
    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button(
        "⬅️",
        key="btn_pag_ant",
        on_click=_ir_pagina,
        args=(st.session_state.pagina - 1,),
        disabled=st.session_state.pagina <= 1,
        use_container_width=True,
    )
    if n > 1:
        c2.number_input("Página", 1, n, key="pagina", label_visibility="collapsed")
    else:
        c2.markdown("<div style='text-align:center;padding-top:6px;font-weight:bold'>1 / 1</div>", unsafe_allow_html=True)
    c3.button(
        "➡️",
        key="btn_pag_prox",
        on_click=_ir_pagina,
        args=(st.session_state.pagina + 1,),
        disabled=st.session_state.pagina >= n,
        use_container_width=True,
    )
    pag = st.session_state.pagina
    if pag in manual.paginas_sem_texto:
        st.caption("Esta página não tem texto extraível (só desenho): use dois dedos ou a roda do rato para ampliar.")
    try:
        with st.spinner("A preparar a página..." + (" (a traduzir)" if traduzir else "")):
            dados, mime, blocos = _pagina_renderizada(
                str(manual.caminho),
                manual.hash,
                pag,
                ZOOM_RENDER,
                formato,
                bool(traduzir and pode_traduzir),
                manual.idioma,
            )
        components.html(html_visualizador(dados, mime, 640), height=650)
        if blocos:
            with st.expander("Texto traduzido desta página"):
                for b in blocos:
                    st.markdown(f"- {b['texto']}  →  **{b.get('traducao', '')}**")
    except Exception as e:
        st.error(f"Não consegui mostrar a página: {e}")

# ------------------------------------------------------------------ PAINEL ESQUERDO: DIAGNÓSTICO
with col_chat:
    st.subheader("💬 Diagnóstico")
    st.caption("O assistente apenas **sugere**. Valide sempre no esquema e siga o procedimento de segurança.")

    for i, msg in enumerate(mensagens):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] != "assistant":
                continue
            if msg.get("aviso"):
                st.warning(AVISO_SEGURANCA)
            if msg.get("paginas"):
                cols = st.columns(min(len(msg["paginas"]), 5) + 1)
                cols[0].caption("Abrir:")
                for c, p in zip(cols[1:], msg["paginas"][:5]):
                    c.button(f"📄 p.{p}", key=f"pg_{i}_{p}", on_click=_ir_pagina, args=(p,))
            if msg.get("casos"):
                with st.expander(f"📚 {len(msg['casos'])} casos parecidos no histórico"):
                    for c in msg["casos"]:
                        st.markdown(
                            f"**{c['id']}** · {c['data']} · {c['equipamento']}  \n"
                            f"Avaria: {c['avaria']}  \nCausa: {c['causa'] or '—'}  \n"
                            f"Solução: {c['solucao'] or '—'}"
                        )
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
                            if st.form_submit_button("Guardar avaliação"):
                                avaliar_fb(msg["fb_id"], pend[1], causa, solucao)
                                msg["avaliacao"] = pend[1]
                                st.session_state.pop("fb_pendente", None)
                                _guardar()
                                st.rerun()
                    else:
                        b1, b2, b3 = st.columns(3)
                        for col, (res, rot) in zip(
                            (b1, b2, b3),
                            (("resolveu", "✅ Resolveu"), ("parcial", "🟡 Em parte"), ("nao_resolveu", "❌ Não resolveu")),
                        ):
                            if col.button(rot, key=f"fb_{res}_{i}", use_container_width=True):
                                st.session_state.fb_pendente = (i, res)
                                st.rerun()

    # --------------------------------------------------------------- NOVA PERGUNTA
    if pergunta:
        with st.chat_message("user"):
            st.markdown(pergunta)
        hist_antes = list(mensagens)
        mensagens.append({"role": "user", "content": pergunta})

        with st.chat_message("assistant"):
            with st.spinner("A consultar o manual e o histórico de avarias..."):
                consulta = reescrever_consulta(pergunta, hist_antes, usar_llm=reescrever and ok_llm)
                trechos = indice.procurar(consulta, k=TOP_CHUNKS_MANUAL)
                casos = base.procurar(consulta, equipamento, k=TOP_CASOS_MANWINWIN)

            pag_aberta = int(st.session_state.get("pagina", 1))
            txt_pag_aberta = manual.paginas_texto[pag_aberta - 1]
            msgs = montar_mensagens_diagnostico(
                pergunta,
                hist_antes,
                trechos,
                casos,
                manual.nome,
                equipamento,
                manual.idioma,
                pag_aberta,
                txt_pag_aberta,
            )

            paginas_busca = []
            for ch, _ in trechos:
                if ch.meta["pagina"] not in paginas_busca:
                    paginas_busca.append(ch.meta["pagina"])

            casos_resumo = [
                {
                    "id": (f"OT {c.id}" if c.origem == "Manwinwin" else c.id),
                    "data": c.data,
                    "equipamento": c.equipamento,
                    "avaria": c.avaria,
                    "causa": c.causa,
                    "solucao": c.solucao,
                }
                for c, _ in casos
            ]

            try:
                resposta = st.write_stream(gerar_stream_gemini(msgs))
                erro = None
            except Exception as e:
                resposta, erro = "", str(e)

            if erro or not resposta.strip():
                resposta = (
                    "⚠️ O modelo Google Gemini não respondeu (" + (erro or "resposta vazia") + "). "
                    "Mostro-lhe apenas o que encontrei no manual e no histórico — consulte as páginas e os casos abaixo."
                )
                st.markdown(resposta)

            citadas = paginas_citadas(resposta, manual.n_paginas)
            paginas = citadas or paginas_busca[:3] or [pag_aberta]
            fb_id = registar_resposta_fb(
                utilizador,
                manual.nome,
                equipamento,
                pergunta,
                resposta,
                paginas,
                [c["id"] for c in casos_resumo],
            )
            mensagens.append({
                "role": "assistant",
                "content": resposta,
                "paginas": paginas,
                "casos": casos_resumo,
                "fb_id": fb_id,
                "aviso": precisa_aviso_seguranca(resposta),
            })
            if paginas:
                st.session_state.pagina_pendente = paginas[0]
            _guardar()
        st.rerun()
