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

# Cache global em memória (seguro para múltiplas threads fora do st.session_state)
CACHE_TRADUCOES = {}

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

# ---------------------------------------------------------
# FUNÇÕES DE TRADUÇÃO INTERNA (TEXTO E IMAGEM)
# ---------------------------------------------------------
def chamar_tradutor_pt(texto, retornar_idioma=False):
    """Traduz qualquer texto para Português de Portugal de forma segura em multi-threading."""
    texto_limpo = texto.strip()
    if not texto_limpo:
        return ("", "pt") if retornar_idioma else ""
        
    if not retornar_idioma and texto_limpo in CACHE_TRADUCOES:
        return CACHE_TRADUCOES[texto_limpo]

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
            
            CACHE_TRADUCOES[texto_limpo] = texto_traduzido
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
    
    idioma = detetar_idioma_pdf(textos_originais)
    st.session_state.idioma_manual = idioma
    
    # Se não estiver em Português, traduz o texto de todas as páginas em paralelo
    if not idioma.startswith("pt"):
        barra = st.progress(0, text=f"Manual detetado em '{idioma.upper()}'. A traduzir automaticamente para Português...")
        textos_traduzidos = list(textos_originais)
        
        def traduzir_pagina(idx_texto):
            idx, txt = idx_texto
            if "[Página sem texto" in txt:
                return idx, txt
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
            texto_limpo = re.sub(r'\n+', '\n', textos[idx])
            contexto += f"\n\n--- PÁGINA {idx + 1} ---\n{texto_limpo}"
            paginas_alvo.append(int(idx + 1))
        
    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina, traduzir_visualmente=True):
    """Gera a imagem da página e substitui textos estrangeiros por Português diretamente na imagem."""
    chave_cache = f"{num_pagina}_{traduzir_visualmente}"
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
                        pagina.insert_text(
                            ponto_escrita,
                            txt_pt_limpo,
                            fontsize=tam_fonte,
                            fontname="helv",
                            color=(0, 0, 0)
                        )
        except Exception:
            pass

    matriz_zoom = fitz.Matrix(2.0, 2.0)
    pix = pagina.get_pixmap(matrix=matriz_zoom)
    imagem_bytes = pix.tobytes("png")
    img_final = Image.open(io.BytesIO(imagem_bytes))
    
    st.session_state.cache_imagens[chave_cache] = img_final
    return img_final

def listar_modelos_chat_groq(api_key):
    """Obtém apenas modelos de conversação robustos."""
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
    """Gera a resposta com temperatura baixa para impedir repetições e erros."""
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

chave_configurada = obter_chave_oculta()

with st.sidebar:
    st.header("Manuais da Máquina")
    
    if chave_configurada:
        api_key = chave_configurada
    else:
        api_key = st.text_input("Groq API Key", type="password")
        st.divider()
        
    ficheiro_pdf = st.file_uploader("Carregar Manual da Máquina (PDF)", type="pdf")
    
    if ficheiro_pdf and ficheiro_pdf.name != st.session_state.ultimo_pdf_nome:
        st.session_state.pdf_processado = False
        st.session_state.ultimo_pdf_nome = ficheiro_pdf.name
    
    if ficheiro_pdf and not st.session_state.pdf_processado and api_key:
        with st.spinner("A ler e a indexar o manual..."):
            st.session_state.textos_paginas = processar_pdf(ficheiro_pdf)
            st.session_state.bm25_index = gerar_indice_bm25(st.session_state.textos_paginas)
            listar_modelos_chat_groq(api_key)
            st.session_state.pdf_processado = True
            
    if st.session_state.pdf_processado:
        total_pags = len(st.session_state.textos_paginas)
        idioma_det = st.session_state.idioma_manual.upper()
        st.success(f"Manual pronto! ({total_pags} páginas)")
        
        manual_estrangeiro = not st.session_state.idioma_manual.startswith("pt")
        if manual_estrangeiro:
            st.info(f"🌐 Idioma original: {idioma_det} (Traduzido automaticamente para PT)")
        
        traduzir_img_op = st.checkbox(
            "Traduzir textos na imagem para Português",
            value=manual_estrangeiro,
            help="Ativa automaticamente quando o manual não está em Português."
        )
    else:
        traduzir_img_op = False

