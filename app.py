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
# CONFIGURAÇÃO DE PÁGINA
# ---------------------------------------------------------
st.set_page_config(page_title="Assistente MGC - Manuais", page_icon="🔧", layout="centered")

# APENAS PARA USO LOCAL NO PC (Deixa vazio "" se fores enviar para o GitHub)
CHAVE_LOCAL_FIXA = ""

# Pasta onde ficam guardados os manuais fixos
PASTA_MANUAIS = "manuais"
os.makedirs(PASTA_MANUAIS, exist_ok=True)

# Ficheiro local para persistir a chave API
FICHEIRO_CONFIG_LOCAL = ".groq_key.json"

# Cache global em memória para traduções (Thread-safe)
CACHE_TRADUCOES = {}

# ---------------------------------------------------------
# INICIALIZAÇÃO DE SESSÃO E LOGIN
# ---------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "utilizador_atual" not in st.session_state:
    st.session_state.utilizador_atual = ""
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
if "pagina_ativa" not in st.session_state:
    st.session_state.pagina_ativa = None

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
    """Analisa uma amostra do manual para detetar se está noutra língua."""
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
    """Filtra apenas palavras reais e ignora códigos puros de esquemas."""
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
# GESTÃO DE CHAVES E CONFIGURAÇÃO
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
# TELA DE LOGIN OBRIGATÓRIA
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.markdown("<h2 style='text-align: center;'>🔧 Assistente MGC - Manuais Técnicos</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Introduza as credenciais da equipa para aceder à central.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("form_login"):
            utilizador_input = st.text_input("Nome de Usuário (Ex: Bruno, Alexandre, João)")
            chave_input = st.text_input("Chave de Acesso MGC", type="password")
            
            chave_sistema = obter_chave_oculta()
            api_key_input = ""
            if not chave_sistema:
                api_key_input = st.text_input("Groq API Key (Primeiro acesso)", type="password", help="Obtenha gratuitamente em console.groq.com/keys")
            
            submeter = st.form_submit_button("Entrar no Sistema", use_container_width=True)
            
            if submeter:
                pin_correto = obter_pin_seguro()
                if chave_input.strip() == pin_correto and utilizador_input.strip():
                    st.session_state.autenticado = True
                    st.session_state.utilizador_atual = utilizador_input.strip()
                    if api_key_input.strip():
                        guardar_chave_local(api_key_input.strip())
                    st.success("Autenticação bem-sucedida! A carregar...")
                    st.rerun()
                else:
                    st.error("Chave de Acesso MGC incorreta ou Nome de Usuário em falta.")
    st.stop()

# ---------------------------------------------------------
# FUNÇÕES CORE DE PROCESSAMENTO DE PDF
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
        barra = st.progress(0, text=f"A traduzir manual para Português...")
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
                barra.progress(concluido / total, text=f"A traduzir manual ({concluido}/{total} págs)...")
        barra.empty()
        return textos_traduzidos
        
    return textos_originais

def gerar_indice_bm25(textos):
    corpus_tokenizado = []
    for texto in textos:
        texto_limpo = re.sub(r'[^\w\s]', ' ', texto.lower())
        corpus_tokenizado.append(texto_limpo.split())
    return BM25Okapi(corpus_tokenizado)

def corrigir_termo_por_aproximacao(sintoma, textos_paginas):
    palavras_manual = set()
    for txt in textos_paginas:
        for p in re.findall(r'[A-Za-zÀ-ÿ]{4,}', txt.lower()):
            palavras_manual.add(p)
            
    termos_utilizador = re.findall(r'[A-Za-zÀ-ÿ]{4,}', sintoma.lower())
    correcoes_feitas = {}
    
    for termo in termos_utilizador:
        if termo not in palavras_manual:
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

def procurar_paginas_relevantes(sintoma, textos, bm25, pagina_atual=None, top_k=4):
    total_pags = len(textos)
    paginas_alvo = []

    match_pag_pergunta = re.search(r'p[áa]g(?:ina)?\.?\s*(\d+)', sintoma, re.IGNORECASE)
    if match_pag_pergunta:
        pag_citada = int(match_pag_pergunta.group(1))
        if 1 <= pag_citada <= total_pags:
            paginas_alvo.append(pag_citada)

    sintoma_limpo = re.sub(r'[^\w\s]', ' ', sintoma.lower())
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
    for num_p in paginas_alvo[:5]:
        texto_limpo = re.sub(r'\n+', '\n', textos[num_p - 1])
        etiqueta = " (PÁGINA ATUALMENTE ABERTA PELO TÉCNICO)" if num_p == pagina_atual else ""
        contexto += f"\n\n--- PÁGINA {num_p}{etiqueta} ---\n{texto_limpo}"

    return contexto, paginas_alvo

def extrair_imagem_pagina(num_pagina, traduzir_visualmente=True, nivel_zoom=3.5):
    """Gera a imagem em alta resolução nativa. O zoom é feito por pinch-to-zoom ou wheel no ecrã cheio."""
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
                
        modelos_filtrados.sort(key=lambda n: 0 if "70b" in n.lower() else (1 if "32b" in n.lower() else 2))
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
                max_tokens=600,
                top_p=0.9,
            )
            return chat_completion.choices[0].message.content, nome_modelo
        except Exception as e:
            ultimo_erro = str(e)
            continue
            
    raise Exception(f"Nenhum modelo disponível respondeu. Último erro: {ultimo_erro}")

