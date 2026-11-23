"""Pesquisa BM25 em Python puro (sem dependências), sobre chunks com metadados."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import textutil


@dataclass
class Chunk:
    texto: str
    meta: dict = field(default_factory=dict)  # ex.: {"pagina": 12} ou {"os": "1234", "data": ...}


class BM25:
    def __init__(self, textos_tokenizados: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(textos_tokenizados)
        self.tf = [Counter(d) for d in textos_tokenizados]
        self.dl = [len(d) for d in textos_tokenizados]
        self.avgdl = (sum(self.dl) / self.N) if self.N else 0.0
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, consulta: list[str]) -> list[float]:
        out = [0.0] * self.N
        if not self.N:
            return out
        for t in set(consulta):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                out[i] += idf * f * (self.k1 + 1) / denom
        return out


class Indice:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25([textutil.tokenizar(c.texto) for c in chunks])

    def procurar(self, consulta: str, k: int = 5, usar_glossario: bool = True,
                 bonus_codigos: float = 3.0, filtro=None) -> list[tuple[Chunk, float]]:
        toks = textutil.tokenizar(consulta)
        if usar_glossario:
            toks = toks + textutil.expandir_com_glossario(consulta)
        sc = self.bm25.scores(toks)

        # Códigos exatos (3+ dígitos) com limites de palavra: reforço forte
        for cod in textutil.codigos_numericos(consulta):
            padrao = re.compile(r"(?<![\w.])" + re.escape(cod) + r"(?![\w.])")
            for i, c in enumerate(self.chunks):
                if padrao.search(c.texto):
                    sc[i] += bonus_codigos

        ordem = sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)
        res = []
        for i in ordem:
            if sc[i] <= 0:
                break
            if filtro and not filtro(self.chunks[i]):
                continue
            res.append((self.chunks[i], sc[i]))
            if len(res) >= k:
                break
        return res


def dividir_em_chunks(texto: str, palavras: int = 220, sobreposicao: int = 40) -> list[str]:
    """Chunks por janelas de palavras com sobreposição; respeita linhas curtas (esquemas)."""
    ps = texto.split()
    if len(ps) <= palavras:
        return [texto.strip()] if texto.strip() else []
    passo = max(1, palavras - sobreposicao)
    return [" ".join(ps[i:i + palavras]) for i in range(0, len(ps), passo)
            if ps[i:i + palavras]]


def reescrever_consulta_simples(historico: list[dict], pergunta: str, n: int = 3) -> str:
    """Fallback sem LLM: junta as últimas perguntas do técnico, para 'e agora?' ter contexto."""
    anteriores = [m["content"] for m in historico if m.get("role") == "user"][-n:]
    return " ".join(anteriores + [pergunta])
