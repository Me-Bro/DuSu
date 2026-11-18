"""Grammar Lab - the explanation of a verdict, in Hindi and English (pure: fixed text, no model).

Every sentence here is a template filled with the learner's own words and the target's; nothing is generated.  `build(result, unit, trap)` returns BOTH languages so the card can flip
between them without a request:

    {"hi": {"headline", "rules": [..], "changes": [{"said", "fix"}], "formula", "marker", "gist", "trap"}, "en": {...}}

Hindi rules (CLAUDE.md section 23): Devanagari for the Hindi words, Latin for the grammar terms; "tum", never "aap" / "tu"; no second-person verb ending that guesses the learner's gender
(imperatives and "तुमने ... बनाया है" only).  `REVIEWED` in catalog.py is False until a native reader has read these.
"""

from __future__ import annotations

from . import catalog, forms as F

KIND_DESC = {
    "base": {"hi": "1st form (V1)", "en": "base form (V1)"},
    "s": {"hi": "V1 + s/es", "en": "V1 + s/es"},
    "ing": {"hi": "V1 + ing", "en": "V1 + ing"},
    "v2": {"hi": "2nd form (V2)", "en": "past form (V2)"},
    "v3": {"hi": "3rd form (V3)", "en": "past participle (V3)"},
}

# why a verb form is needed at a place (read off the word in front of it) -> (hi, en)
WHY = {
    "ing_after_be": ("am / is / are / was / were के बाद verb में -ing लगता है।", "After am / is / are / was / were the verb takes -ing."),
    "ing_after_been": ("been के बाद verb में -ing लगता है।", "After been the verb takes -ing."),
    "v3_after_have": ("has / have / had के बाद verb की 3rd form (V3) आती है, 2nd form (V2) नहीं।", "After has / have / had the verb is in V3, not V2."),
    "v1_after_aux": ("do / does / did / will / to के बाद verb की 1st form (V1) आती है: बिना -s, -ing या -ed के।", "After do / does / did / will / to the verb stays in V1: no -s, -ing or -ed."),
    "no_s_plural": ("I / you / we / they और बहुवचन subject के साथ verb में -s नहीं लगता।", "With I / you / we / they and plural subjects the verb takes no -s."),
    "s_third": ("he / she / it (एकवचन) के साथ Present Simple में verb में -s / -es लगता है।", "With he / she / it the Present Simple verb takes -s / -es."),
    "v2_past": ("बीते समय के लिए verb की 2nd form (V2) चाहिए।", "For the past the verb needs its past form (V2)."),
}
AGREE = {
    "be_pres": ("I के साथ am, he / she / it (एकवचन) के साथ is, we / you / they (बहुवचन) के साथ are।", "am with I, is with he / she / it (singular), are with we / you / they (plural)."),
    "be_past": ("I / he / she / it के साथ was, we / you / they के साथ were।", "was with I / he / she / it, were with we / you / they."),
    "be_mix": ("am / is / are = Present, was / were = Past: वाक्य का समय देखो।", "am / is / are = Present, was / were = Past: look at the time of the sentence."),
    "have_pres": ("he / she / it के साथ has, I / you / we / they के साथ have।", "has with he / she / it, have with I / you / we / they."),
    "have_mix": ("has / have = Present Perfect, had = Past Perfect।", "has / have = Present Perfect, had = Past Perfect."),
    "do_pres": ("he / she / it के साथ does, बाकी सब के साथ do।", "does with he / she / it, do with everyone else."),
    "do_mix": ("do / does = Present, did = Past।", "do / does = Present, did = Past."),
}
MISSING_AUX = {
    "do": ("Negative और question में do / does / did लगता है।", "Negatives and questions use do / does / did."),
    "does": ("Negative और question में do / does / did लगता है।", "Negatives and questions use do / does / did."),
    "did": ("Past के negative और question में did लगता है।", "Past negatives and questions use did."),
    "will": ("Future के लिए will लगता है।", "The future uses will."),
    "been": ("Perfect Continuous में have / has / had के बाद been आता है: have been + V1 + ing।", "A Perfect Continuous has been after have / has / had: have been + V1 + ing."),
    "be": ("Future Continuous में will be + V1 + ing आता है।", "A Future Continuous is will be + V1 + ing."),
    "have": ("Perfect में has / have / had ज़रूरी है।", "A perfect tense needs has / have / had."),
    "has": ("Perfect में has / have / had ज़रूरी है।", "A perfect tense needs has / have / had."),
    "had": ("Past Perfect में had ज़रूरी है।", "The Past Perfect needs had."),
    "is": ("-ing वाले tense में am / is / are ज़रूरी है।", "An -ing tense needs am / is / are."),
    "am": ("-ing वाले tense में am / is / are ज़रूरी है।", "An -ing tense needs am / is / are."),
    "are": ("-ing वाले tense में am / is / are ज़रूरी है।", "An -ing tense needs am / is / are."),
    "was": ("Past Continuous में was / were ज़रूरी है।", "A Past Continuous needs was / were."),
    "were": ("Past Continuous में was / were ज़रूरी है।", "A Past Continuous needs was / were."),
}
HEAD = {
    "tense": ("यहाँ दूसरा tense चाहिए।", "A different tense is needed here."),
    "vf": ("Verb का form ठीक करो।", "Fix the verb form."),
    "be": ("am / is / are (या was / were) ठीक करो।", "Fix am / is / are (or was / were)."),
    "have": ("has / have / had ठीक करो।", "Fix has / have / had."),
    "do": ("do / does / did ठीक करो।", "Fix do / does / did."),
    "will": ("will / shall ठीक करो।", "Fix will / shall."),
    "aux": ("Helping verb ठीक करो।", "Fix the helping verb."),
    "missing_aux": ("एक helping verb छूट गया है।", "A helping verb is missing."),
    "extra_aux": ("एक helping verb ज़्यादा है।", "There is one helping verb too many."),
    "overreg": ("यह irregular verb है।", "This is an irregular verb."),
    "missing_not": ("यह वाक्य negative है।", "This sentence is negative."),
    "extra_not": ("यह वाक्य negative नहीं है।", "This sentence is not negative."),
    "qform": ("वाक्य का रूप ठीक करो।", "Fix the sentence form."),
    "order_q": ("Question में शब्दों का क्रम ठीक करो।", "Fix the word order of the question."),
    "aux_place": ("Helping verb की जगह ठीक करो।", "Move the helping verb."),
}
UNSURE = ("तुम्हारा वाक्य हमारे जवाब से अलग है, पर tense या verb form की कोई ग़लती नहीं मिली। हमारा जवाब देखकर compare करो।",
          "Your sentence is different from ours, but we found no tense or verb-form mistake. Compare it with our answer.")
