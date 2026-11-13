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
if "modelos_chat_validos" not in st.session_state:
    st.session_state.modelos_chat_validos = []

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
            texto = "[Página sem texto detetável, apenas esquemas/imagens]"
        textos.append(texto)
    ficheiro.seek(0)
    st.session_state.pdf_bytes = ficheiro.read()
    return textos

def gerar_indice_bm25(textos):
    """Cria um índice de pesquisa instantâneo local (Zero Internet, Zero Limites)."""
    corpus_tokenizado = []
    for texto in textos:
        texto_limpo = re.sub(r'[^\w\s]', ' ', texto.lower())
        corpus_tokenizado.append(texto_limpo.split())
    return BM25Okapi(corpus_tokenizado)

def procurar_paginas_relevantes(sintoma, textos, bm25, top_k=2):
    """Encontra as páginas usando pontuação algorítmica exata."""
    sintoma_limpo = re.sub(r'[^\w\s]', ' ', sintoma.lower())
    tokenized_query = sintoma_limpo.split()
    
    scores = bm25.get_scores(tokenized_query)
    
    if max(scores) == 0:
        return "Nenhuma palavra-chave do sintoma encontrada no manual.", []
        
    indices_top = np.argsort(scores)[::-1][:top_k]
    
    contexto = ""
    paginas_alvo = []
    for idx in indices_top:
        if scores[idx] > 0:
            # Limpa espaços e linhas repetidas do esquema elétrico para não confundir a IA
            texto_limpo = re.sub(r'\n+', '\n', textos[idx])
            contexto += f"\n\n--- PÁGINA {idx + 1} ---\n{texto_limpo}"
            paginas_alvo.append(int(idx + 1))
        
    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina):
    """Gera a imagem de alta resolução do esquema elétrico/mecânico da página."""
    doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    pagina = doc.load_page(num_pagina - 1)
    matriz_zoom = fitz.Matrix(2.0, 2.0)
    pix = pagina.get_pixmap(matrix=matriz_zoom)
    imagem_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(imagem_bytes))

def listar_modelos_chat_groq(api_key):
    """Obtém apenas modelos de conversação robustos, bloqueando modelos pequenos (1B/3B) e de classificação."""
    if st.session_state.modelos_chat_validos:
        return st.session_state.modelos_chat_validos
        
    palavras_bloqueadas = [
        "guard", "whisper", "tts", "playai", "orpheus", 
        "embed", "moderation", "vision", "audio", "safeguard",
        "tool", "1b", "3b", "allam"
    ]
    
    modelos_filtrados = []
    try:
        client = Groq(api_key=api_key)
        todos_modelos = [m.id for m in client.models.list().data]
        
        for m in todos_modelos:
            nome_min = m.lower()
            if not any(bloqueada in nome_min for bloqueada in palavras_bloqueadas):
                modelos_filtrados.append(m)
                
        # Ordena dando prioridade aos modelos maiores e mais inteligentes em Português
        def prioridade(nome):
            n = nome.lower()
            if "70b" in n or "120b" in n:
                return 0
            if "32b" in n or "27b" in n or "24b" in n:
                return 1
            if "qwen" in n or "deepseek" in n or "gemma2-9b" in n:
                return 2
            if "llama" in n and "8b" in n:
                return 3
            return 4
            
        modelos_filtrados.sort(key=prioridade)
    except Exception:
        pass
        
    if not modelos_filtrados:
        modelos_filtrados = ["llama-3.1-8b-instant", "gemma2-9b-it"]
        
    st.session_state.modelos_chat_validos = modelos_filtrados
    return modelos_filtrados

