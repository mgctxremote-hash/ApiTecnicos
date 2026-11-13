import streamlit as st
import fitz  # PyMuPDF
import numpy as np
import re
import os
import io
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from rank_bm25 import BM25Okapi
from groq import Groq
import difflib

# ---------------------------------------------------------
# CONFIGURAÇÃO DE PÁGINA & ESTILO FUTURISTA 2026
# ---------------------------------------------------------
st.set_page_config(page_title="Assistente MGC 2026", page_icon="⚡", layout="centered")

st.markdown("""
<style>
    /* Estilo Industrial Futurista 2026 - MGC */
    .stApp {
        background-color: #050810;
        background-image: radial-gradient(circle at top right, #0a1128 0%, #050810 100%);
        color: #e2e8f0;
        font-family: 'Segoe UI', Roboto, Helvetica, sans-serif;
    }
    .sidebar .stSidebar {
        background-color: rgba(10, 15, 30, 0.8) !important;
        backdrop-filter: blur(12px);
        border-right: 1px solid rgba(56, 189, 248, 0.2);
    }
    h1, h2, h3 {
        color: #38bdf8 !important;
        text-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
        letter-spacing: -0.5px;
    }
    .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: rgba(30, 41, 59, 0.7) !important;
        color: #f8fafc !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
    }
    .stTextInput input:focus {
        border-color: #38bdf8 !important;
        box-shadow: 0 0 8px rgba(56, 189, 248, 0.5) !important;
    }
    .stButton button {
        background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
        color: white;
        border: 1px solid rgba(56, 189, 248, 0.4);
        border-radius: 8px;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(2, 132, 199, 0.4);
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
        box-shadow: 0 6px 20px rgba(14, 165, 233, 0.6);
        transform: translateY(-2px);
        border: 1px solid #38bdf8;
    }
    div.stChatMessage {
        background: rgba(30, 41, 59, 0.65);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# VARIÁVEIS GLOBAIS E PASTAS
# ---------------------------------------------------------
CHAVE_LOCAL_FIXA = ""
PASTA_MANUAIS = "manuais"
os.makedirs(PASTA_MANUAIS, exist_ok=True)
FICHEIRO_CONFIG_LOCAL = ".groq_key.json"
FICHEIRO_HISTORICO = "historico_chat.json"
CACHE_TRADUCOES = {}

# ---------------------------------------------------------
# GESTÃO DE SESSÃO PERSISTENTE E MEMÓRIA
# ---------------------------------------------------------
def carregar_historico_chat():
    """Recupera o histórico da memória se o browser for atualizado."""
    if os.path.exists(FICHEIRO_HISTORICO):
        try:
            with open(FICHEIRO_HISTORICO, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_historico_chat(mensagens):
    """Guarda a conversa em tempo real para não perder contexto."""
    try:
        with open(FICHEIRO_HISTORICO, "w", encoding="utf-8") as f:
            json.dump(mensagens, f)
    except Exception:
        pass

# Verifica Sessão através dos parâmetros do URL (evita voltar ao Login)
params = st.query_params

if "autenticado" not in st.session_state:
    if params.get("autenticado") == "true" and params.get("user"):
        st.session_state.autenticado = True
        st.session_state.utilizador_atual = params.get("user")
    else:
        st.session_state.autenticado = False

if "utilizador_atual" not in st.session_state:
    st.session_state.utilizador_atual = ""
if "mensagens" not in st.session_state:
    st.session_state.mensagens = carregar_historico_chat()
if "pdf_processado" not in st.session_state:
    st.session_state.pdf_processado = False
if "textos_paginas" not in st.session_state:
    st.session_state.textos_paginas = []
if "bm25_index" not in st.session_state:
    st.session_state.bm25_index = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "modelos_chat_validos" not in st.session_state:
    st.session_state.modelos_chat_validos = []
if "ultimo_pdf_nome" not in st.session_state:
    st.session_state.ultimo_pdf_nome = None
if "idioma_manual" not in st.session_state:
    st.session_state.idioma_manual = "pt"
if "cache_imagens" not in st.session_state:
    st.session_state.cache_imagens = {}
if "pagina_ativa" not in st.session_state:
    st.session_state.pagina_ativa = None

# ---------------------------------------------------------
# FUNÇÕES DE TRADUÇÃO MELHORADA (EM BLOCOS)
# ---------------------------------------------------------
def chamar_tradutor_pt(texto, retornar_idioma=False):
    texto_limpo = texto.strip()
    if not texto_limpo:
        return ("", "pt") if retornar_idioma else ""
        
    if not retornar_idioma and texto_limpo in CACHE_TRADUCOES:
        return CACHE_TRADUCOES[texto_limpo]

    # Divide textos muito grandes para evitar bloqueio da API do Google
    blocos = [texto_limpo[i:i+1000] for i in range(0, len(texto_limpo), 1000)]
    texto_traduzido_final = ""
    idioma_origem = "pt"

    try:
        for bloco in blocos:
            url = (
                "https://translate.googleapis.com/translate_a/single?client=gtx"
                f"&sl=auto&tl=pt-PT&dt=t&q={urllib.parse.quote(bloco)}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as response:
                dados = json.loads(response.read().decode("utf-8"))
                texto_traduzido_final += "".join([parte[0] for parte in dados[0] if parte[0]])
                if len(dados) > 2:
                    idioma_origem = dados[2]
                
        CACHE_TRADUCOES[texto_limpo] = texto_traduzido_final
        if retornar_idioma:
            return texto_traduzido_final, idioma_origem
        return texto_traduzido_final
    except Exception:
        return (texto, "pt") if retornar_idioma else texto

def detetar_idioma_pdf(textos):
    amostra = ""
    for t in textos:
        if "[Página sem texto" not in t and len(t) > 40:
            amostra += " " + t[:300]
        if len(amostra) > 1200:
            break
    if not amostra.strip():
        return "pt"
    _, idioma = chamar_tradutor_pt(amostra[:1000], retornar_idioma=True)
    return idioma.lower() if idioma else "pt"

def precisa_traduzir_linha(texto):
    palavras = re.findall(r'[A-Za-zÀ-ÿ]{3,}', texto)
    termos_tecnicos_fixos = {"vdc", "vac", "pe", "eco", "mgc", "plc", "cpu", "liycy", "pt100"}
    palavras_reais = [p for p in palavras if p.lower() not in termos_tecnicos_fixos]
    return len(palavras_reais) > 0

def limpar_caracteres_pdf(texto):
    substituicoes = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."}
    for orig, subst in substituicoes.items():
        texto = texto.replace(orig, subst)
    return texto.encode("latin-1", "ignore").decode("latin-1")

# ---------------------------------------------------------
# GESTÃO DE CHAVES
# ---------------------------------------------------------
def obter_chave_oculta():
    if CHAVE_LOCAL_FIXA.strip():
        return CHAVE_LOCAL_FIXA.strip()
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"].strip()
    except Exception:
        pass
    if os.path.exists(FICHEIRO_CONFIG_LOCAL):
        try:
            with open(FICHEIRO_CONFIG_LOCAL, "r", encoding="utf-8") as f:
                dados = json.load(f)
                if dados.get("groq_key"):
                    return dados["groq_key"].strip()
        except Exception:
            pass
    return os.environ.get("GROQ_API_KEY", "").strip()

def guardar_chave_local(api_key):
    try:
        with open(FICHEIRO_CONFIG_LOCAL, "w", encoding="utf-8") as f:
            json.dump({"groq_key": api_key.strip()}, f)
    except Exception:
        pass

def obter_pin_seguro():
    try:
        if "PIN_ACESSO" in st.secrets:
            return st.secrets["PIN_ACESSO"].strip()
    except Exception:
        pass
    return "tecnicos4321"

# ---------------------------------------------------------
# TELA DE LOGIN OBRIGATÓRIA (COM PERSISTÊNCIA NA NUVEM)
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.markdown("<h1 style='text-align: center;'>⚡ MGC 2026</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8;'>Sistema Inteligente de Diagnóstico Industrial</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("form_login"):
            utilizador_input = st.text_input("Nome do Técnico (Ex: Bruno, Alexandre, João)")
            chave_input = st.text_input("Chave de Acesso MGC", type="password")
            
            chave_sistema = obter_chave_oculta()
            api_key_input = ""
            if not chave_sistema:
                api_key_input = st.text_input("Groq API Key (Apenas no Primeiro Acesso)", type="password")
            
            submeter = st.form_submit_button("Entrar no Sistema", use_container_width=True)
            
            if submeter:
                pin_correto = obter_pin_seguro()
                if chave_input.strip() == pin_correto and utilizador_input.strip():
                    st.session_state.autenticado = True
                    st.session_state.utilizador_atual = utilizador_input.strip()
                    if api_key_input.strip():
                        guardar_chave_local(api_key_input.strip())
                    
                    # Salva login no URL para não voltar a pedir ao atualizar a página
                    st.query_params["autenticado"] = "true"
                    st.query_params["user"] = utilizador_input.strip()
                    st.success("Acesso Concedido. Bem-vindo.")
                    st.rerun()
                else:
                    st.error("Falha na autenticação: Verifique a Chave de Acesso.")
    st.stop()

# ---------------------------------------------------------
# PROCESSAMENTO DE PDF E MOTOR DE BUSCA AVANÇADO
# ---------------------------------------------------------
def listar_manuais_fixos():
    manuais = {}
    if os.path.exists(PASTA_MANUAIS):
        for f in sorted(os.listdir(PASTA_MANUAIS)):
            if f.lower().endswith(".pdf"):
                manuais[f] = os.path.join(PASTA_MANUAIS, f)
    for f in sorted(os.listdir(".")):
        if f.lower().endswith(".pdf") and f not in manuais:
            manuais[f] = f
    return manuais

def processar_bytes_pdf(pdf_bytes, ativar_traducao=False):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    textos_originais = []
    
    # Lê ABSOLUTAMENTE TODAS AS PÁGINAS do documento
    for num_pagina in range(len(doc)):
        texto = doc[num_pagina].get_text("text").strip()
        if not texto:
            texto = "[Página sem texto detetável, apenas esquemas/imagens]"
        textos_originais.append(texto)
        
    st.session_state.pdf_bytes = pdf_bytes
    st.session_state.cache_imagens = {}
    st.session_state.pagina_ativa = 1
    
    idioma = detetar_idioma_pdf(textos_originais)
    st.session_state.idioma_manual = idioma
    
    if ativar_traducao and not idioma.startswith("pt"):
        barra = st.progress(0, text=f"A traduzir manual completo para Português...")
        textos_traduzidos = list(textos_originais)
        
        def traduzir_pagina(idx_texto):
            idx, txt = idx_texto
            if "[Página sem texto" in txt:
                return idx, txt
            return idx, chamar_tradutor_pt(txt[:4000])

        with ThreadPoolExecutor(max_workers=8) as executor:
            total = len(textos_originais)
            for concluido, (idx, txt_pt) in enumerate(executor.map(traduzir_pagina, enumerate(textos_originais)), 1):
                textos_traduzidos[idx] = txt_pt
                barra.progress(concluido / total, text=f"A traduzir página {concluido} de {total}...")
        barra.empty()
        return textos_traduzidos
        
    return textos_originais

def gerar_indice_bm25(textos):
    corpus_tokenizado = []
    for texto in textos:
        # Preserva totalmente números e sinais para a pesquisa não falhar (ex: -999)
        texto_limpo = re.sub(r'[^\w\s\-]', ' ', texto.lower())
        corpus_tokenizado.append(texto_limpo.split())
    return BM25Okapi(corpus_tokenizado)

def corrigir_termo_por_aproximacao(sintoma, textos_paginas):
    palavras_manual = set()
    for txt in textos_paginas:
        for p in re.findall(r'[A-Za-zÀ-ÿ0-9\-]{3,}', txt.lower()):
            palavras_manual.add(p)
            
    termos_utilizador = re.findall(r'[A-Za-zÀ-ÿ0-9\-]{3,}', sintoma.lower())
    correcoes_feitas = {}
    
    for termo in termos_utilizador:
        if termo not in palavras_manual and not termo.startswith("-"):
            matches = difflib.get_close_matches(termo, list(palavras_manual), n=1, cutoff=0.75)
            if matches:
                correcoes_feitas[termo] = matches[0]
                
    sintoma_corrigido = sintoma
    termo_sugerido = None
    if correcoes_feitas:
        for err, certo in correcoes_feitas.items():
            sintoma_corrigido = re.sub(r'\b' + err + r'\b', certo, sintoma_corrigido, flags=re.IGNORECASE)
            termo_sugerido = certo
            
    return sintoma_corrigido, termo_sugerido

def procurar_paginas_relevantes(sintoma, textos, bm25, pagina_atual=None, top_k=8):
    """Retorna uma porção massiva de contexto (8 páginas) para a IA ter visão geral do problema."""
    total_pags = len(textos)
    paginas_alvo = []

    match_pag_pergunta = re.search(r'p[áa]g(?:ina)?\.?\s*(\d+)', sintoma, re.IGNORECASE)
    if match_pag_pergunta:
        pag_citada = int(match_pag_pergunta.group(1))
        if 1 <= pag_citada <= total_pags:
            paginas_alvo.append(pag_citada)

    # Detetor rigoroso de códigos de erro
    padrao_numerico = re.findall(r'\-?\d+', sintoma)
    for idx, texto_pag in enumerate(textos):
        for num in padrao_numerico:
            if num in texto_pag:
                num_p = idx + 1
                if num_p not in paginas_alvo:
                    paginas_alvo.append(num_p)

    sintoma_limpo = re.sub(r'[^\w\s\-]', ' ', sintoma.lower())
    tokenized_query = sintoma_limpo.split()
    scores = bm25.get_scores(tokenized_query)
    indices_top = np.argsort(scores)[::-1][:top_k]

    for idx in indices_top:
        if scores[idx] > 0:
            num_p = int(idx + 1)
            if num_p not in paginas_alvo:
                paginas_alvo.append(num_p)

    if pagina_atual and (1 <= pagina_atual <= total_pags):
        if not paginas_alvo:
            paginas_alvo.append(pagina_atual)
        elif pagina_atual not in paginas_alvo:
            paginas_alvo.insert(0, pagina_atual)

    if not paginas_alvo:
        return "", []

    contexto = ""
    for num_p in paginas_alvo[:8]: # Envia as 8 páginas mais relevantes ao mesmo tempo para não perder detalhes
        texto_limpo = re.sub(r'\n+', '\n', textos[num_p - 1])
        etiqueta = " (PÁGINA ATUALMENTE EM FOCO PELO TÉCNICO)" if num_p == pagina_atual else ""
        contexto += f"\n\n--- PÁGINA {num_p}{etiqueta} ---\n{texto_limpo}"

    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina, traduzir_visualmente=True, nivel_zoom=3.5):
    nome_doc = st.session_state.ultimo_pdf_nome or "doc"
    chave_cache = f"{nome_doc}_{num_pagina}_{traduzir_visualmente}_{nivel_zoom}"
    if chave_cache in st.session_state.cache_imagens:
        return st.session_state.cache_imagens[chave_cache]

    doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    pagina = doc.load_page(num_pagina - 1)
    
    if traduzir_visualmente:
        try:
            estrutura = pagina.get_text("dict")
            linhas_para_traduzir = []
            
            for bloco in estrutura.get("blocks", []):
                if bloco.get("type") == 0:
                    for linha in bloco.get("lines", []):
                        if linha.get("dir", (1.0, 0.0)) == (1.0, 0.0):
                            spans = linha.get("spans", [])
                            texto_linha = "".join([s.get("text", "") for s in spans]).strip()
                            if len(texto_linha) >= 3 and precisa_traduzir_linha(texto_linha):
                                tamanho_orig = spans[0].get("size", 8.0) if spans else 8.0
                                linhas_para_traduzir.append((linha["bbox"], texto_linha, tamanho_orig))
            
            if linhas_para_traduzir:
                textos_orig = [item[1] for item in linhas_para_traduzir]
                with ThreadPoolExecutor(max_workers=8) as executor:
                    textos_pt = list(executor.map(chamar_tradutor_pt, textos_orig))
                    
                for (bbox, txt_orig, tam_orig), txt_pt in zip(linhas_para_traduzir, textos_pt):
                    txt_pt_limpo = limpar_caracteres_pdf(txt_pt.strip())
                    if txt_pt_limpo and txt_pt_limpo.lower() != txt_orig.strip().lower():
                        rect = fitz.Rect(bbox)
                        largura_caixa = max(rect.width, 10.0)
                        pagina.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
                        tam_fonte = min(tam_orig, max(rect.height * 0.85, 4.5))
                        try:
                            largura_texto = fitz.get_text_length(txt_pt_limpo, fontname="helv", fontsize=tam_fonte)
                        except Exception:
                            largura_texto = len(txt_pt_limpo) * tam_fonte * 0.55
                            
                        if largura_texto > largura_caixa and largura_texto > 0:
                            tam_fonte = max(3.8, tam_fonte * (largura_caixa / largura_texto))
                            
                        ponto_escrita = fitz.Point(rect.x0, rect.y1 - max(1.0, (rect.height - tam_fonte) * 0.25))
                        pagina.insert_text(ponto_escrita, txt_pt_limpo, fontsize=tam_fonte, fontname="helv", color=(0, 0, 0))
        except Exception:
            pass

    matriz_zoom = fitz.Matrix(nivel_zoom, nivel_zoom)
    pix = pagina.get_pixmap(matrix=matriz_zoom)
    img_final = Image.open(io.BytesIO(pix.tobytes("png")))
    
    if len(st.session_state.cache_imagens) > 4:
        st.session_state.cache_imagens.pop(next(iter(st.session_state.cache_imagens)))
        
    st.session_state.cache_imagens[chave_cache] = img_final
    return img_final

def listar_modelos_chat_groq(api_key):
    if st.session_state.modelos_chat_validos:
        return st.session_state.modelos_chat_validos
        
    palavras_bloqueadas = ["guard", "whisper", "tts", "playai", "orpheus", "embed", "moderation", "vision", "audio", "safeguard", "tool", "1b", "3b", "allam"]
    modelos_filtrados = []
    try:
        client = Groq(api_key=api_key)
        for m in client.models.list().data:
            if not any(b in m.id.lower() for b in palavras_bloqueadas):
                modelos_filtrados.append(m.id)
                
        # Força o modelo mais potente possível para raciocínio de engenharia complexo
        modelos_filtrados.sort(key=lambda n: 0 if ("70b" in n.lower() or "versatile" in n.lower()) else (1 if "32b" in n.lower() else 2))
    except Exception:
        pass
        
    if not modelos_filtrados:
        modelos_filtrados = ["llama-3.1-8b-instant"]
        
    st.session_state.modelos_chat_validos = modelos_filtrados
    return modelos_filtrados

def gerar_resposta_groq(api_key, prompt_sistema, historico_recente, prompt_utilizador):
    client = Groq(api_key=api_key)
    modelos = listar_modelos_chat_groq(api_key)
    ultimo_erro = ""
    
    mensagens_api = [{"role": "system", "content": prompt_sistema}]
    for msg_ant in historico_recente:
        mensagens_api.append({"role": msg_ant["role"], "content": msg_ant["content"]})
    mensagens_api.append({"role": "user", "content": prompt_utilizador})
    
    for nome_modelo in modelos:
        try:
            chat_completion = client.chat.completions.create(
                messages=mensagens_api,
                model=nome_modelo,
                temperature=0.15,
                max_tokens=700, # Margem aumentada para explicações completas
                top_p=0.9,
            )
            return chat_completion.choices[0].message.content, nome_modelo
        except Exception as e:
            ultimo_erro = str(e)
            continue
            
    raise Exception(f"Nenhum modelo respondeu. Erro: {ultimo_erro}")

# ---------------------------------------------------------
# INTERFACE LATERAL 2026 E NAVEGAÇÃO
# ---------------------------------------------------------
api_key = obter_chave_oculta()

with st.sidebar:
    st.markdown(f"### 👤 Técnico: `{st.session_state.utilizador_atual}`")
    st.divider()
    
    st.header("📚 Manuais da Máquina")
    manuais_disponiveis = listar_manuais_fixos()
    opcoes_select = list(manuais_disponiveis.keys())
    
    manual_escolhido_nome = None
    bytes_para_processar = None

    if opcoes_select:
        manual_escolhido_nome = st.selectbox("Manual Fixo:", options=opcoes_select, index=0)

    with st.expander("➕ Adicionar Novo PDF"):
        ficheiro_upload = st.file_uploader("Ficheiro PDF", type="pdf")
        if ficheiro_upload is not None:
            caminho_guardar = os.path.join(PASTA_MANUAIS, ficheiro_upload.name)
            if not os.path.exists(caminho_guardar):
                with open(caminho_guardar, "wb") as f_out:
                    f_out.write(ficheiro_upload.getbuffer())
                st.success("Manual guardado permanentemente!")
                st.rerun()
            else:
                manual_escolhido_nome = ficheiro_upload.name
                bytes_para_processar = ficheiro_upload.getvalue()

    if manual_escolhido_nome and bytes_para_processar is None and manual_escolhido_nome in manuais_disponiveis:
        with open(manuais_disponiveis[manual_escolhido_nome], "rb") as f_in:
            bytes_para_processar = f_in.read()

    if manual_escolhido_nome and manual_escolhido_nome != st.session_state.ultimo_pdf_nome:
        st.session_state.pdf_processado = False
        st.session_state.ultimo_pdf_nome = manual_escolhido_nome

    ativar_traducao_manual = st.checkbox("🌐 Tradução Total do Manual para PT", value=False)

    if bytes_para_processar and not st.session_state.pdf_processado and api_key:
        with st.spinner(f"A analisar '{manual_escolhido_nome}' na íntegra..."):
            st.session_state.textos_paginas = processar_bytes_pdf(bytes_para_processar, ativar_traducao=ativar_traducao_manual)
            st.session_state.bm25_index = gerar_indice_bm25(st.session_state.textos_paginas)
            listar_modelos_chat_groq(api_key)
            st.session_state.pdf_processado = True

    if st.session_state.pdf_processado:
        total_pags = len(st.session_state.textos_paginas)
        st.success(f"Status: Pronto ({total_pags} págs lidas)")
        
        traduzir_img_op = st.checkbox("Traduzir textos no ecrã", value=ativar_traducao_manual)
        
        pag_selecionada = st.number_input("Página em foco:", min_value=1, max_value=total_pags, value=st.session_state.pagina_ativa or 1, step=1)
        st.session_state.pagina_ativa = pag_selecionada
        
        st.divider()
        if st.button("🗑️ Limpar Conversa Atual", use_container_width=True):
            st.session_state.mensagens = []
            guardar_historico_chat([])
            st.rerun()
            
        if st.button("🚪 Encerrar Sessão", use_container_width=True):
            st.session_state.autenticado = False
            st.query_params.clear()
            st.rerun()
    else:
        traduzir_img_op = False

# ---------------------------------------------------------
# HISTÓRICO DE MENSAGENS E RENDERING DA IMAGEM
# ---------------------------------------------------------
total_paginas_doc = len(st.session_state.textos_paginas)

for idx_msg, msg in enumerate(st.session_state.mensagens):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "num_pagina" in msg and st.session_state.pdf_processado:
            pag_atual = msg["num_pagina"]
            
            with st.spinner(f"A gerar e renderizar esquema da Página {pag_atual}..."):
                img_exibir = extrair_imagem_pagina(pag_atual, traduzir_visualmente=traduzir_img_op, nivel_zoom=3.5)
            
            st.image(img_exibir, caption=f"Página {pag_atual} / {total_paginas_doc} (Expanda para aplicar zoom)", use_container_width=True)
            
            col_ant, col_meio, col_prox = st.columns([1, 1, 1])
            with col_ant:
                if st.button(f"⬅️ Ant. {pag_atual - 1}", key=f"ant_{idx_msg}_{pag_atual}", disabled=(pag_atual <= 1), use_container_width=True):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual - 1
                    st.session_state.pagina_ativa = pag_atual - 1
                    guardar_historico_chat(st.session_state.mensagens)
                    st.rerun()
            with col_meio:
                st.markdown(f"<div style='text-align:center; padding-top:6px; font-weight:bold; color:#38bdf8;'>Pág. {pag_atual} / {total_paginas_doc}</div>", unsafe_allow_html=True)
            with col_prox:
                if st.button(f"Seg. {pag_atual + 1} ➡️", key=f"prox_{idx_msg}_{pag_atual}", disabled=(pag_atual >= total_paginas_doc), use_container_width=True):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual + 1
                    st.session_state.pagina_ativa = pag_atual + 1
                    guardar_historico_chat(st.session_state.mensagens)
                    st.rerun()

# ---------------------------------------------------------
# CÉREBRO DE ENGENHARIA - CONTINUIDADE E DIAGNÓSTICO
# ---------------------------------------------------------
sintoma = st.chat_input("Ex: 'Já testei a continuidade e está boa, mas o erro -999 continua. O que meço a seguir?'")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Selecione um manual na barra lateral primeiro.")
    else:
        sintoma_processado, termo_sugerido = corrigir_termo_por_aproximacao(sintoma, st.session_state.textos_paginas)
        
        texto_exibir_utilizador = sintoma
        if termo_sugerido:
            texto_exibir_utilizador = f"{sintoma} *(Referência corrigida: **{termo_sugerido}**)*"
            
        with st.chat_message("user"):
            st.markdown(texto_exibir_utilizador)
            
        with st.chat_message("assistant"):
            with st.spinner("A cruzar os teus testes com todas as páginas do esquema..."):
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma_processado, 
                    st.session_state.textos_paginas, 
                    st.session_state.bm25_index,
                    pagina_atual=st.session_state.pagina_ativa,
                    top_k=8 # Varre 8 páginas massivas para não deixar escapar nenhum detalhe
                )
                
                if not paginas:
                    st.warning("Não encontrei referências exatas, mas irei guiar-te com o meu conhecimento de engenharia.")
                    pagina_principal = st.session_state.pagina_ativa
                else:
                    pagina_principal = paginas[0]
                    
                prompt_sistema = """És um Engenheiro Eletromecânico e Técnico Sénior de Automação Industrial a guiar um técnico no terreno de uma central de biomassa.

REGRAS DE RESPOSTA OBRIGATÓRIAS:
1. NUNCA fuja do assunto nem ignores a mensagem do técnico. Lê o histórico da conversa: se o técnico já testou X e diz que está bom, AVANÇA para a causa Y (ex: "Como já testaste a sonda no campo, vamos testar o cartão do PLC no quadro.").
2. Lê as páginas fornecidas e funde essa informação com o teu conhecimento técnico real. 
3. Quando houver códigos de erro (como -999 ou sinais fora de escala), traduz isso para a realidade física: o que está partido, em curto, desligado ou desconfigurado? 
4. Dá passos claros de diagnóstico prático com multímetro (tensão, resistência, 4-20mA) indicando os bornes e pinos exatos listados no PDF.
5. Usa sempre Português de Portugal industrial (bornes, malha, cartão analógico, PT100). Indica as páginas referidas (ex: [Página X])."""

                prompt_utilizador = f"""Técnico a operar: {st.session_state.utilizador_atual}
Manual: {st.session_state.ultimo_pdf_nome}
Página atual no ecrã: [Página {st.session_state.pagina_ativa}]
Top páginas lidas: {paginas}

TEXTOS EXTRAÍDOS DO MANUAL:
{contexto_relevante}

MENSAGEM/SINTOMA RELATADO AGORA PELO TÉCNICO: "{sintoma_processado}"

(Não repitas os testes que o técnico já fez. Dá-lhe a próxima instrução técnica baseada nos esquemas acima.)"""
                
                try:
                    # Envia as últimas 10 mensagens para a IA reter o raciocínio contínuo perfeitamente
                    historico_alargado = st.session_state.mensagens[-10:]
                    resposta_ai, modelo_usado = gerar_resposta_groq(api_key, prompt_sistema, historico_alargado, prompt_utilizador)
                    
                    st.session_state.mensagens.append({"role": "user", "content": texto_exibir_utilizador})
                    
                    match_pagina = re.search(r'\[P[áa]gina\s*(\d+)\]', resposta_ai, re.IGNORECASE)
                    if match_pagina:
                        num_pag_ia = int(match_pagina.group(1))
                        num_pagina_detectada = num_pag_ia if (1 <= num_pag_ia <= total_paginas_doc) else pagina_principal
                    else:
                        num_pagina_detectada = pagina_principal
                        
                    st.session_state.pagina_ativa = num_pagina_detectada
                    
                    dados_resposta = {
                        "role": "assistant",
                        "content": resposta_ai,
                        "num_pagina": num_pagina_detectada
                    }
                    st.session_state.mensagens.append(dados_resposta)
                    guardar_historico_chat(st.session_state.mensagens)
                    st.rerun()
                    
                except Exception as e:
                    st.session_state.mensagens.append({"role": "user", "content": texto_exibir_utilizador})
                    st.error(f"Erro no cérebro da IA: {e}")
                    dados_fallback = {
                        "role": "assistant",
                        "content": f"A mostrar a **[Página {pagina_principal}]** extraída do manual:",
                        "num_pagina": pagina_principal
                    }
                    st.session_state.mensagens.append(dados_fallback)
                    guardar_historico_chat(st.session_state.mensagens)
                    st.rerun()
