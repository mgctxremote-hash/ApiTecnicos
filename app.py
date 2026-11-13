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

# ---------------------------------------------------------
# CONFIGURAÇÃO DE PÁGINA
# ---------------------------------------------------------
st.set_page_config(page_title="Assistente de Diagnóstico", page_icon="🔧", layout="centered")

# APENAS PARA USO LOCAL NO PC (Deixa vazio "" se fores enviar o código para o GitHub!)
CHAVE_LOCAL_FIXA = ""

# ---------------------------------------------------------
# INICIALIZAÇÃO DE SESSÃO
# ---------------------------------------------------------
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
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
if "cache_traducoes" not in st.session_state:
    st.session_state.cache_traducoes = {}

# ---------------------------------------------------------
# FUNÇÕES DE TRADUÇÃO INTERNA (TEXTO E IMAGEM)
# ---------------------------------------------------------
def chamar_tradutor_pt(texto, retornar_idioma=False):
    """Traduz qualquer texto para Português de Portugal sem precisar de bibliotecas externas."""
    texto_limpo = texto.strip()
    if not texto_limpo:
        return ("", "pt") if retornar_idioma else ""
        
    if not retornar_idioma and texto_limpo in st.session_state.cache_traducoes:
        return st.session_state.cache_traducoes[texto_limpo]

    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            f"&sl=auto&tl=pt-PT&dt=t&q={urllib.parse.quote(texto_limpo)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as response:
            dados = json.loads(response.read().decode("utf-8"))
            texto_traduzido = "".join([parte[0] for parte in dados[0] if parte[0]])
            idioma_origem = dados[2] if len(dados) > 2 else "pt"
            
            st.session_state.cache_traducoes[texto_limpo] = texto_traduzido
            if retornar_idioma:
                return texto_traduzido, idioma_origem
            return texto_traduzido
    except Exception:
        return (texto, "pt") if retornar_idioma else texto

def detetar_idioma_pdf(textos):
    """Analisa uma amostra do manual para detetar se está noutra língua que não Português."""
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
    """Filtra apenas palavras reais e ignora códigos puros de esquemas (ex: 24VDC, 14CT10, 54W6)."""
    palavras = re.findall(r'[A-Za-zÀ-ÿ]{3,}', texto)
    termos_tecnicos_fixos = {"vdc", "vac", "pe", "eco", "mgc", "plc", "cpu", "liycy", "pt100"}
    palavras_reais = [p for p in palavras if p.lower() not in termos_tecnicos_fixos]
    return len(palavras_reais) > 0

def limpar_caracteres_pdf(texto):
    """Garante compatibilidade de caracteres com a fonte interna do PDF."""
    substituicoes = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."}
    for orig, subst in substituicoes.items():
        texto = texto.replace(orig, subst)
    return texto.encode("latin-1", "ignore").decode("latin-1")

# ---------------------------------------------------------
# FUNÇÕES CORE
# ---------------------------------------------------------
def obter_chave_oculta():
    """Procura a API Key escondida no código local, nos Secrets do Streamlit ou variáveis de sistema."""
    if CHAVE_LOCAL_FIXA.strip():
        return CHAVE_LOCAL_FIXA.strip()
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"].strip()
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", "").strip()

def processar_pdf(ficheiro):
    """Extrai o texto do PDF e traduz automaticamente para Português se estiver noutro idioma."""
    doc = fitz.open(stream=ficheiro.read(), filetype="pdf")
    textos_originais = []
    for num_pagina in range(len(doc)):
        texto = doc[num_pagina].get_text("text").strip()
        if not texto:
            texto = "[Página sem texto detetável, apenas esquemas/imagens]"
        textos_originais.append(texto)
        
    ficheiro.seek(0)
    st.session_state.pdf_bytes = ficheiro.read()
    st.session_state.cache_imagens = {}
    
    # Deteta o idioma do manual
    idioma = detetar_idioma_pdf(textos_originais)
    st.session_state.idioma_manual = idioma
    
    # Se não estiver em Português, traduz o texto de todas as páginas em paralelo para a pesquisa funcionar em PT
    if not idioma.startswith("pt"):
        barra = st.progress(0, text=f"Manual detetado em '{idioma.upper()}'. A traduzir automaticamente para Português...")
        textos_traduzidos = list(textos_originais)
        
        def traduzir_pagina(idx_texto):
            idx, txt = idx_texto
            if "[Página sem texto" in txt:
                return idx, txt
            # Limita a 3500 caracteres por página para tradução rápida
            return idx, chamar_tradutor_pt(txt[:3500])

        with ThreadPoolExecutor(max_workers=8) as executor:
            total = len(textos_originais)
            for concluido, (idx, txt_pt) in enumerate(executor.map(traduzir_pagina, enumerate(textos_originais)), 1):
                textos_traduzidos[idx] = txt_pt
                barra.progress(concluido / total, text=f"A traduzir manual para Português ({concluido}/{total} páginas)...")
        barra.empty()
        return textos_traduzidos
        
    return textos_originais

def gerar_indice_bm25(textos):
    """Cria um índice de pesquisa instantâneo local."""
    corpus_tokenizado = []
    for texto in textos:
        texto_limpo = re