EMPTY = ("कुछ लिखा या बोला नहीं गया। फिर से try करो।", "Nothing was written or said. Try again.")
LANG = ("English में जवाब दो: यह Hindi में है।", "Answer in English: this one is in Hindi.")


def _agree(code: str) -> tuple:
    fam, rest = code.split(":", 1)
    u, t = rest.split(">", 1)
    if fam == "be":
        if u in F.BE_PRES and t in F.BE_PRES:
            return AGREE["be_pres"]
        if u in F.BE_PAST and t in F.BE_PAST:
            return AGREE["be_past"]
        return AGREE["be_mix"]
    if fam == "have":
        return AGREE["have_pres"] if u in ("has", "have") and t in ("has", "have") else AGREE["have_mix"]
    if fam == "do":
        return AGREE["do_pres"] if u in ("do", "does") and t in ("do", "does") else AGREE["do_mix"]
    return (f"यहाँ {t} चाहिए, {u} नहीं।", f"Here {t} is needed, not {u}.")


def _rule(code: str, edit: dict, unit: str) -> tuple:
    """(hi, en) - the rule behind one code (without the learner's words; those go in `changes`)."""
    fam = code.split(":", 1)[0]
    if fam == "vf":
        why = edit.get("why") or "generic"
        if why in WHY:
            return WHY[why]
        tk = code.split(">", 1)[1]
        return (f"यहाँ verb का {KIND_DESC[tk]['hi']} चाहिए।", f"The verb needs its {KIND_DESC[tk]['en']} here.")
    if fam in ("be", "have", "do"):
        return _agree(code)
    if fam == "will":
        return ("will इस्तेमाल करो: Future के लिए will + V1।", "Use will: the future is will + V1.")
    if fam == "aux":
        u, t = code.split(":", 1)[1].split(">", 1)
        return (f"यहाँ {t} चाहिए, {u} नहीं।", f"Here {t} is needed, not {u}.")
    if fam == "missing_aux":
        x = code.split(":", 1)[1]
        return MISSING_AUX.get(x, (f"यहाँ {x} चाहिए।", f"{x} is needed here."))
    if fam == "aux_place":
        x = code.split(":", 1)[1]
        return (f"{x} मौजूद है, पर सही जगह पर नहीं: Question में helping verb subject से पहले आता है, सीधे वाक्य में subject के बाद।",
                f"{x} is there, but in the wrong place: in a question the helping verb comes before the subject, in a statement after it.")
    if fam == "extra_aux":
        x = code.split(":", 1)[1]
        if x in ("do", "does", "did"):
            return ("सीधे (affirmative) वाक्य में do / does / did नहीं लगता।", "A plain statement does not use do / does / did.")
        return (f"यहाँ {x} की ज़रूरत नहीं है।", f"{x} is not needed here.")
    if fam == "overreg":
        u, t = code.split(":", 1)[1].split(">", 1)
        return (f"{t} irregular verb है: उसका form याद करना पड़ता है ({u} जैसा form नहीं बनता)।", f"{t} is an irregular verb: its form has to be learned (there is no {u}).")
    if fam == "missing_not":
        return ("इस वाक्य में 'नहीं' का मतलब है, इसलिए not लगाओ।", "The Hindi says नहीं, so the English needs not.")
    if fam == "extra_not":
        return ("Hindi वाक्य negative नहीं है, इसलिए not हटाओ।", "The Hindi is not negative, so remove not.")
    if fam == "qform":
        if code == "qform:q":
            return ("यह question है: helping verb (Do / Does / Is / Have / Will ...) subject से पहले आता है।", "This is a question: the helping verb (Do / Does / Is / Have / Will ...) comes before the subject.")
        return ("यह सीधा वाक्य है, question नहीं।", "This is a statement, not a question.")
    if fam == "order_q":
        return ("Question में helping verb subject से पहले आता है।", "In a question the helping verb comes before the subject.")
    if fam == "tense":
        l, t = code.split(":", 1)[1].split(">", 1)
        nl, nt = catalog.UNIT_META[l]["name"]["en"], catalog.UNIT_META[t]["name"]["en"]
        return (f"तुमने {nl} बनाया है, पर इस वाक्य में {nt} चाहिए।", f"You built a {nl}, but this sentence needs the {nt}.")
    return ("", "")


