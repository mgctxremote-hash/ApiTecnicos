"""Tradução de uma página de esquema para PT-PT, usando o mesmo LLM (sem serviços externos).

Estratégia:
  1. extrai blocos de texto horizontais da página (PyMuPDF);
  2. traduz em lotes numerados com glossário técnico fixo;
  3. guarda em cache (por manual+página);
  4. desenha a tradução sobre a página SEM apagar linhas/símbolos (redação só de texto, sem fundo branco).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import config, llm, textutil

GLOSSARIO_PROMPT = (
    "terminal=borne; shield=malha; breaker/circuit breaker=disjuntor; relay=relé; contactor=contactor; "
    "fuse=fusível; power supply=fonte de alimentação; analog input=entrada analógica; "
    "analog output=saída analógica; emergency stop=paragem de emergência; safety=segurança; "
    "inverter/drive=variador; probe/sensor=sonda/sensor; cable=cabo; wire=fio; fault=falha; "
    "supply voltage=tensão de alimentação; loom/knitting machine=tear/máquina de malha. "
    "Mantém INALTERADOS: referências (X1, K3, -F2, Q01), valores e unidades (24VDC, 4-20mA), siglas (PLC, PE, PT100)."
)

_RE_SO_CODIGO = re.compile(r"^[\W\d_A-Za-z]{0,6}$")


def precisa_traduzir(texto: str) -> bool:
    palavras = re.findall(r"[A-Za-zÀ-ÿ]{4,}", texto)
    return len(palavras) > 0 and not _RE_SO_CODIGO.match(texto.strip())


def _caminho_cache(hash_manual: str, pagina: int, idioma_origem: str) -> Path:
    chave = hashlib.sha1(f"{hash_manual}|{pagina}|{idioma_origem}|{config.LLM_PROVIDER}".encode()).hexdigest()
    return config.PASTA_CACHE / f"trad_{chave}.json"


def extrair_blocos(pdf_path: Path, pagina: int) -> list[dict]:
    """[{bbox:(x0,y0,x1,y1), texto, tamanho}] só de texto horizontal com letras."""
    import fitz
    blocos = []
    with fitz.open(pdf_path) as doc:
        d = doc.load_page(pagina - 1).get_text("dict")
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        linhas = b.get("lines", [])
        if not linhas or any(tuple(round(x, 2) for x in l.get("dir", (1, 0))) != (1.0, 0.0) for l in linhas):
            continue
        texto = " ".join("".join(s.get("text", "") for s in l.get("spans", [])).strip() for l in linhas).strip()
        if len(texto) < 3 or not precisa_traduzir(texto):
            continue
        tam = linhas[0]["spans"][0].get("size", 8.0) if linhas[0].get("spans") else 8.0
        blocos.append({"bbox": tuple(b["bbox"]), "texto": texto, "tamanho": tam})
    return blocos


def _traduzir_lote(textos: list[str], idioma_origem: str) -> list[str]:
    entrada = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(textos))
    sistema = (
        "És tradutor técnico de manuais de máquinas têxteis e quadros elétricos. "
        f"Traduz do idioma '{idioma_origem}' para Português de Portugal. Glossário: {GLOSSARIO_PROMPT} "
        "Responde APENAS com as linhas traduzidas, no mesmo formato '[n] texto', uma por linha, sem comentários."
    )
    saida = llm.gerar([{"role": "system", "content": sistema}, {"role": "user", "content": entrada}],
                      max_tokens=2500, temperatura=0.0)
    mapa = {int(n): t.strip() for n, t in re.findall(r"^\[(\d+)\]\s*(.+)$", saida, re.MULTILINE)}
    return [mapa.get(i + 1, textos[i]) for i in range(len(textos))]   # se faltar, mantém original


def traduzir_pagina(pdf_path: Path, hash_manual: str, pagina: int, idioma_origem: str) -> list[dict]:
    """Devolve blocos com campo 'traducao'. Usa cache em disco."""
    cache = _caminho_cache(hash_manual, pagina, idioma_origem)
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    blocos = extrair_blocos(pdf_path, pagina)
    for i in range(0, len(blocos), 25):
        lote = blocos[i:i + 25]
        for b, t in zip(lote, _traduzir_lote([b["texto"] for b in lote], idioma_origem)):
            b["traducao"] = t
    cache.write_text(json.dumps(blocos), encoding="utf-8")
    return blocos


def _latin1(t: str) -> str:
    for a, b in {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "º": "o", "ª": "a"}.items():
        t = t.replace(a, b)
    return t.encode("latin-1", "ignore").decode("latin-1")


def aplicar_traducao_na_pagina(pagina_fitz, blocos: list[dict]) -> None:
    """Substitui o texto original pela tradução, preservando desenho vetorial e imagens."""
    import fitz
    validos = [b for b in blocos if b.get("traducao") and b["traducao"].strip().lower() != b["texto"].strip().lower()]
    for b in validos:
        pagina_fitz.add_redact_annot(fitz.Rect(b["bbox"]), fill=False)   # sem fundo: não apaga fios
    pagina_fitz.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
    )
    for b in validos:
        r = fitz.Rect(b["bbox"])
        txt = _latin1(b["traducao"])
        tam = max(min(b["tamanho"], 12.0), 4.0)
        while tam >= 3.2:
            sobra = pagina_fitz.insert_textbox(r, txt, fontsize=tam, fontname="helv", color=(0, 0, 0.55))
            if sobra >= 0:
                break
            tam -= 0.5
        else:   # não coube: escreve em linha única, comprimida
            pagina_fitz.insert_text((r.x0, r.y1 - 1), txt, fontsize=3.2, fontname="helv", color=(0, 0, 0.55))
