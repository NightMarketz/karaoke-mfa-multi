"""Trechos de 20-30 s a partir da letra e dos tempos alinhados (logica pura)."""
import re
import unicodedata
from collections import Counter

TRECHO_MIN_S: float = 20.0
TRECHO_MAX_S: float = 30.0


def normaliza(texto: str) -> str:
    """Minusculas, sem acento nem pontuacao, espacos colapsados."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpo = re.sub(r"[^\w\s]", " ", sem_acento.lower())
    return " ".join(limpo.split())


def versos_da_letra(linhas: list[str], palavras: list[dict]) -> list[dict]:
    """Um verso por linha nao vazia; consome `palavras` em sequencia (um token cada).

    Mesma regra de ass_builder.group_words_by_lyrics_lines; linha em branco
    incrementa a estrofe.
    """
    tokens_por_linha = [linha.split() for linha in linhas]
    n_tokens = sum(len(t) for t in tokens_por_linha)
    if n_tokens != len(palavras):
        raise ValueError(
            f"{n_tokens} tokens na letra != {len(palavras)} palavras alinhadas"
        )

    versos: list[dict] = []
    idx = 0
    estrofe = 0
    pendente = False  # ha verso na estrofe atual
    for tokens in tokens_por_linha:
        if not tokens:
            if pendente:
                estrofe += 1
                pendente = False
            continue
        fatia = palavras[idx: idx + len(tokens)]
        idx += len(tokens)
        pals = [
            {"texto": tok, "inicio": float(p["start"]), "fim": float(p["end"])}
            for tok, p in zip(tokens, fatia)
        ]
        versos.append({
            "texto": " ".join(tokens),
            "inicio": pals[0]["inicio"],
            "fim": pals[-1]["fim"],
            "estrofe": estrofe,
            "palavras": pals,
        })
        pendente = True
    return versos


def trechos(versos: list[dict]) -> list[dict]:
    """Trechos sem sobreposicao de 20-30 s; versos repetidos (refrao) primeiro."""
    contagem = Counter(normaliza(v["texto"]) for v in versos)
    repetido = [contagem[normaliza(v["texto"])] >= 2 for v in versos]

    candidatos = []  # (-prioridade, inicio, i, j, longo)
    for i, vi in enumerate(versos):
        j = -1
        for k in range(i, len(versos)):
            if versos[k]["fim"] - vi["inicio"] <= TRECHO_MAX_S:
                j = k
            else:
                break
        if j < 0:
            j, longo = i, True
        elif versos[j]["fim"] - vi["inicio"] >= TRECHO_MIN_S:
            longo = False
        else:
            continue
        dur = versos[j]["fim"] - vi["inicio"]
        rep = sum(
            versos[k]["fim"] - versos[k]["inicio"]
            for k in range(i, j + 1) if repetido[k]
        )
        prioridade = rep / dur if dur > 0 else 0.0
        candidatos.append((-prioridade, vi["inicio"], i, j, longo))

    candidatos.sort(key=lambda c: (c[0], c[1]))
    aceitos: list[dict] = []
    for neg_prio, inicio, i, j, longo in candidatos:
        fim = versos[j]["fim"]
        if all(fim <= a["inicio"] or a["fim"] <= inicio for a in aceitos):
            aceitos.append({
                "id": len(aceitos), "inicio": inicio, "fim": fim,
                "refrao": neg_prio < 0, "longo": longo,
                "versos": versos[i: j + 1],
            })
    return aceitos


def trechos_da_letra(linhas: list[str], palavras: list[dict]) -> list[dict]:
    return trechos(versos_da_letra(linhas, palavras))
