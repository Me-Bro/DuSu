"""Grammar Lab - wrong versions of a correct sentence (test helper, pure).  `wrongs(sentence)` yields (kind, text): a helping verb dropped, a helping verb swapped inside its family,
a verb put into every OTHER form.  A correct sentence must be accepted and every one of these must NOT be."""
import re
import sys
sys.path.insert(0, "backend")
from app.grammar import lexicon as L
from app.lab import forms as F

SWAP = {"is": ("are", "am"), "are": ("is",), "am": ("is", "are"), "was": ("were",), "were": ("was",), "has": ("have",), "have": ("has",), "does": ("do",), "do": ("does",)}


def _words(sentence: str) -> list:
    return re.findall(r"[A-Za-z']+|[^A-Za-z'\s]+", sentence)


def _join(ws: list) -> str:
    out = ""
    for w in ws:
        out += (w if (not out or re.fullmatch(r"[.,?!;:]+", w)) else " " + w)
    return out


def wrongs(sentence: str, limit: int = 14) -> list:
    ws = _words(sentence)
    out: list = []
    seen = {" ".join(F.norm_tokens(sentence))}

    def add(kind, new_ws):
        t = _join(new_ws)
        key = " ".join(F.norm_tokens(t))
        if key and key not in seen:
            seen.add(key)
            out.append((kind, t))

    low = [w.lower() for w in ws]
    for i, w in enumerate(low):                                   # a helping verb dropped / swapped
        if w in F.AUX and w not in ("not",) and w not in F.MODALS:
            add(f"drop:{w}", ws[:i] + ws[i + 1:])
        if w in SWAP:
            for r in SWAP[w]:
                add(f"swap:{w}>{r}", ws[:i] + [r.capitalize() if ws[i][:1].isupper() else r] + ws[i + 1:])
    for i, w in enumerate(low):                                   # a verb in every other form
        k = F.kinds(w)
        b = F.lemma(w)
        if not k or b == w and "base" not in k:
            continue
        forms = {"base": b, "s": L.third_s(b), "ing": L.ing_form(b), "v2": L.v2_of(b), "v3": L.v3_of(b)}
        ok_alt = set(L.ing_forms(b)) | set(L.past_forms(b)) | {L.EXTRA_V3.get(b, ""), L.IRREG.get(b, ("", ""))[1], L.IRREG.get(b, ("", ""))[0]} - {""}     # spellings / forms that are both right (travelling, traveling; got, gotten; learnt, learned)
        for kind, f in forms.items():
            if f != w and not (f in ok_alt and w in ok_alt and F.kinds(f) & F.kinds(w)):
                add(f"form:{w}>{f}", ws[:i] + [f.capitalize() if ws[i][:1].isupper() else f] + ws[i + 1:])
    return out[:limit]