# ---------------------------------------------------------
# INTERFACE PRINCIPAL (STREAMLIT)
# ---------------------------------------------------------
st.title("🔧 Assistente MGC - Manuais")

api_key = obter_chave_oculta()

with st.sidebar:
    st.success(f"👤 Técnico: **{st.session_state.utilizador_atual}**")
    st.divider()
    
    st.header("📚 Manuais da Máquina")
    manuais_disponiveis = listar_manuais_fixos()
    opcoes_select = list(manuais_disponiveis.keys())
    
    manual_escolhido_nome = None
    bytes_para_processar = None

    if opcoes_select:
        manual_escolhido_nome = st.selectbox("Selecionar Manual Fixo:", options=opcoes_select, index=0)

    with st.expander("➕ Adicionar / Carregar PDF"):
        ficheiro_upload = st.file_uploader("Escolher ficheiro PDF", type="pdf")
        if ficheiro_upload is not None:
            caminho_guardar = os.path.join(PASTA_MANUAIS, ficheiro_upload.name)
            if not os.path.exists(caminho_guardar):
                with open(caminho_guardar, "wb") as f_out:
                    f_out.write(ficheiro_upload.getbuffer())
                st.success("Manual guardado nos fixos!")
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

    ativar_traducao_manual = st.checkbox("🌐 Ativar Tradução Automática PT (Se estrangeiro)", value=False)

    if bytes_para_processar and not st.session_state.pdf_processado and api_key:
        with st.spinner(f"A indexar '{manual_escolhido_nome}'..."):
            st.session_state.textos_paginas = processar_bytes_pdf(bytes_para_processar, ativar_traducao=ativar_traducao_manual)
            st.session_state.bm25_index = gerar_indice_bm25(st.session_state.textos_paginas)
            listar_modelos_chat_groq(api_key)
            st.session_state.pdf_processado = True

    if st.session_state.pdf_processado:
        total_pags = len(st.session_state.textos_paginas)
        st.success(f"Ativo: {st.session_state.ultimo_pdf_nome} ({total_pags} págs)")
        
        traduzir_img_op = st.checkbox("Traduzir textos na imagem para PT", value=ativar_traducao_manual)
        
        pag_selecionada = st.number_input("Página em leitura / foco:", min_value=1, max_value=total_pags, value=st.session_state.pagina_ativa or 1, step=1)
        st.session_state.pagina_ativa = pag_selecionada
        
        st.divider()
        if st.button("🗑️ Limpar Conversa", use_container_width=True, type="secondary"):
            st.session_state.mensagens = []
            st.rerun()
            
        if st.button("🚪 Terminar Sessão", use_container_width=True):
            st.session_state.autenticado = False
            st.rerun()
    else:
        traduzir_img_op = False

# Histórico de Mensagens
total_paginas_doc = len(st.session_state.textos_paginas)