def gerar_resposta_groq(api_key, prompt_sistema, prompt_utilizador):
    """Gera a resposta com temperatura baixa e penalização para impedir repetições e erros."""
    client = Groq(api_key=api_key)
    modelos = listar_modelos_chat_groq(api_key)
    ultimo_erro = ""
    
    for nome_modelo in modelos:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_utilizador}
                ],
                model=nome_modelo,
                temperature=0.1,
                max_tokens=350,
                top_p=0.9,
            )
            return chat_completion.choices[0].message.content, nome_modelo
        except Exception as e:
            ultimo_erro = str(e)
            continue
            
    raise Exception(f"Nenhum modelo disponível respondeu. Último erro: {ultimo_erro}")

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
            listar_modelos_chat_groq(api_key)
            
            st.session_state.pdf_processado = True
            st.success(f"Indexação concluída! ({len(st.session_state.textos_paginas)} páginas prontas)")

# Histórico
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "imagem" in msg:
            st.image(msg["imagem"], caption=f"Esquema Visual - Página {msg['num_pagina']}", use_container_width=True)

# Input
sintoma = st.chat_input("Descreve a avaria ou palavra-chave (ex: erro -999 sonda da fornalha)...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Carrega um manual e insere a Groq API Key primeiro!")
    else:
        st.session_state.mensagens.append({"role": "user", "content": sintoma})
        with st.chat_message("user"):
            st.markdown(sintoma)
            
        with st.chat_message("assistant"):
            with st.spinner("A analisar esquema e manual..."):
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma, 
                    st.session_state.textos_paginas, 
                    st.session_state.bm25_index
                )
                
                if not paginas:
                    st.warning("Nenhuma das palavras digitadas foi encontrada no manual.")
                else:
                    pagina_principal = paginas[0]
                    
                    prompt_sistema = """És um engenheiro e técnico sénior de manutenção industrial em Portugal.
A tua função é ajudar o técnico no chão de fábrica a localizar componentes e diagnosticar avarias com base nos manuais e esquemas elétricos.

REGRAS OBRIGATÓRIAS DE ESCRITA:
1. Escreve EXCLUSIVAMENTE em Português de Portugal correto, claro e profissional (usa termos como "quadro elétrico", "borne", "cabo", "sonda", "verificar a continuidade", "alimentação 24VDC").
2. PROIBIDO repetir frases, ideias ou palavras. Sê direto e conciso (máximo de 4 a 5 linhas no total).
3. O texto fornecido vem de um esquema elétrico industrial (contém códigos de componentes como 14CT10, 26A3, cabos como 54W6, entradas analógicas, etc.). Identifica os códigos relevantes da página principal e indica-os ao técnico.
4. Indica sempre a página principal no formato [Página X].
5. Termina com uma única pergunta curta e prática de despiste (ex: "Consegues medir se chegam 24VDC aos bornes da sonda no quadro?")."""

                    prompt_utilizador = f"""Página mais relevante encontrada pelo sistema: [Página {pagina_principal}]

Texto extraído das páginas do manual/esquema elétrico:
{contexto_relevante}

Sintoma ou dúvida do técnico: "{sintoma}"

Fornece um diagnóstico curto, sem repetições, indicando os componentes a verificar na [Página {pagina_principal}]."""
                    
                    try:
                        resposta_ai, modelo_usado = gerar_resposta_groq(api_key, prompt_sistema, prompt_utilizador)
                        st.markdown(resposta_ai)
                        
                        # Usa a página principal encontrada pelo BM25 (ou a citada pela IA se existir no intervalo)
                        match_pagina = re.search(r'\[P[áa]gina\s*(\d+)\]', resposta_ai, re.IGNORECASE)
                        if match_pagina:
                            num_pag_ia = int(match_pagina.group(1))
                            num_pagina_detectada = num_pag_ia if num_pag_ia in paginas else pagina_principal
                        else:
                            num_pagina_detectada = pagina_principal
                            
                        img = None
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
                        num_pag_fallback = paginas[0]
                        img_fallback = extrair_imagem_pagina(num_pag_fallback)
                        st.info(f"A mostrar diretamente a Página {num_pag_fallback} encontrada no manual:")
                        st.image(img_fallback, caption=f"Esquema Visual - Página {num_pag_fallback}", use_container_width=True)
