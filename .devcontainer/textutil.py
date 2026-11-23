"""Utilitários de texto: normalização, tokenização, glossário técnico PT <-> EN/DE."""
from __future__ import annotations

import re
import unicodedata

_STOP = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "um", "uma", "em", "no", "na", "nos", "nas",
    "que", "com", "para", "por", "se", "ao", "mas", "ja", "já", "esta", "está", "tem", "foi", "ser",
    "the", "of", "and", "to", "in", "is", "for", "on", "with", "der", "die", "das", "und", "den", "zu",
}


def sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sem acentos, preserva códigos tipo -999, E-102, 4-20ma, X1.3."""
    t = sem_acentos(texto.lower())
    t = re.sub(r"[^\w\-\.\s]", " ", t)
    toks = []
    for tok in t.split():
        tok = tok.strip(".-_") if not re.fullmatch(r"-\d+", tok) else tok
        if not tok or tok in _STOP:
            continue
        toks.append(tok)
        # também indexa as partes de tokens compostos (x1.3 -> x1, 3 ; e-102 -> e, 102)
        partes = [p for p in re.split(r"[\-\.]", tok) if len(p) >= 2 and p != tok]
        toks.extend(partes)
    return toks


def codigos_numericos(texto: str) -> list[str]:
    """Números de 3+ dígitos (códigos de erro, endereços). Evita '1', '24', etc."""
    return re.findall(r"(?<![\w.])-?\d{3,}(?![\w.])", texto)


# Glossário mínimo para ponte de idiomas na pesquisa (PT -> EN/DE). Expandir conforme os manuais.
GLOSSARIO = {
    "borne": ["terminal", "klemme"],
    "bornes": ["terminals", "klemmen"],
    "malha": ["shield", "schirm"],
    "disjuntor": ["breaker", "circuit breaker", "leistungsschalter"],
    "rele": ["relay", "relais"],
    "contactor": ["contactor", "schutz"],
    "fusivel": ["fuse", "sicherung"],
    "sonda": ["probe", "sensor", "fuehler"],
    "temperatura": ["temperature", "temperatur"],
    "pressao": ["pressure", "druck"],
    "motor": ["motor", "drive"],
    "variador": ["inverter", "drive", "frequenzumrichter"],
    "alimentacao": ["supply", "power supply", "versorgung"],
    "fonte": ["power supply", "netzteil"],
    "tensao": ["voltage", "spannung"],
    "corrente": ["current", "strom"],
    "cartao": ["card", "module", "karte", "baugruppe"],
    "analogico": ["analog", "analogue"],
    "entrada": ["input", "eingang"],
    "saida": ["output", "ausgang"],
    "paragem": ["stop", "emergency", "halt"],
    "emergencia": ["emergency", "not-aus", "e-stop"],
    "seguranca": ["safety", "sicherheit"],
    "falha": ["fault", "failure", "error", "stoerung"],
    "erro": ["error", "fault", "fehler"],
    "alarme": ["alarm", "alarm"],
    "cabo": ["cable", "kabel"],
    "esquema": ["diagram", "schematic", "schaltplan"],
    "lista": ["list", "liste"],
    "agulha": ["needle", "nadel"],
    "fio": ["thread", "yarn", "wire", "faden"],
    "tear": ["loom", "knitting machine", "webmaschine", "strickmaschine"],
    "sensor": ["sensor", "sensor"],
    "encoder": ["encoder", "geber"],
    "ventilador": ["fan", "luefter"],
    "bomba": ["pump", "pumpe"],
    "comunicacao": ["communication", "kommunikation"],
    "profibus": ["profibus"],
    "reset": ["reset", "ruecksetzen"],
}


def expandir_com_glossario(texto: str, limite: int = 12) -> list[str]:
    extra: list[str] = []
    for tok in tokenizar(texto):
        if tok in GLOSSARIO:
            for e in GLOSSARIO[tok]:
                extra.extend(tokenizar(e))
    return extra[:limite * 3]


_PALAVRAS_IDIOMA = {
    "pt": {"de", "do", "da", "que", "para", "com", "nao", "uma", "os", "as", "em", "por", "ao", "se"},
    "en": {"the", "and", "of", "to", "is", "for", "with", "on", "not", "check", "connect", "must"},
    "de": {"der", "die", "und", "nicht", "ist", "mit", "fuer", "von", "den", "das", "ein", "zu"},
    "es": {"el", "los", "las", "con", "para", "por", "una", "del", "que", "no"},
    "it": {"il", "della", "con", "per", "non", "una", "che", "di", "sono"},
    "fr": {"le", "les", "des", "est", "pour", "avec", "une", "pas", "de", "du"},
}


def detetar_idioma(texto: str) -> str:
    """Heurística offline por stopwords. Devolve pt/en/de/es/it/fr (defeito pt)."""
    palavras = re.findall(r"[a-z]+", sem_acentos(texto.lower()))
    if len(palavras) < 20:
        return "pt"
    pontos = {l: sum(1 for p in palavras if p in conj) for l, conj in _PALAVRAS_IDIOMA.items()}
    melhor = max(pontos, key=pontos.get)
    return melhor if pontos[melhor] > 0 else "pt"
