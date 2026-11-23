"""Montagem do prompt de diagnóstico, regras de segurança e formatação das fontes.

Princípio: o sistema SUGERE, nunca ordena. Só afirma o que está nas fontes (manual e casos
validados por técnicos) ou rotula como conhecimento geral a confirmar.
"""
from __future__ import annotations

import re

from . import llm
from .casos import Caso
from .search import Chunk, reescrever_consulta_simples

PROMPT_SISTEMA = """És um assistente de apoio ao diagnóstico para técnicos de manutenção de máquinas têxteis e quadros elétricos. Falas Português de Portugal industrial (bornes, malha, disjuntor, cartão analógico).

O TEU PAPEL: SUGERIR, nunca decidir nem ordenar. O técnico é quem decide e executa; um erro teu pode causar danos ou acidentes.

REGRAS OBRIGATÓRIAS
1. Usa APENAS as fontes fornecidas: trechos do manual e casos já resolvidos e validados por técnicos. O conhecimento geral só pode aparecer rotulado como "(conhecimento geral – confirmar)".
2. NUNCA inventes bornes, pinos, referências, valores de tensão ou parâmetros. Se o manual não o indica, diz exatamente: "Não encontrei isso no manual fornecido."
3. Formula sempre como recomendação ou pergunta, por exemplo: "O que acha de medir a tensão entre os bornes X1.1 e X1.2? Deve rondar 24 V segundo [Manual p.12]." Nunca uses imperativos secos.
4. Cita a origem de cada afirmação: [Manual p.N] para o manual, [FBid] para casos validados por técnicos.
5. Lê a conversa: não repitas testes que o técnico já fez; avança para a hipótese seguinte.
6. Se vários casos antigos apontam a mesma causa, diz quantos e com que frequência; se são só vagamente parecidos, di-lo.
7. Os trechos do manual podem estar noutro idioma (inglês, alemão...). Responde sempre em português e traduz os termos técnicos.
8. Se a informação for insuficiente, faz UMA pergunta curta ao técnico (modelo da máquina, código de erro, o que mudou) em vez de adivinhar.

FORMATO (curto, sem enrolar)
**Leitura do problema:** 1–2 frases.
**Hipóteses (da mais para a menos provável):** lista numerada, cada uma com o porquê e a fonte.
**Próximo passo sugerido:** UM só passo, em forma de pergunta/recomendação, de preferência o mais simples e seguro primeiro (inspeção visual, ligações, fusíveis) antes de medições.
**Fontes consultadas:** lista curta."""

AVISO_SEGURANCA = (
    "⚠️ **Segurança:** medições em quadros energizados só por pessoal habilitado e seguindo o procedimento da empresa "
    "(corte, bloqueio e verificação de ausência de tensão). Estas sugestões podem estar erradas — confirme no esquema "
    "e com o responsável antes de intervir."
)

_RE_MEDICAO = re.compile(
    r"\b(medi\w*|tens[aã]o|volt\w*|\d+\s?v\b|vdc|vac|ma\b|mult[ií]metro|continuidade|resist[eê]ncia|bornes?|cabo|alimenta\w*)",
    re.IGNORECASE,
)


def precisa_aviso_seguranca(resposta: str) -> bool:
    return bool(_RE_MEDICAO.search(resposta))


def formatar_trechos(trechos: list[tuple[Chunk, float]]) -> str:
    if not trechos:
        return "(nenhum trecho relevante encontrado no manual)"
    return "\n\n".join(f"[Manual p.{c.meta['pagina']}]\n{c.texto}" for c, _ in trechos)


def formatar_casos(casos: list[tuple[Caso, float]]) -> str:
    if not casos:
        return "(ainda sem casos parecidos registados)"
    linhas = []
    for c, _ in casos:
        etiqueta = c.id
        linhas.append(
            f"[{etiqueta}] {c.data} | Equip.: {c.equipamento or '?'} | Avaria: {c.avaria or '?'} | "
            f"Causa: {c.causa or 'não registada'} | Solução: {c.solucao or 'não registada'}"
            + (" | VALIDADO por técnico" if c.origem == "Feedback" else "")
        )
    return "\n".join(linhas)


def montar_mensagens(pergunta: str, historico: list[dict], trechos, casos, manual_nome: str,
                     equipamento: str | None, idioma_manual: str, max_hist: int = 6) -> list[dict]:
    contexto = (
        f"MANUAL: {manual_nome} (idioma: {idioma_manual})\n"
        f"EQUIPAMENTO: {equipamento or 'não indicado'}\n\n"
        f"TRECHOS DO MANUAL:\n{formatar_trechos(trechos)}\n\n"
        f"CASOS PARECIDOS JÁ RESOLVIDOS:\n{formatar_casos(casos)}\n\n"
        f"MENSAGEM ATUAL DO TÉCNICO: {pergunta}"
    )
    msgs = [{"role": "system", "content": PROMPT_SISTEMA}]
    for m in historico[-max_hist:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": contexto})
    return msgs


def reescrever_consulta(pergunta: str, historico: list[dict], usar_llm: bool = True) -> str:
    """'E agora?' sozinho não pesquisa nada: junta contexto da conversa numa consulta autónoma."""
    if not historico:
        return pergunta
    simples = reescrever_consulta_simples(historico, pergunta)
    if not usar_llm:
        return simples
    try:
        resumo = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in historico[-4:])
        saida = llm.gerar(
            [{"role": "system", "content": "Reescreve a última mensagem do técnico como UMA consulta de pesquisa "
                                           "autónoma (máx. 25 palavras, português, termos técnicos, códigos de erro "
                                           "exatos). Responde só com a consulta."},
             {"role": "user", "content": f"Conversa:\n{resumo}\n\nÚltima mensagem: {pergunta}"}],
            max_tokens=80, temperatura=0.0)
        return (saida.splitlines()[0].strip() if saida else simples) or simples
    except Exception:
        return simples


def paginas_citadas(resposta: str, n_paginas: int) -> list[int]:
    pags = []
    for m in re.finditer(r"\[Manual p\.?\s*(\d+)\]", resposta, re.IGNORECASE):
        p = int(m.group(1))
        if 1 <= p <= n_paginas and p not in pags:
            pags.append(p)
    return pags
