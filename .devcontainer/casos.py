"""Histórico de avarias do próprio sistema: casos validados pelos técnicos (botão 'Resolveu')."""
from __future__ import annotations

from dataclasses import dataclass, field

from .search import Chunk, Indice


@dataclass
class Caso:
    id: str
    origem: str            # "Feedback"
    data: str = ""
    equipamento: str = ""
    avaria: str = ""
    causa: str = ""
    solucao: str = ""
    tempo: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def texto(self) -> str:
        return " ".join([self.equipamento, self.avaria, self.causa, self.solucao])


class BaseCasos:
    def __init__(self, casos: list[Caso]):
        self.casos = casos
        self.indice = Indice([Chunk(c.texto, {"idx": i}) for i, c in enumerate(casos)])

    def equipamentos(self) -> list[str]:
        return sorted({c.equipamento for c in self.casos if c.equipamento})

    def procurar(self, consulta: str, equipamento: str | None = None, k: int = 5) -> list[tuple[Caso, float]]:
        if not self.casos:
            return []
        res = []
        for ch, sc in self.indice.procurar(consulta, k=k * 4):
            caso = self.casos[ch.meta["idx"]]
            if equipamento and equipamento.lower() in caso.equipamento.lower():
                sc *= 1.5
            res.append((caso, sc))
        res.sort(key=lambda x: x[1], reverse=True)
        return res[:k]
