import streamlit as st
import fitz  # PyMuPDF
import numpy as np
import re
from PIL import Image
import io
from rank_bm25 import BM25Okapi
from groq import Groq

# ---------------------------------------------------------
# CONFIGURAÇÃO DE PÁGINA
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
if "bm25_index" not in st.session_state:
    st.session_state.bm25_index = None
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
        if not texto:
            texto = "[Página sem texto detectável, apenas esquemas/imagens]"
        textos.append(texto)
    ficheiro.seek(0)
    st.session_state.pdf_bytes = ficheiro.read()
    return textos

def gerar_indice_bm25(textos):
    """Cria um índice de pesquisa instantâneo local (Zero Internet, Zero Limites)."""
    corpus_tokenizado = []
    for texto in textos:
        texto_limpo = re.sub(r'[^\w\s]', '', texto.lower())
        corpus_tokenizado.append(texto_limpo.split())
    return BM25Okapi(corpus_tokenizado)

def procurar_paginas_relevantes(sintoma, textos, bm25, top_k=2):
    """Encontra as páginas usando pontuação algorítmica exata."""
    sintoma_limpo = re.sub(r'[^\w\s]', '', sintoma.lower())
    tokenized_query = sintoma_limpo.split()
    
    scores = bm25.get_scores(tokenized_query)
    
    if max(scores) == 0:
        return "Nenhuma palavra-chave do sintoma encontrada no manual.", []
        
    indices_top = np.argsort(scores)[::-1][:top_k]
    
    contexto = ""
    paginas_alvo = []
    for idx in indices_top:
        contexto += f"\n\n--- PÁGINA {idx + 1} ---\n{textos[idx]}"
        paginas_alvo.append(idx + 1)
        
    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina):
    """Gera a imagem do esquema elétrico da página."""
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
    api_key = st.text_input("Groq API Key", type="password")
        
    st.divider()
    ficheiro_pdf = st.file_uploader("Carregar Manual da Máquina (PDF)", type="pdf")
    
    if ficheiro_pdf and not st.session_state.pdf_processado and api_key:
        with st.spinner("A indexar manual (Motor Local BM25)..."):
            st.session_state.textos_paginas = processar_pdf(ficheiro_pdf)
            st.session_state.bm25_index = gerar_indice_bm25(st.session_state.textos_paginas)
            
            st.session_state.pdf_processado = True
            st.success(f"Indexação concluída! ({len(st.session_state.textos_paginas)} páginas prontas)")

# Histórico
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "imagem" in msg:
            st.image(msg["imagem"], caption=f"Esquema Referido ({msg['num_pagina']})", use_container_width=True)

# Input
sintoma = st.chat_input("Descreve a avaria ou palavra-chave (ex: falha pressostato)...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Carrega um manual e insere a Groq API Key primeiro!")
    else:
        st.session_state.mensagens.append({"role": "user", "content": sintoma})
        with st.chat_message("user"):
            st.markdown(sintoma)
            
        with st.chat_message("assistant"):
            with st.spinner("A diagnosticar..."):
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma, 
                    st.session_state.textos_paginas, 
                    st.session_state.bm25_index
                )
                
                if not paginas:
                    st.warning("As palavras-chave não existem no documento.")
                else:
                    prompt_sistema = f"""
                    És um técnico sénior de manutenção industrial. Diagnostica avarias passo a passo.
                    Usa APENAS a informação do manual fornecida abaixo.
                    Nunca dês a solução completa se for ambíguo. Dá a causa provável e termina com uma pergunta curta (ex: "O erro no sensor X confirma-se?").
                    Responde sempre em Português de Portugal.
                    
                    REGRA ABSOLUTA: Sempre que referires a causa, OBRIGATORIAMENTE indica a página de onde tiraste a informação no formato exato: [Página X].
                    
                    Contexto recuperado:
                    {contexto_relevante}
                    """
                    
                    try:
                        # Inicializa o cliente Groq
                        client = Groq(api_key=api_key)
                        
                        # Chama o modelo Llama 3 (Ultra rápido)
                        chat_completion = client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": prompt_sistema},
                                {"role": "user", "content": f"Sintoma: {sintoma}"}
                            ],
                            model="llama-3.3-70b-versatile",
                            temperature=0.3,
                        )
                        
                        resposta_ai = chat_completion.choices[0].message.content
                        
                        st.markdown(resposta_ai)
                        
                        # Extrai a página para mostrar o esquema
                        match_pagina = re.search(r'\[Página (\d+)\]', resposta_ai, re.IGNORECASE)
                        img = None
                        num_pagina_detectada = None
                        
                        if match_pagina:
                            num_pagina_detectada = int(match_pagina.group(1))
                            if 1 <= num_pagina_detectada <= len(st.session_state.textos_paginas):
                                img = extrair_imagem_pagina(num_pagina_detectada)
                                st.image(img, caption=f"Esquema Visual - Página {num_pagina_detectada}", use_container_width=True)
                        
                        dados_resposta = {"role": "assistant", "content": resposta_ai}
                        if img:
                            dados_resposta["imagem"] = img
                            dados_resposta["num_pagina"] = num_pagina_detectada
                        st.session_state.mensagens.append(dados_resposta)
                        
                    except Exception as e:
                        st.error(f"Erro na comunicação com o Groq: {e}")