def build(res: dict, unit: str, trap: str = "") -> dict:
    """Both languages' explanation of one `checker.check` result."""
    verdict = res.get("verdict", "")
    target_unit = unit
    for c in res.get("codes", []):
        if c.startswith("tense:"):
            target_unit = c.split(">", 1)[1]
            break
    meta = catalog.UNIT_META.get(target_unit) or catalog.UNIT_META.get(unit) or {}
    out: dict = {}
    tgt_tokens = F.norm_tokens(res.get("target", "")) if res.get("target") else []
    form_key = "q" if F.is_question(tgt_tokens) else ("neg" if F.has_negation(tgt_tokens) else "aff")
    for lg, k in (("hi", 0), ("en", 1)):
        d: dict = {"headline": "", "rules": [], "changes": [], "formula": "", "marker": "", "gist": "", "trap": ""}
        if verdict == "empty":
            d["headline"] = EMPTY[k]
        elif verdict == "lang":
            d["headline"] = LANG[k]
        elif verdict == "unsure":
            d["headline"] = UNSURE[k]
            d["changes"] = [{"said": e["said"], "fix": e["fix"]} for e in res.get("edits", []) if e.get("said") or e.get("fix")][:4]
        elif verdict == "wrong":
            codes = res.get("codes", [])
            edits = res.get("edits", [])
            d["headline"] = HEAD.get(codes[0].split(":", 1)[0], HEAD["vf"])[k] if codes else ""
            seen = set()
            for code, e in zip(codes, edits):
                r = _rule(code, e, unit)[k]
                if r and r not in seen and len(d["rules"]) < 3:
                    seen.add(r)
                    d["rules"].append(r)
            d["changes"] = [{"said": e["said"], "fix": e["fix"]} for e in edits if (e.get("said") or e.get("fix")) and not e["code"].startswith(("tense:", "qform", "order_q"))][:4]
            if meta:
                d["formula"] = meta["formula"][form_key]
                d["marker"] = meta["marker"][lg]
                d["gist"] = meta["gist"][lg]
            if trap and trap in catalog.TRAPS:
                d["trap"] = catalog.TRAPS[trap][lg]
        out[lg] = d
    return out


def sample_codes() -> list:
    """One example of every code family the checker can produce - the test walks them to prove none is left without a Hindi and an English text."""
    return ["tense:present_simple>present_continuous", "vf:base>s", "vf:s>base", "vf:base>ing", "vf:ing>base", "vf:v2>v3", "vf:v3>v2", "vf:base>v2", "vf:v2>base", "vf:base>v3", "vf:s>ing", "be:is>are", "be:was>were",
            "be:is>was", "have:has>have", "have:has>had", "do:does>do", "do:do>did", "will:shall>will", "aux:was>did", "missing_aux:do", "missing_aux:been", "missing_aux:will", "missing_aux:is",
            "missing_aux:had", "extra_aux:did", "extra_aux:will", "aux_place:will", "overreg:goed>went", "missing_not", "extra_not", "qform:q", "qform:s", "order_q"]


def rule_text(code: str, unit: str = "") -> dict:
    """The rule behind one error code alone, in both languages ({"hi", "en"}) - the Lab's "what to practise next" line."""
    hi, en = _rule(code, {}, unit)
    return {"hi": hi, "en": en}


def static_help(unit: str, trap: str, target: str) -> dict:
    """The teaching lines that need no checker result (the learner asked to see the answer): the formula of the TARGET's shape, the Hindi ending, what the tense is for, the item's trap."""
    meta = catalog.UNIT_META.get(unit) or {}
    ts = F.norm_tokens(target or "")
    key = "q" if F.is_question(ts) else ("neg" if F.has_negation(ts) else "aff")
    out = {}
    for lg in ("hi", "en"):
        out[lg] = {"headline": "", "rules": [], "changes": [], "formula": meta["formula"][key] if meta else "", "marker": meta["marker"][lg] if meta else "",
                   "gist": meta["gist"][lg] if meta else "", "trap": catalog.TRAPS[trap][lg] if trap in catalog.TRAPS else ""}
    return out