for idx_msg, msg in enumerate(st.session_state.mensagens):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "num_pagina" in msg and st.session_state.pdf_processado:
            pag_atual = msg["num_pagina"]
            
            with st.spinner(f"A gerar esquema (Página {pag_atual})..."):
                # Resolução fixa otimizada (3.5x), garantindo nitidez sem sobrecarregar a memória
                img_exibir = extrair_imagem_pagina(pag_atual, traduzir_visualmente=traduzir_img_op, nivel_zoom=3.5)
            
            # Imagem limpa com suporte nativo a zoom por gesto (dois dedos) ou wheel (rato) ao abrir em ecrã cheio
            st.image(img_exibir, caption=f"Página {pag_atual} de {total_paginas_doc} (Clique no ícone de expandir para zoom em ecrã cheio)", use_container_width=True)
            
            col_ant, col_meio, col_prox = st.columns([1, 1, 1])
            with col_ant:
                if st.button(f"⬅️ Página {pag_atual - 1}", key=f"ant_{idx_msg}_{pag_atual}", disabled=(pag_atual <= 1), use_container_width=True):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual - 1
                    st.session_state.pagina_ativa = pag_atual - 1
                    st.rerun()
            with col_meio:
                st.markdown(f"<div style='text-align:center; padding-top:6px; font-weight:bold;'>📄 Pág. {pag_atual} / {total_paginas_doc}</div>", unsafe_allow_html=True)
            with col_prox:
                if st.button(f"Página {pag_atual + 1} ➡️", key=f"prox_{idx_msg}_{pag_atual}", disabled=(pag_atual >= total_paginas_doc), use_container_width=True):
                    st.session_state.mensagens[idx_msg]["num_pagina"] = pag_atual + 1
                    st.session_state.pagina_ativa = pag_atual + 1
                    st.rerun()

# Input de Sintoma
sintoma = st.chat_input("Faz uma pergunta sobre a página ou descreve uma avaria...")

if sintoma:
    if not st.session_state.pdf_processado:
        st.warning("Seleciona ou carrega primeiro um manual PDF na barra lateral!")
    else:
        sintoma_processado, termo_sugerido = corrigir_termo_por_aproximacao(sintoma, st.session_state.textos_paginas)
        
        texto_exibir_utilizador = sintoma
        if termo_sugerido:
            texto_exibir_utilizador = f"{sintoma} *(Assumi que procuravas por **{termo_sugerido}** — confirma-se?)*"
            
        with st.chat_message("user"):
            st.markdown(texto_exibir_utilizador)
            
        with st.chat_message("assistant"):
            with st.spinner("A consultar o manual e a analisar o esquema..."):
                contexto_relevante, paginas = procurar_paginas_relevantes(
                    sintoma_processado, 
                    st.session_state.textos_paginas, 
                    st.session_state.bm25_index,
                    pagina_atual=st.session_state.pagina_ativa,
                    top_k=4
                )
                
                if not paginas:
                    st.warning("Não foi possível localizar informação relevante no manual.")
                else:
                    pagina_principal = paginas[0]
                    
                    prompt_sistema = """És um engenheiro eletromecânico e técnico sénior de manutenção e automação industrial em Portugal.
A tua função é responder a dúvidas técnicas e ajudar no diagnóstico de avarias combinando TODOS os dados fornecidos do manual/esquema elétrico com o teu conhecimento sólido de engenharia industrial.

REGRAS OBRIGATÓRIAS DE RESPOSTA:
1. Escreve EXCLUSIVAMENTE em Português de Portugal correto, claro e direto, sem repetir frases ou palavras.
2. RESPOSTA COMPLETA E DIRETA: Se o técnico fizer uma pergunta específica (sobre pinos, cabos, bornes, polaridades Uv, I+, Power, Signal, 24VDC, 0V, PE), responde diretamente e de forma completa cruzando os dados do manual com as normas industriais. Nunca ocultes a resposta.
3. Se o técnico relatar uma avaria, explica a causa técnica, indica os componentes e bornes exatos a medir e sugere o próximo passo prático.
4. Sempre que citares dados do documento, indica a página no formato [Página X]."""

                    prompt_utilizador = f"""Técnico em sessão: {st.session_state.utilizador_atual}
Manual ativo: {st.session_state.ultimo_pdf_nome}
Página em foco no ecrã: [Página {st.session_state.pagina_ativa}]
Páginas analisadas no manual: {paginas}

Dados extraídos do manual e esquemas elétricos:
{contexto_relevante}

Pergunta ou sintoma do técnico: "{sintoma_processado}"

Responde de forma técnica, clara e completa combinando os dados destas páginas do manual com o teu conhecimento de manutenção industrial."""
                    
                    try:
                        historico_curto = st.session_state.mensagens[-4:]
                        resposta_ai, modelo_usado = gerar_resposta_groq(api_key, prompt_sistema, historico_curto, prompt_utilizador)
                        
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
                        st.rerun()
                        
                    except Exception as e:
                        st.session_state.mensagens.append({"role": "user", "content": texto_exibir_utilizador})
                        st.error(f"Erro na comunicação com o Groq: {e}")
                        dados_fallback = {
                            "role": "assistant",
                            "content": f"A mostrar diretamente a **[Página {pagina_principal}]** encontrada no manual:",
                            "num_pagina": pagina_principal
                        }
                        st.session_state.mensagens.append(dados_fallback)
                        st.rerun()
