"""Assistente MGC – diagnóstico de avarias com manual + histórico Manwinwin + feedback."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core import auth, config, diagnosis, feedback, history, llm, manwinwin, pdf_store, translate, viewer

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


def _assinatura_manwinwin():
    fich = tuple((f.name, f.stat().st_mtime) for f in sorted(config.PASTA_MANWINWIN.glob("*")))
    return fich, len(feedback.casos_validados())


@st.cache_resource(show_spinner="A carregar histórico de avarias...")
def _base_casos(assinatura):
    casos, avisos = manwinwin.carregar_casos()
    n_mw = len(casos)
    casos += feedback.casos_validados()
    return manwinwin.BaseCasos(casos), avisos, n_mw


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

    base, avisos_mw, n_mw = _base_casos(_assinatura_manwinwin())
    equipamentos = ["(não indicado)"] + base.equipamentos()
    equip_sel = st.selectbox("🏭 Equipamento (melhora a pesquisa no histórico)", equipamentos)
    equipamento = None if equip_sel == "(não indicado)" else equip_sel

    st.caption(f"Manual: {manual.n_paginas} págs · idioma detetado: **{manual.idioma}**")
    if manual.paginas_sem_texto:
        st.caption(f"{len(manual.paginas_sem_texto)} págs sem texto pesquisável (só desenho).")
    st.caption(f"Histórico: {n_mw} avarias Manwinwin · {len(base.casos) - n_mw} casos validados")
    for a in avisos_mw:
        st.warning(a)
    if n_mw == 0:
        st.info("Sem dados do Manwinwin. Copie o export (.xlsx/.csv) para data/manwinwin/.")

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
                with st.expander(f"📚 {len(msg['casos'])} casos parecidos no histórico"):
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
            with st.spinner("A consultar o manual e o histórico de avarias..."):
                consulta = diagnosis.reescrever_consulta(pergunta, hist_antes, usar_llm=reescrever and ok_llm)
                trechos = indice.procurar(consulta, k=config.TOP_CHUNKS_MANUAL)
                casos = base.procurar(consulta, equipamento, k=config.TOP_CASOS_MANWINWIN)
            msgs = diagnosis.montar_mensagens(pergunta, hist_antes, trechos, casos, manual.nome,
                                              equipamento, manual.idioma)
            paginas_busca = []
            for ch, _ in trechos:
                if ch.meta["pagina"] not in paginas_busca:
                    paginas_busca.append(ch.meta["pagina"])
            casos_resumo = [{"id": (f"OT {c.id}" if c.origem == "Manwinwin" else c.id), "data": c.data,
                             "equipamento": c.equipamento, "avaria": c.avaria, "causa": c.causa,
                             "solucao": c.solucao} for c, _ in casos]
            try:
                resposta = st.write_stream(llm.gerar_stream(msgs))
                erro = None
            except llm.LLMErro as e:
                resposta, erro = "", str(e)

            if erro or not resposta.strip():
                resposta = ("⚠️ O modelo de IA não respondeu (" + (erro or "resposta vazia") + "). "
                            "Mostro-lhe apenas o que encontrei no manual e no histórico — consulte as páginas e os casos abaixo.")
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
