[app.py](https://github.com/user-attachments/files/34798236/app.py)
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
# INICIALIZAÇÃO DE SESSÃO (Isolamento por utilizador)
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

# ---------------------------------------------------------
# FUNÇÕES CORE
# ---------------------------------------------------------
def processar_pdf(ficheiro):
    """Extrai texto página a página do PDF carregado."""
    doc = fitz.open(stream=ficheiro.read(), filetype="pdf")
    textos = []
    for num_pagina in range(len(doc)):
        texto = doc[num_pagina].get_text("text").strip()
        # Se a página for só imagens, colocamos um aviso para não gerar erro
        if not texto:
            texto = "[Página sem texto detectável, apenas esquemas/imagens]"
        textos.append(texto)
    
    # Guarda os bytes originais para depois conseguirmos extrair as imagens das páginas
    ficheiro.seek(0)
    st.session_state.pdf_bytes = ficheiro.read()
    return textos

def gerar_embeddings(textos):
    """Gera vetores usando a API leve e gratuita do Gemini."""
    try:
        resultado = genai.embed_content(
            model="models/embedding-001",
            content=textos,
            task_type="retrieval_document",
        )
        return np.array(resultado['embedding'])
    except Exception as e:
        st.error(f"Erro ao gerar embeddings (Verifica a API Key): {e}")
        return None

def procurar_paginas_relevantes(sintoma, textos, vetores, top_k=2):
    """Pesquisa as páginas mais semelhantes ao sintoma usando Matemática simples (NumPy)."""
    # Cria o vetor do sintoma
    vetor_sintoma = np.array(genai.embed_content(
        model="models/embedding-001",
        content=sintoma,
        task_type="retrieval_query"
    )['embedding'])
    
    # Calcula a similaridade (Cosine Similarity)
    similaridades = np.dot(vetores, vetor_sintoma) / (np.linalg.norm(vetores, axis=1) * np.linalg.norm(vetor_sintoma))
    
    # Pega nos índices das páginas mais relevantes
    indices_top = np.argsort(similaridades)[::-1][:top_k]
    
    contexto = ""
    paginas_alvo = []
    for idx in indices_top:
        contexto += f"\n\n--- PÁGINA {idx + 1} ---\n{textos[idx]}"
        paginas_alvo.append(idx + 1)
        
    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina):
    """Gera uma imagem de alta resolução da página do PDF para ver esquemas."""
    doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    pagina = doc.load_page(num_pagina - 1)  # Zero-indexed
    # Aumentar a resolução (zoom 2x) para os esquemas elétricos ficarem legíveis
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
        with st.spinner("A ler manual e a indexar páginas..."):
            st.session_state.textos_paginas = processar_pdf(ficheiro_pdf)
            st.session_state.vetores_paginas = gerar_embeddings(st.session_state.textos_paginas)
            
            if st.session_state.vetores_paginas is not None:
                st.session_state.pdf_processado = True
                st.success(f"Manual processado! ({len(st.session_state.textos_paginas)} páginas)")

# Histórico de Chat
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "imagem" in msg:
            st.image(msg["imagem"], caption=f"Página do Manual referida ({msg['num_pagina']})", use_container_width=True)

# Input de Sintoma (Caixa de texto no fundo do ecrã mobile)
sintoma = st.chat_input("Descreve o sintoma (ex: luz vermelha a piscar no quadro)...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Carrega um manual e insere a API Key primeiro!")
    else:
        # Mostra a mensagem do técnico
        st.session_state.mensagens.append({"role": "user", "content": sintoma})
        with st.chat_message("user"):
            st.markdown(sintoma)
            
        with st.chat_message("assistant"):
            with st.spinner("A diagnosticar..."):
                # 1. Procura as páginas no PDF
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma, 
                    st.session_state.textos_paginas, 
                    st.session_state.vetores_paginas
                )
                
                # 2. Prepara a instrução estrita para o Gemini
                prompt_sistema = f"""
                És um técnico sénior de manutenção industrial. O teu objetivo é diagnosticar avarias passo a passo.
                Usa APENAS a informação do manual fornecida abaixo (que é a mais provável de conter a avaria).
                Nunca dês a solução completa de imediato se o sintoma for ambíguo. Dá a causa mais provável e termina com uma pergunta curta de triagem (ex: "Achas que o erro poderia ser no sensor X?").
                
                REGRA ABSOLUTA: Sempre que referires uma causa ou solução, OBRIGATORIAMENTE indica a página de onde tiraste a informação no formato exato: [Página X] (exemplo: [Página 42]).
                
                Contexto do manual encontrado:
                {contexto_relevante}
                """
                
                # 3. Chama o Modelo LLM
                modelo = genai.GenerativeModel("gemini-1.5-flash")
                resposta_ai = modelo.generate_content([prompt_sistema, f"Sintoma relatado pelo técnico: {sintoma}"]).text
                
                # 4. Mostra o texto
                st.markdown(resposta_ai)
                
                # 5. Procura menções a [Página X] na resposta para extrair o esquema visual
                match_pagina = re.search(r'\[Página (\d+)\]', resposta_ai, re.IGNORECASE)
                img = None
                num_pagina_detectada = None
                
                if match_pagina:
                    num_pagina_detectada = int(match_pagina.group(1))
                    # Validação de segurança para não rebentar se a IA inventar uma página
                    if 1 <= num_pagina_detectada <= len(st.session_state.textos_paginas):
                        img = extrair_imagem_pagina(num_pagina_detectada)
                        st.image(img, caption=f"Esquema/Visual - Página {num_pagina_detectada}", use_container_width=True)
                
                # 6. Guarda no histórico
                dados_resposta = {"role": "assistant", "content": resposta_ai}
                if img:
                    dados_resposta["imagem"] = img
                    dados_resposta["num_pagina"] = num_pagina_detectada
                st.session_state.mensagens.append(dados_resposta)
