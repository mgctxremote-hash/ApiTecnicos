import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import numpy as np
import re
from PIL import Image
import io

# ---------------------------------------------------------
# CONFIGURAÇÃO DE PÁGINA (Mobile Friendly)
# ---------------------------------------------------------
st.set_page_config(page_title="Assistente de Diagnóstico", page_icon="🔧", layout="centered")

# ---------------------------------------------------------
# INICIALIZAÇÃO DE SESSÃO
# ---------------------------------------------------------
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
if "pdf_processado" not in st.session_state:
    st.session_state.pdf_processado = False
if "textos_paginas" not in st.session_state:
    st.session_state.textos_paginas = []
if "vetores_paginas" not in st.session_state:
    st.session_state.vetores_paginas = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "nome_modelo_embedding" not in st.session_state:
    st.session_state.nome_modelo_embedding = None

# ---------------------------------------------------------
# FUNÇÕES CORE
# ---------------------------------------------------------
def processar_pdf(ficheiro):
    """Extrai texto página a página do PDF carregado."""
    doc = fitz.open(stream=ficheiro.read(), filetype="pdf")
    textos = []
    for num_pagina in range(len(doc)):
        texto = doc[num_pagina].get_text("text").strip()
        if not texto:
            texto = "[Página sem texto detectável, apenas esquemas/imagens]"
        textos.append(texto)
    ficheiro.seek(0)
    st.session_state.pdf_bytes = ficheiro.read()
    return textos

def obter_modelo_embedding():
    """Procura dinamicamente o modelo de embedding autorizado na tua API Key."""
    if st.session_state.nome_modelo_embedding:
        return st.session_state.nome_modelo_embedding
        
    for m in genai.list_models():
        if 'embedContent' in m.supported_generation_methods:
            st.session_state.nome_modelo_embedding = m.name
            return m.name
    return "models/text-embedding-004" # Fallback de segurança

def gerar_embeddings(textos):
    """Gera vetores de forma dinâmica e limpa, sem parâmetros conflituosos."""
    try:
        modelo = obter_modelo_embedding()
        resultado = genai.embed_content(
            model=modelo,
            content=textos
        )
        return np.array(resultado['embedding'])
    except Exception as e:
        st.error(f"Erro ao gerar embeddings com {st.session_state.nome_modelo_embedding}: {e}")
        return None

def procurar_paginas_relevantes(sintoma, textos, vetores, top_k=2):
    """Pesquisa as páginas mais semelhantes ao sintoma usando Numpy puro."""
    modelo = obter_modelo_embedding()
    vetor_sintoma = np.array(genai.embed_content(
        model=modelo,
        content=sintoma
    )['embedding'])
    
    similaridades = np.dot(vetores, vetor_sintoma) / (np.linalg.norm(vetores, axis=1) * np.linalg.norm(vetor_sintoma))
    indices_top = np.argsort(similaridades)[::-1][:top_k]
    
    contexto = ""
    paginas_alvo = []
    for idx in indices_top:
        contexto += f"\n\n--- PÁGINA {idx + 1} ---\n{textos[idx]}"
        paginas_alvo.append(idx + 1)
        
    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina):
    """Gera uma imagem de alta resolução da página do PDF."""
    doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    pagina = doc.load_page(num_pagina - 1)
    matriz_zoom = fitz.Matrix(2.0, 2.0)
    pix = pagina.get_pixmap(matrix=matriz_zoom)
    imagem_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(imagem_bytes))

# ---------------------------------------------------------
# INTERFACE STREAMLIT
# ---------------------------------------------------------
st.title("🔧 Assistente MGC - Manuais")

with st.sidebar:
    st.header("Configurações")
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key:
        genai.configure(api_key=api_key)
        
    st.divider()
    ficheiro_pdf = st.file_uploader("Carregar Manual da Máquina (PDF)", type="pdf")
    
    if ficheiro_pdf and not st.session_state.pdf_processado and api_key:
        with st.spinner("A mapear o manual (Deteção Auto de IA)..."):
            st.session_state.textos_paginas = processar_pdf(ficheiro_pdf)
            st.session_state.vetores_paginas = gerar_embeddings(st.session_state.textos_paginas)
            
            if st.session_state.vetores_paginas is not None:
                st.session_state.pdf_processado = True
                st.success(f"Manual indexado! Modelo usado: {st.session_state.nome_modelo_embedding}")

# Histórico de Chat
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "imagem" in msg:
            st.image(msg["imagem"], caption=f"Página referida ({msg['num_pagina']})", use_container_width=True)

# Input
sintoma = st.chat_input("Descreve o sintoma (ex: luz vermelha a piscar no quadro)...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Carrega um manual e insere a API Key primeiro!")
    else:
        st.session_state.mensagens.append({"role": "user", "content": sintoma})
        with st.chat_message("user"):
            st.markdown(sintoma)
            
        with st.chat_message("assistant"):
            with st.spinner("A diagnosticar..."):
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma, 
                    st.session_state.textos_paginas, 
                    st.session_state.vetores_paginas
                )
                
                prompt_sistema = f"""
                És um técnico sénior de manutenção industrial. O teu objetivo é diagnosticar avarias passo a passo.
                Usa APENAS a informação do manual fornecida abaixo (que é a mais provável de conter a avaria).
                Nunca dês a solução completa de imediato se o sintoma for ambíguo. Dá a causa mais provável e termina com uma pergunta curta de triagem (ex: "Achas que o erro poderia ser no sensor X?").
                
                REGRA ABSOLUTA: Sempre que referires uma causa ou solução, OBRIGATORIAMENTE indica a página de onde tiraste a informação no formato exato: [Página X] (exemplo: [Página 42]).
                
                Contexto do manual encontrado:
                {contexto_relevante}
                """
                
                modelo = genai.GenerativeModel("gemini-1.5-flash")
                resposta_ai = modelo.generate_content([prompt_sistema, f"Sintoma relatado pelo técnico: {sintoma}"]).text
                
                st.markdown(resposta_ai)
                
                match_pagina = re.search(r'\[Página (\d+)\]', resposta_ai, re.IGNORECASE)
                img = None
                num_pagina_detectada = None
                
                if match_pagina:
                    num_pagina_detectada = int(match_pagina.group(1))
                    if 1 <= num_pagina_detectada <= len(st.session_state.textos_paginas):
                        img = extrair_imagem_pagina(num_pagina_detectada)
                        st.image(img, caption=f"Esquema/Visual - Página {num_pagina_detectada}", use_container_width=True)
                
                dados_resposta = {"role": "assistant", "content": resposta_ai}
                if img:
                    dados_resposta["imagem"] = img
                    dados_resposta["num_pagina"] = num_pagina_detectada
                st.session_state.mensagens.append(dados_resposta)
