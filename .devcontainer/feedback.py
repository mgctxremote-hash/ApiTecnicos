"""Registo de feedback "resolveu / não resolveu" em SQLite (um ficheiro, sem servidor).

Os casos marcados como "resolveu" com solução real alimentam a pesquisa como casos validados.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from contextlib import contextmanager

from . import config
from .casos import Caso

RESULTADOS = ("resolveu", "parcial", "nao_resolveu")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    utilizador TEXT NOT NULL,
    manual TEXT,
    equipamento TEXT,
    pergunta TEXT,
    resposta TEXT,
    paginas TEXT,
    casos_usados TEXT,
    resultado TEXT,
    causa_real TEXT,
    solucao_real TEXT,
    nota TEXT
);
"""


@contextmanager
def _ligar():
    con = sqlite3.connect(config.FICHEIRO_FEEDBACK_DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def registar_resposta(utilizador, manual, equipamento, pergunta, resposta, paginas, casos_usados) -> int:
    """Guarda cada resposta dada (resultado vazio até o técnico avaliar). Devolve o id."""
    with _ligar() as con:
        cur = con.execute(
            "INSERT INTO feedback (ts, utilizador, manual, equipamento, pergunta, resposta, paginas, casos_usados)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), utilizador, manual, equipamento or "", pergunta, resposta,
             json.dumps(list(paginas)), json.dumps(list(casos_usados))),
        )
        return cur.lastrowid


def avaliar(id_: int, resultado: str, causa_real: str = "", solucao_real: str = "", nota: str = "") -> None:
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado inválido: {resultado}")
    with _ligar() as con:
        con.execute(
            "UPDATE feedback SET resultado=?, causa_real=?, solucao_real=?, nota=? WHERE id=?",
            (resultado, causa_real.strip(), solucao_real.strip(), nota.strip(), id_),
        )


def obter(id_: int) -> dict | None:
    with _ligar() as con:
        r = con.execute("SELECT * FROM feedback WHERE id=?", (id_,)).fetchone()
        return dict(r) if r else None


def casos_validados() -> list[Caso]:
    """Casos 'resolveu' com solução escrita pelo técnico -> entram na pesquisa."""
    with _ligar() as con:
        linhas = con.execute(
            "SELECT * FROM feedback WHERE resultado='resolveu' AND TRIM(COALESCE(solucao_real,''))<>''"
        ).fetchall()
    return [
        Caso(id=f"FB{r['id']}", origem="Feedback", data=r["ts"][:10], equipamento=r["equipamento"] or "",
             avaria=r["pergunta"] or "", causa=r["causa_real"] or "", solucao=r["solucao_real"])
        for r in linhas
    ]


def estatisticas() -> dict:
    with _ligar() as con:
        tot = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        por = {r[0] or "sem avaliação": r[1] for r in
               con.execute("SELECT resultado, COUNT(*) FROM feedback GROUP BY resultado")}
    return {"total": tot, "por_resultado": por}


def exportar_csv() -> str:
    with _ligar() as con:
        linhas = con.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    buf = io.StringIO()
    if linhas:
        w = csv.DictWriter(buf, fieldnames=linhas[0].keys())
        w.writeheader()
        for r in linhas:
            w.writerow(dict(r))
    return buf.getvalue()
