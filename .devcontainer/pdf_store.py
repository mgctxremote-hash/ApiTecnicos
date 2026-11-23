"""Leitura de manuais PDF (PyMuPDF), cache em disco e chunks por página.

`fitz` só é importado dentro das funções, para o resto do projeto poder ser testado sem ele.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import config, textutil
from .search import Chunk, Indice, dividir_em_chunks


@dataclass
class Manual:
    nome: str
    caminho: Path
    hash: str
    textos: list[str]        # um por página (índice 0 = página 1)
    idioma: str
    paginas_sem_texto: list[int]

    @property
    def n_paginas(self) -> int:
        return len(self.textos)

    def construir_indice(self) -> Indice:
        chunks: list[Chunk] = []
        for i, t in enumerate(self.textos, start=1):
            for parte in dividir_em_chunks(t, config.CHUNK_PALAVRAS, config.CHUNK_SOBREPOSICAO):
                chunks.append(Chunk(parte, {"pagina": i}))
        return Indice(chunks)


def listar_manuais() -> dict[str, Path]:
    return {p.name: p for p in sorted(config.PASTA_MANUAIS.glob("*.pdf"))}


def _hash_ficheiro(caminho: Path) -> str:
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def carregar_manual(caminho: Path) -> Manual:
    """Lê o PDF uma única vez; seguintes aberturas usam a cache em data/cache/<hash>.json."""
    caminho = Path(caminho)
    h = _hash_ficheiro(caminho)
    cache = config.PASTA_CACHE / f"{h}.json"
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            return Manual(caminho.name, caminho, h, d["textos"], d["idioma"], d["sem_texto"])
        except Exception:
            pass

    import fitz  # PyMuPDF
    textos, sem_texto = [], []
    with fitz.open(caminho) as doc:
        for i, pag in enumerate(doc, start=1):
            t = pag.get_text("text", sort=True).strip()
            textos.append(t)
            if len(t) < 15:
                sem_texto.append(i)
    amostra = " ".join(t for t in textos if len(t) > 40)[:6000]
    idioma = textutil.detetar_idioma(amostra)
    cache.write_text(json.dumps({"textos": textos, "idioma": idioma, "sem_texto": sem_texto}), encoding="utf-8")
    return Manual(caminho.name, caminho, h, textos, idioma, sem_texto)