# Histórico de Mensagens + Navegação de Páginas Lado a Lado
total_paginas_doc = len(st.session_state.textos_paginas)

for idx_msg, msg in enumerate(st.session_state.mensagens):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "num_pagina" in msg and st.session_state.pdf_processado:
            pag_atual = msg["num_pagina"]
            
            with st.spinner(f"A preparar imagem da Página {pag_atual}..."):
                img_exibir = extrair_imagem_pagina(pag_atual, traduzir_visualmente=traduzir_img_op)
                
            st.image(
                img_exibir,
                caption=f"Esquema / Manual - Página {pag_atual} de {total_paginas_doc}",
                use_container_width=True
            )
            
            # Botões para passar as páginas para o lado (Anterior / Seguinte)
            col_ant, col_meio, col_prox = st.columns([1, 1, 1])
            with col_ant:
                if st.button(
                    f"⬅️ Página {pag_atual - 1}",
                    key=f"ant_{idx_msg}_{pag_atual}",
                    disabled=(pag_atual <= 1),
                    use_container_width=True
                ):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual - 1
                    st.rerun()
            with col_meio:
                st.markdown(
                    f"<div style='text-align:center; padding-top:6px; font-weight:bold;'>📄 Pág. {pag_atual} / {total_paginas_doc}</div>",
                    unsafe_allow_html=True
                )
            with col_prox:
                if st.button(
                    f"Página {pag_atual + 1} ➡️",
                    key=f"prox_{idx_msg}_{pag_atual}",
                    disabled=(pag_atual >= total_paginas_doc),
                    use_container_width=True
                ):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual + 1
                    st.rerun()

# Input de Sintoma
sintoma = st.chat_input("Descreve a avaria ou palavra-chave (ex: erro -999 sonda da fornalha)...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Carrega primeiro o manual PDF na barra lateral!")
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
3. Identifica os códigos relevantes da página principal (como 14CT10, 26A3, cabos como 54W6, entradas analógicas, etc.) e indica-os ao técnico.
4. Indica sempre a página principal no formato [Página X].
5. Termina com uma única pergunta curta e prática de despiste (ex: "Consegues medir se chegam 24VDC aos bornes da sonda no quadro?")."""

                    prompt_utilizador = f"""Página mais relevante encontrada pelo sistema: [Página {pagina_principal}]

Texto extraído das páginas do manual/esquema elétrico (já traduzido para Português):
{contexto_relevante}

Sintoma ou dúvida do técnico: "{sintoma}"

Fornece um diagnóstico curto, sem repetições, indicando os componentes a verificar na [Página {pagina_principal}]."""
                    
                    try:
                        resposta_ai, modelo_usado = gerar_resposta_groq(api_key, prompt_sistema, prompt_utilizador)
                        
                        match_pagina = re.search(r'\[P[áa]gina\s*(\d+)\]', resposta_ai, re.IGNORECASE)
                        if match_pagina:
                            num_pag_ia = int(match_pagina.group(1))
                            num_pagina_detectada = num_pag_ia if num_pag_ia in paginas else pagina_principal
                        else:
                            num_pagina_detectada = pagina_principal
                            
                        dados_resposta = {
                            "role": "assistant",
                            "content": resposta_ai,
                            "num_pagina": num_pagina_detectada
                        }
                        st.session_state.mensagens.append(dados_resposta)
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erro na comunicação com o Groq: {e}")
                        dados_fallback = {
                            "role": "assistant",
                            "content": f"A mostrar diretamente a **[Página {pagina_principal}]** encontrada no manual:",
                            "num_pagina": pagina_principal
                        }
                        st.session_state.mensagens.append(dados_fallback)
                        st.rerun()
