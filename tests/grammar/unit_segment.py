"""Grammar Coach - segmenter, gates and flow metrics (pure; no model, no network, no database).

Run:  cd /home/vibhanshu/Desktop/DuSu && PYTHONPATH=backend python3 tests/grammar/unit_segment.py
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _h import check, section, main                      # noqa: E402

from app import practice                                  # noqa: E402
from app.grammar import segment as SG                     # noqa: E402
from app.grammar import gating as G                       # noqa: E402
from app.grammar import flow as FL                        # noqa: E402
from app.grammar import lexicon_lang as LX                # noqa: E402
from app.grammar.text import clean_input, keys as tkeys, tokenize   # noqa: E402
from app.grammar.types import Hints, Sent, Gate           # noqa: E402

seg = SG.segment


def texts(s, **kw):
    return [x.text for x in seg(s, **kw)]


def words(n, start=0):
    base = ("market people yesterday office family really building project simple coffee evening problem teacher station village "
            "morning garden doctor travel pocket window ticket bottle answer button circle hunger jungle").split()
    return [base[(start + i) % len(base)] for i in range(n)]


def mk(text, *, conf=None, source="chrome"):
    """A Sent built the way the segmenter would (core words), without going through segment()."""
    ks = [t.key for t in tokenize(text)]
    a, b = SG.core_range(ks, 0, len(ks))
    return Sent(sid="0:0", turn=0, text=text, start=0, end=len(text), n_words=b - a, punct=text.rstrip()[-1:] in ".!?", conf=conf, source=source)


def gate(text, **kw):
    return G.sentence_gate(mk(text, **{k: v for k, v in kw.items() if k in ("conf", "source")}),
                           **{k: v for k, v in kw.items() if k == "name"})


# ============================================================================================= lexicon sanity
section("lexicon")
check("HINGLISH_STOP has no English stop word", not (LX.HINGLISH_STOP & LX.ENGLISH_STOP), LX.HINGLISH_STOP & LX.ENGLISH_STOP)
check("HINGLISH_STOP excludes the English-looking ones", not ({"to", "par", "main", "hi", "ho", "kar", "bas", "do", "me", "the", "sun", "log", "fir", "pe"}
                                                              & LX.HINGLISH_STOP))
check("HINGLISH_STOP is big enough and lowercase", len(LX.HINGLISH_STOP) >= 110 and all(w == w.lower() and w.isalpha() for w in LX.HINGLISH_STOP))
check("LOANWORDS has the named examples", {"chai", "dhaba", "lakh", "crore", "ji", "didi", "diwali", "tiffin", "auto"} <= LX.LOANWORDS and len(LX.LOANWORDS) >= 200)
check("connector categories", set(LX.CONNECTORS) == {"add", "contrast", "cause", "example", "sequence", "condition"})

# ============================================================================================= segmentation: terminals
section("segmentation - terminals and vetoes")
check("two plain sentences", texts("I like tea. She likes coffee.") == ["I like tea.", "She likes coffee."])
check("question and exclamation", texts("Where are you going? I am going home! Really?") == ["Where are you going?", "I am going home!", "Really?"])
check("a quote after the stop opens a sentence", len(texts('He left. "Why did he go?" she asked.')) == 2)
check("lowercase after a stop is not a boundary", texts("I like tea. she likes coffee") == ["I like tea. she likes coffee"])
check("digit after a stop is a boundary", len(texts("I was born in 1990. 2005 was a big year.")) == 2)
check("Dr. Rao", texts("Dr. Rao is my uncle. He lives in Pune.") == ["Dr. Rao is my uncle.", "He lives in Pune."])
check("Mr. / Mrs. / Prof.", len(texts("Mr. Sharma and Mrs. Gupta met Prof. Iyer. They talked.")) == 2)
check("Rs. 500", texts("It cost Rs. 500 only. I paid it.") == ["It cost Rs. 500 only.", "I paid it."])
check("6.30 a.m. is not a boundary", texts("I wake up at 6.30 a.m. Then I walk.") == ["I wake up at 6.30 a.m. Then I walk."])
check("decimals", texts("I scored 8.5 in the test. It was good.") == ["I scored 8.5 in the test.", "It was good."])
check("e.g. / i.e.", len(texts("I like fruits e.g. Mango and apple. They are sweet.")) == 2)
check("initials J. K. Rowling", texts("I read J. K. Rowling every day. She is great.") == ["I read J. K. Rowling every day.", "She is great."])
check("a capital I at the end is a sentence end", texts("Rahul went and so did I. Then we ate.") == ["Rahul went and so did I.", "Then we ate."])
check("list numbering '1. First'", len(texts("My plan is 1. First I study. Then I rest.")) == 2)   # '1.' vetoed, 'study.' splits
check("No. 5 abbreviation vs 'no.' sentence end", len(texts("I live in house No. 5 near the park.")) == 1 and len(texts("I said no. Then he left.")) == 2)
check("URL is not split", len(texts("Visit www.dusu.app. It is free.")) == 2 and len(texts("open http://a.b/c. Then go.")) == 2)
check("'...' after <4 words is a hesitation", texts("Well... I think so. Okay.") == ["Well... I think so.", "Okay."])
check("'...' after a long stretch is a boundary", len(texts("I went to the market yesterday evening... Then I came home.")) == 2)
check("trailing closers stay with the sentence", texts('She said "I am tired." Then she slept.') == ['She said "I am tired."', "Then she slept."])
check("empty / None / whitespace / punctuation only", seg("") == [] and seg(None) == [] and seg("   ") == [] and seg("...?!") == [])
check("devanagari danda splits", len(texts("मेरा नाम राहुल है। मैं पुणे में रहता हूँ।")) == 2)
s = seg("Hello there. How are you")
check("offsets are exact slices of the cleaned text", all(clean_input("Hello there. How are you")[x.start:x.end] == x.text for x in s))
check("sid / turn / source / conf pass through", [(x.sid, x.turn, x.source, x.conf) for x in seg("One two three. Four five six.", turn=3, source="whisper", conf=0.9)]
      == [("3:0", 3, "whisper", 0.9), ("3:1", 3, "whisper", 0.9)])
check("bad source falls back to chrome; bad conf to None", (seg("a b c d", source="x", conf="zz")[0].source, seg("a b c d", conf="zz")[0].conf) == ("chrome", None))

# ============================================================================================= core words
section("core words")
x = seg("um uh so I went home")[0]
check("3 leading discourse tokens not counted", x.n_words == 3 and x.text.startswith("um"), x.n_words)
check("only 3 leading are stripped", seg("so um uh okay I went home")[0].n_words == 4)
check("'you know' / 'i mean' lead phrases", seg("you know I like it")[0].n_words == 3 and seg("i mean it was good")[0].n_words == 3)
check("trailing you know / right / okay", seg("I like it you know")[0].n_words == 3 and seg("I like it right")[0].n_words == 3 and seg("I like it okay")[0].n_words == 3)
check("'um uh' has zero core words", seg("um uh")[0].n_words == 0)
check("'and then I went' strips and, then", seg("and then I went home")[0].n_words == 3)

# ============================================================================================= unpunctuated + long chunks
section("long unpunctuated chunks")
t22 = " ".join(words(22))
check("22 words, no terminals = ONE sentence (src whole)", len(seg(t22)) == 1 and seg(t22)[0].src == "whole" and not seg(t22)[0].punct)
t23 = " ".join(words(23))
check("23 words with nothing to cut at stays whole (no cut possible below 25)", len(seg(t23)) == 1)
t40 = " ".join(words(40))
r = seg(t40)
check("40 plain words: a forced cut at 25, flagged", r and r[0].forced and r[0].src == "forced" and r[0].n_words == 25 and r[1].forced, [(x.n_words, x.src, x.forced) for x in r])
check("forced pieces never punct", not any(x.punct for x in r))
ctext = " ".join(words(14)) + " so " + " ".join(words(14, 3))
r = seg(ctext)
check("cut at the connector 'so'", len(r) == 2 and r[1].text.startswith("so ") and r[0].src == "connector", [x.text for x in r])
check("connector gives no forced flag", not any(x.forced for x in r))
ctext = " ".join(words(12)) + " but I " + " ".join(words(15, 5))
check("but + subject pronoun after >= 8 words is a cut", len(seg(ctext)) == 2 and seg(ctext)[1].text.startswith("but I"))
ctext = " ".join(words(12)) + " but " + " ".join(words(15, 5))
check("but + a non-pronoun is not a cut", all(not x.src == "connector" for x in seg(ctext)))
ctext = " ".join(words(5)) + " so " + " ".join(words(25, 4))
r = seg(ctext)
check("a connector before 6 words is not used", not r[0].text.endswith("market people yesterday office family") or len(r) >= 2)
ctext = " ".join(words(11)) + "; " + " ".join(words(14, 6))
r = seg(ctext)
check("';' is a P1 cut", len(r) == 2 and r[0].text.endswith(";") and r[0].src == "pause", [x.text[-12:] for x in r])
ctext = " ".join(words(11)) + "... " + " ".join(words(14, 6))
check("'...' mid-chunk is a P1 cut", len(seg(ctext)) == 2 and seg(ctext)[0].text.endswith("..."))
# P1 beats P2 even when the connector is nearer the ideal 14
w = words(40)
txt = " ".join(w[:10]) + " ; " + " ".join(w[10:15]) + " so " + " ".join(w[15:])
r = seg(txt)
check("pause/semicolon candidate wins over a nearer connector", r[0].src == "pause", [(x.src, x.n_words) for x in r])
# Whisper hints: pause >= 0.7s
w = words(30)
txt = " ".join(w)
ks = tkeys(txt)
h = Hints(pause_after={11: 0.9}, seg_end=frozenset())
r = seg(txt, hints=h)
check("a pause >= 0.7s is a P1 cut", len(r) == 2 and r[0].n_words == 12 and r[0].src == "pause", [(x.n_words, x.src) for x in r])
h2 = Hints(pause_after={11: 0.5}, seg_end=frozenset())
check("a pause < 0.7s is ignored", all(x.src != "pause" for x in seg(txt, hints=h2)))
h3 = Hints(pause_after={}, seg_end=frozenset({13}))
r = seg(txt, hints=h3)
check("a Whisper segment end is a P1 cut", r[0].n_words == 14 and r[0].src == "pause", [(x.n_words, x.src) for x in r])
h4 = Hints(pause_after={9: 1.2, 15: 1.0}, seg_end=frozenset())
r = seg(txt, hints=h4)
check("nearest candidate to 14 words is chosen", r[0].n_words == 16, [x.n_words for x in r])
# 'and then' chain
chain = "I woke up and then I brushed my teeth and then I had tea and then I left"
check("'and then' chain (< 22 words) is NOT split", len(seg(chain)) == 1, len(chain.split()))
chain2 = chain + " and then I went out and then I came back and then I slept and then I woke and then I ate and then I left home and then I rested"
r = seg(chain2)
check("a longer chain splits BEFORE 'and' (not between 'and' and 'then')", len(r) >= 2 and not r[0].text.endswith(" and") and r[1].text.startswith("and then"), [x.text[-14:] for x in r])
# tiny pieces merge
txt = " ".join(words(24)) + " so " + " ".join(words(2, 1))
r = seg(txt)
check("a tiny tail piece (< 5 words) merges back", len(r) == 1 or all(x.n_words >= 5 for x in r), [x.n_words for x in r])
# punctuated long sentence is also cut
txt = " ".join(words(30)) + "."
r = seg(txt)
check("a long PUNCTUATED sentence is cut, last piece keeps punct", len(r) >= 2 and r[-1].punct and not r[0].punct)
# model cuts
txt = " ".join(words(40))
starts = [" ".join(words(40)[18:21])]
cuts = SG.apply_starts(txt, starts)
r = seg(txt, cuts=cuts)
check("model cuts used only when no candidate exists", len(r) >= 2 and r[0].src == "model" and r[0].n_words == 18, [(x.n_words, x.src) for x in r])

# ============================================================================================= apply_starts / align_hints
section("apply_starts / align_hints")
base = "I went to the market and then I bought some fruit because it was cheap but the shop was far so I took an auto"
a = SG.apply_starts(base, ["and then I", "but the shop", "so I took"])
check("apply_starts: offsets of the anchors", [base[o:o + 6] for o in a] == ["and th", "but th", "so I t"], a)
check("apply_starts: misses ignored, case-insensitive", SG.apply_starts(base, ["AND THEN i", "no such words", "x"]) == [base.index("and then")])
check("apply_starts: strictly increasing, never 0", SG.apply_starts(base, ["I went to", "and then I"]) == [base.index("and then")])
check("apply_starts: garbage in", SG.apply_starts(base, None) == [] and SG.apply_starts("", ["a b"]) == [] and SG.apply_starts(base, [1, None, {}]) == [])
words_rows = [["I", 0.0, 0.2], ["went", 0.25, 0.5], ["to", 0.55, 0.6], ["the", 0.62, 0.7], ["market", 0.75, 1.2], ["and", 2.3, 2.4], ["bought", 2.45, 2.9],
              ["fruit.", 2.95, 3.4]]
clean = "I went to the market and bought fruit."
hh = SG.align_hints(clean, words_rows, [[0.0, 1.3, -0.2, 0.01], [2.2, 3.5, -0.2, 0.01]])
check("align_hints: aligned, pause after 'market' is 1.1s", hh is not None and abs(hh.pause_after.get(4, 0) - 1.1) < 1e-6, hh)
check("align_hints: segment end -> token index", hh is not None and 4 in hh.seg_end, hh)
check("align_hints: small gaps are not kept as pauses", hh is not None and 0 not in hh.pause_after)
bad = [["alpha", 0, 1], ["beta", 1, 2], ["gamma", 2, 3], ["delta", 3, 4], ["epsilon", 4, 5]]
check("align_hints: unrelated words -> None", SG.align_hints(clean, bad, None) is None)
check("align_hints: empty / junk -> None", SG.align_hints(clean, [], None) is None and SG.align_hints(clean, "x", None) is None and SG.align_hints("", words_rows) is None)
long_clean = " ".join(words(20))
long_rows = [[wd, i * 0.3, i * 0.3 + 0.2] for i, wd in enumerate(words(20))]
check("align_hints: one dropped word still aligns (>= 0.9)", SG.align_hints(long_clean, long_rows[:7] + long_rows[8:]) is not None)
check("align_hints: one extra word still aligns", SG.align_hints(long_clean, long_rows[:7] + [["uh", 2.0, 2.1]] + long_rows[7:]) is not None)
check("align_hints: 50% mismatch -> None", SG.align_hints("one two three four five six seven eight", [["one", 0, 1], ["x", 1, 2], ["three", 2, 3], ["y", 3, 4], ["five", 4, 5],
                                                                                                 ["z", 5, 6], ["seven", 6, 7], ["w", 7, 8]]) is None)
check("align_hints: apostrophes and punctuation in Whisper words", SG.align_hints("I don't know.", [["I", 0, 0.2], [" don't", 0.3, 0.5], ["know.", 0.6, 0.9]]) is not None)
# hints end to end: a Whisper-aligned pause drives a cut
w30 = words(30)
tclean = " ".join(w30)
rows = []
t = 0.0
for i, wd in enumerate(w30):
    rows.append([wd, t, t + 0.3])
    t += 0.35 + (1.0 if i == 12 else 0.0)
hh = SG.align_hints(tclean, rows)
r = seg(tclean, hints=hh, source="whisper")
check("align_hints -> segment: cut right after the 1.0s pause", r[0].n_words == 13 and r[0].src == "pause", [(x.n_words, x.src) for x in r])

# ============================================================================================= invariant
section("re-join invariant (seeded property test, 3,000 inputs)")
rng = random.Random(20261016)
PIECES = ["the", "I", "went", "to", "market", "Dr.", "Mr.", "e.g.", "i.e.", "a.m.", "p.m.", "Rs.", "No.", "J.", "K.", "etc.", "3.5", "6.30", "1,000",
          "don't", "can't", "it's", "O'Brien", "um", "uh", "so", "and", "then", "but", "However", "Anyway", "you", "know", "i", "mean", "well",
          ".", "..", "...", "?", "!", "?!", ";", ",", '"', "'", "(", ")", "[", "]", "-", "’", "“", "”", "…",
          "मेरा", "नाम", "है", "।", "हूँ", "कि", "123", "4.", "http://x.y/z", "www.a.com", "ok.", "Right.", "Yes.", "Hello,", "world!", "\n", "\t", "  ",
          "[Music]", "(laughs)", "\x00", "ß", "İ", "ǅ", "é", "Ünïcode", "日本", "😀", "a", "b", "1.", "2."]
bad_inv = bad_exc = bad_primary = 0
total_sents = 0
for it in range(3000):
    n = rng.choice([0, 1, 2, 3, 5, 10, 25, 40, 80])
    parts = [rng.choice(PIECES) for _ in range(n)]
    sep = rng.choice([" ", " ", " ", "", "  "])
    s = sep.join(parts) if rng.random() < 0.8 else "".join(rng.choice(PIECES + [" "]) for _ in range(n))
    try:
        out = seg(s, turn=it % 7, source=rng.choice(["chrome", "whisper", "gemini"]))
        cl = clean_input(s)
        if not SG.invariant_ok(cl, out):
            bad_inv += 1
        total_sents += len(out)
        # the PRIMARY path (not the single-chunk fallback) must satisfy the invariant too
        ts_, te_, ks_ = SG._scan(cl)
        if ks_:
            prim = SG._build(cl, ts_, te_, ks_, 0, "chrome", None, None, set())
            if not SG.invariant_ok(cl, prim):
                bad_primary += 1
    except Exception as e:                                  # noqa: BLE001
        bad_exc += 1
        print("   exception:", repr(e), repr(s)[:80])
check("never raises on 3,000 random inputs", bad_exc == 0, bad_exc)
check("invariant_ok on every output", bad_inv == 0, bad_inv)
check("invariant holds on the PRIMARY path (no fallback hiding a bug)", bad_primary == 0, bad_primary)
check("the fuzz actually produced sentences", total_sents > 3000, total_sents)
check("invariant_ok detects a violation (reordered / lost text)",
      not SG.invariant_ok("one two three four", [Sent("0:0", 0, "one two", 0, 7, 2, False), Sent("0:1", 0, "four", 14, 18, 1, False)]) and
      not SG.invariant_ok("one two", [Sent("0:0", 0, "one", 0, 3, 1, False), Sent("0:1", 0, "one", 0, 3, 1, False)]) and
      not SG.invariant_ok("one two", [Sent("0:0", 0, "xxx two", 0, 7, 2, False)]) and
      SG.invariant_ok("one two", [Sent("0:0", 0, "one two", 0, 7, 2, False)]))
long_random = " ".join(rng.choice(["so", "and", "then", "I", "we", "went", "but", "market", ";", "...", "also", "now"]) for _ in range(5000))
check("a 5,000-word unpunctuated turn is covered by the invariant", SG.invariant_ok(clean_input(long_random), seg(long_random)))
check("limit slices the input first", sum(len(x.text) for x in seg("word " * 10000, limit=500)) <= 500)

# ============================================================================================= session gate
section("session_gate")
table = [
    (("conversation", None, "en"), True), (("conversation", None, "hi"), False), (("interview", None, "en"), True), (("interview", None, "hi"), False),
    (("practice", "en", "en"), True), (("practice", "hi", "en"), False), (("practice", "hinglish", "en"), False), (("practice", "fr", "en"), False),
    (("practice", None, "en"), False), (("practice", "EN", "hi"), True), (("practice", " English ", "en"), True),
    (("resume_interview", None, "en"), True), (("resume_interview", None, "hi"), True), (("job_interview", "hi", "hi"), True),
    (("daily", None, "en"), False), (("learning", None, "en"), False), (("home", None, "en"), False), (("mystery", None, "en"), False), ((None, None, "en"), False),
    (("Conversation", None, "EN"), True),
]
for args, want in table:
    g = G.session_gate(*args)
    check(f"session_gate{args} -> {want}", g.ok is want and (g.ok or g.reason in ("mode", "language")), g)
check("reasons: mode vs language", G.session_gate("daily").reason == "mode" and G.session_gate("practice", "hi").reason == "language"
      and G.session_gate("conversation", lang="hi").reason == "language")

# ============================================================================================= sentence gate
section("sentence_gate - too_short")
for t in ["um uh", "yes sir", "okay", "Thank you", "so um yes"]:
    check(f"too_short: {t!r}", gate(t) == Gate(False, "too_short"), gate(t))
for t in ["I like tea", "she goes to school", "we were very happy yesterday"]:
    check(f"not too_short: {t!r}", gate(t).reason != "too_short", gate(t))

section("sentence_gate - not_a_sentence")
for t in ["A B C D", "R A H U L S", "one two three four five", "9 8 7 6 5 4", "no no no no", "hello hello hello hello"]:
    check(f"not_a_sentence: {t!r}", gate(t) == Gate(False, "not_a_sentence"), gate(t))
for t in ["I am a student", "My number is nine eight seven and I live in Pune", "he said no no I cannot go"]:
    check(f"a sentence: {t!r}", gate(t).reason != "not_a_sentence", gate(t))

section("sentence_gate - unintelligible")
for t in ["thank you for watching bye bye", "thanks for watching bye bye", "the the the end the the the end"]:
    check(f"hallucination: {t!r}", gate(t, source="whisper") == Gate(False, "unintelligible"), gate(t, source="whisper"))
check("low recogniser confidence", gate("I went to the market yesterday", conf=0.3) == Gate(False, "unintelligible"))
check("confidence 0 / None means unknown", gate("I went to the market yesterday", conf=0).ok and gate("I went to the market yesterday", conf=None).ok)
check("confidence at 0.45 passes", gate("I went to the market yesterday", conf=0.45).ok)
check("one-letter token salad", gate("p q r market t u v w") == Gate(False, "unintelligible") or gate("p q r market t u v w").reason == "not_a_sentence")
check("40% one-letter tokens", gate("I went x to y the z market p").reason == "unintelligible", gate("I went x to y the z market p"))
for t in ["Mary bad cut ladder kitchen sir Monday garden", "tomato river chair window sky pocket silver ticket round", "cat jungle hunger bottle simple coffee evening village mango"]:
    check(f"Hindi heard as English salad: {t!r}", gate(t) == Gate(False, "unintelligible"), gate(t))
for t in ["I went to the market and I bought some fruit", "She is the teacher of my school", "we were not able to reach on time"]:
    check(f"normal English passes: {t!r}", gate(t).ok, gate(t))
check("short content-heavy list under 6 tokens is not salad", gate("software engineer data science").ok)
try:
    from app.resume_interview import rules as RIR
    cases = ["Thank you.", "Thanks for watching", "I went to the market", "the end the end the end the end the end", "yes yes yes yes yes yes yes", "", "okay so yeah",
             "I like my job and I want to grow", "bye bye bye bye bye bye", "one two three four five six seven"]
    check("hallucination parity on 10 texts", all(G._hallucination(c) == RIR.is_hallucination(c) for c in cases), [c for c in cases if G._hallucination(c) != RIR.is_hallucination(c)])
except Exception as e:                                       # noqa: BLE001
    check("hallucination parity on 10 texts (module importable)", False, repr(e))

section("sentence_gate - not_english")
for t in ["मेरा नाम राहुल है और मैं पुणे में रहता हूँ", "mera naam Rahul hai aur main Pune mein rehta hoon", "aap kaise ho aaj kal bahut kaam hai", "mujhe nahi pata kya karna chahiye"]:
    check(f"not_english: {t!r}", gate(t) == Gate(False, "not_english"), gate(t))
check("Devanagari mixed in English >= 30% of letters", gate("I said नमस्ते दोस्तों कैसे हो आप सब") == Gate(False, "not_english"))
for t in ["I had chai and samosa at the dhaba yesterday", "My didi gave me five lakh rupees for Diwali", "we took an auto to the market near the ghat",
          "I want to tell you one thing yaar it was a good day", "she is a good person and she is my friend"]:
    check(f"English with loanwords / one Hindi word stays ok: {t!r}", gate(t).ok, gate(t))
check("one Hindi word in 6 tokens (0.17) passes", gate("I told him kal I will come").ok)
check("0.10 Hinglish share + few English stop words -> not_english", gate("tum Rahul Priya Amit Sneha Anita Kavita Divya Pooja Neha").reason in ("not_english", "unintelligible"))
check("the learner's own name is neutral", gate("I was talking with Kal about the market", name="Kal").ok and gate("Kal Kal I am coming kal", name="Kal").reason != "x")
check("not_english wins over the statistical 'unintelligible' for Devanagari", gate("राहुल कल पुणे जा रहा है").reason == "not_english")

section("sentence_gate - order (first rule wins)")
check("too_short before everything", gate("नमस्ते") == Gate(False, "too_short"))
check("not_a_sentence before not_english", gate("no no no no no") .reason == "not_a_sentence")

section("opaque_indices")
def op(t, **kw):
    return {tokenize(t)[i].raw for i in G.opaque_indices(tokenize(t), **kw)}
check("Devanagari tokens are opaque (the tokenizer splits a word at its matras)", {"न", "म"} <= op("my नाम is Rahul") and "my" not in op("my नाम is Rahul"))
check("Hinglish-list words are opaque", {"yaar", "nahi"} <= op("it is yaar nahi good"))
check("loanwords are opaque", op("I drank chai at the dhaba") == {"chai", "dhaba"})
check("the learner's name is opaque", "Meenakshi" in op("my friend Meenakshi came", name="Meenakshi Iyer") and "friend" not in op("my friend Meenakshi came", name="Meenakshi"))
check("capitalised mid-sentence tokens opaque only when cased", "Google" in op("I work at Google now", cased=True) and "Google" not in op("I work at Google now", cased=False))
check("sentence-initial and I-forms are not opaque", op("The man said I'm happy and I know", cased=True) == set())
check("acronyms are opaque when cased", "IELTS" in op("I took IELTS last year", cased=True) and "TCS" in op("TCS hired me", cased=True))
check("a run of 3+ spelled letters is opaque", op("my name is R A H U L ok") == {"R", "A", "H", "U", "L"}, op("my name is R A H U L ok"))
check("a lone 'a' or 'I' is not opaque", op("I have a dog") == set())
check("indexes, plain strings accepted", G.opaque_indices(["I", "ate", "chai"]) == {2})
check("is_cased: normal text yes, Title Case Everything no", G.is_cased(tokenize("I work at Google in Pune with Rahul")) and not G.is_cased(tokenize("My Name Is Rahul And I Live In Pune")))

section("lang_mix")
ne, ok_, ts = Gate(False, "not_english"), Gate(True, ""), Gate(False, "too_short")
check("3 of 6 not_english -> mix", G.lang_mix([ne, ok_, ne, ok_, ne, ok_]) is True)
check("2 of 6 -> no mix", G.lang_mix([ne, ok_, ne, ok_, ok_, ok_]) is False)
check("only the first 6 units count", G.lang_mix([ok_] * 6 + [ne] * 10) is False and G.lang_mix([ne] * 3 + [ok_] * 3 + [ne] * 20) is True)
check("empty -> False; too_short is not not_english", G.lang_mix([]) is False and G.lang_mix([ts, ts, ts, ne]) is False)
check("accepts reason strings", G.lang_mix(["not_english", "not_english", "ok"]) is True)

# ============================================================================================= flow
section("flow metrics")
def S(text, *, punct=True, forced=False, source="whisper"):
    s = mk(text, source=source)
    return Sent(s.sid, 0, s.text, 0, len(s.text), s.n_words, punct, "terminal", forced, None, source)

good = [S(t) for t in ["I work as a software engineer in Pune.", "My team builds payment tools for small shops.", "However, last year we changed our whole design.",
                       "For example, we moved the data to a new service.", "Because of that the pages became much faster.", "Then I spent some time on testing.",
                       "If a test failed, I would fix it first.", "After that, the customers were happier.", "I enjoy this work because I learn every day."]]
m = FL.flow_metrics(good, source="whisper")
check("< 8 sentences -> None", FL.flow_metrics(good[:7], source="whisper") is None and FL.flow_metrics([], source="chrome") is None and FL.flow_metrics(None, source="chrome") is None)
check("8 sentences -> dict with the fields", m is not None and {"avg_words", "share_long", "choppy_runs", "and_then_chains", "starter_top", "connector_variety", "fillers_per100",
                                                               "restarts", "approx", "punct_ok", "flags"} <= set(m))
check("avg words per sentence", m and 6 <= m["avg_words"] <= 11, m and m["avg_words"])
check("healthy text raises no flow flag except maybe none", m and m["flags"] == [], m and m["flags"])
check("connector variety counts categories (>= 3 good)", m and m["connector_variety"]["categories"] >= 3 and m["connector_variety"]["good"], m and m["connector_variety"])
check("whisper: approx False, punct_ok True", m and m["approx"] is False and m["punct_ok"] is True)

choppy = [S(t) for t in ["I go.", "I eat.", "I sleep.", "I work now.", "I like it.", "It is good.", "I am fine.", "He is nice.", "She is kind."]]
m = FL.flow_metrics(choppy, source="whisper")
check("choppy runs (>= 3 consecutive <= 5 words) found for whisper", m and m["choppy_runs"] >= 1 and "f.choppy" in m["flags"], m and (m["choppy_runs"], m["flags"]))
check("yes / no / okay are ignored inside a run", FL.flow_metrics([S("I go."), S("Okay."), S("I eat."), S("Yes."), S("I sleep.")] + [S("I work in a big office today and it is good for me, so I stay.")] * 3,
                                                                  source="whisper")["choppy_runs"] == 1)
mc = FL.flow_metrics([S(t.text, source="chrome") for t in choppy], source="chrome")
check("chrome: choppy / run-on are None and not flagged, approx True", mc and mc["choppy_runs"] is None and mc["share_long"] is None and mc["run_on"] is None
      and mc["choppy"] is None and mc["approx"] is True and "f.choppy" not in mc["flags"] and "f.run_on" not in mc["flags"], mc and (mc["choppy_runs"], mc["flags"]))
check("chrome keeps avg length, starters, and/then chains", mc and mc["avg_words"] < 6 and mc["starter_top"][0] == "i" and "f.starters" in mc["flags"])
unt = [S(t.text, punct=False, forced=True) for t in choppy]
check("our own cut sentences (not punct / forced) never count as choppy", FL.flow_metrics(unt, source="whisper")["choppy_runs"] == 0)
long_s = [S(" ".join(words(30)) + ".") for _ in range(8)]
ml = FL.flow_metrics(long_s, source="whisper")
check("run-on: share_long and avg > 25 flagged", ml["share_long"] == 1.0 and "f.run_on" in ml["flags"] and ml["run_on"] is True)
check("run-on is not computed for chrome", FL.flow_metrics([S(x.text, source="chrome") for x in long_s], source="chrome")["share_long"] is None)

chain = [S("I woke up and then I brushed my teeth and then I had tea and then I left.")] * 2 + good[:6]
mm = FL.flow_metrics(chain, source="whisper")
check("and-then chains (>= 3 'then' in one unit)", mm["and_then_chains"] == 2 and "f.connectors" in mm["flags"], (mm["and_then_chains"], mm["flags"]))

same = [S(t) for t in ["I went home.", "I ate food.", "I slept early.", "My friend called.", "We talked a lot.", "They laughed hard.", "She joined us.", "He left soon."]]
ms = FL.flow_metrics(same, source="whisper")
check("same starter on 3 consecutive sentences", ms["starter_repeat"] is True and "f.starters" in ms["flags"] and ms["starter_top"][0] == "i")
varied = [S(t) for t in ["The cat sat.", "A dog ran.", "My bird sang.", "Our fish swam.", "His horse jumped.", "Her cow ate.", "Some ants worked.", "That frog hopped."]]
check("varied starters: no flag", FL.flow_metrics(varied, source="whisper")["starter_repeat"] is False)
top40 = [S(t) for t in ["We went home.", "A dog ran.", "We ate food.", "My bird sang.", "We slept early.", "Our fish swam.", "We talked a lot.", "His horse jumped.", "Some ants worked.", "That frog hopped."]]
mt = FL.flow_metrics(top40, source="whisper")
check("top share >= 40% flags (not consecutive)", mt["starter_repeat"] is True and mt["starter_top"] == ("we", 0.4), mt["starter_top"])
check("leading 'so / and / then' do not hide the starter", FL.flow_metrics([S(t) for t in ["so I went.", "and I ate.", "then I slept.", "so I woke.", "and I read.", "then I wrote.", "so I ran.", "and I sat."]],
                                                                       source="whisper")["starter_top"][0] == "i")

filler = [S(t) for t in ["Um I think, you know, it is basically fine.", "Actually I like it, you know, a lot.", "I mean it is, um, good.", "So basically we went.",
                         "You know the plan is okay.", "Um then we left.", "Basically it works, um.", "I am actually happy, you know."]]
mf = FL.flow_metrics(filler, source="whisper")
check("fillers per 100 words measured for whisper", mf["fillers_per100"] is not None and mf["fillers_per100"] >= 4 and "f.fillers" in mf["flags"], mf["fillers_per100"])
check("fillers are None (not 0) for chrome and gemini", FL.flow_metrics(filler, source="chrome")["fillers_per100"] is None and FL.flow_metrics(filler, source="gemini")["fillers_per100"] is None)
check("fillers agree with practice.count_fillers", abs(mf["fillers_per100"] - round(100 * sum(d["n"] for d in practice.count_fillers(practice.norm(" ".join(s.text for s in filler)))) / len(practice.norm(" ".join(s.text for s in filler)).split()), 1)) < 1e-9)
rs = [S(t) for t in ["We are we are going home.", "I I think so.", "It is it is fine.", "They went they went out.", "We like it.", "He said it.", "She read it.", "You saw it."]]
mr = FL.flow_metrics(rs, source="whisper")
check("restarts counted; flagged for whisper", mr["restarts"] >= 3 and "f.restarts" in mr["flags"], (mr["restarts"], mr["flags"]))
check("restarts are approximate for chrome: counted, not flagged", FL.flow_metrics(rs, source="chrome")["restarts"] >= 3 and "f.restarts" not in FL.flow_metrics(rs, source="chrome")["flags"])
check("only known flow ids appear", all(f in FL.FLOW_IDS for f in mr["flags"] + mf["flags"] + ml["flags"] + mm["flags"]))
check("duration gives wpm", FL.flow_metrics(good, source="whisper", duration_sec=60)["wpm"] is not None and FL.flow_metrics(good, source="whisper")["wpm"] is None)
check("an explicit text= is used for fillers", FL.flow_metrics(good, source="whisper", text="um um um um um um um um um um okay " * 3)["fillers_per100"] >= 4)
check("bad source falls back to chrome behaviour", FL.flow_metrics(good, source="???")["approx"] is True)

# ============================================================================================= adversarial timing
section("adversarial timing (25 hostile shapes, each < 100 ms after the internal slice)")
BIG = 200000
shapes = {
    "200k spaces": " " * BIG,
    "a. x50000": "a." * 50000,
    "dots x100000": "." * 100000,
    "1. x50000": "1." * 50000,
    "digit run": "1" * BIG,
    "digits and dots": "1." * 20000 + "2" * 100000,
    "e.g. x100000": "e.g. " * 100000,
    "A. x100000": "A. " * 100000,
    "unbalanced quotes": '"' * 100000 + "a. B" * 5000,
    "unbalanced brackets": "([" * 100000,
    "closers only": ")]\"'" * 50000,
    "huge devanagari": "मेरा नाम राहुल है। " * 20000,
    "devanagari no stops": "नमस्ते " * 40000,
    "question marks": "?" * 100000,
    "?! pairs": "?! " * 60000,
    "ellipses": "... " * 60000,
    "ellipsis chars": "…" * 100000,
    "one long word": "a" * BIG,
    "apostrophes": "a'" * 100000,
    "apostrophe words": "don't " * 50000,
    "semicolons": "word; " * 40000,
    "mixed hostile": ("Dr. Mr. e.g. 1. 2.5 a.m. ... ?! \" ( [ so and then but " * 6000),
    "connectors only": "so then and but also now " * 20000,
    "tabs/newlines/ctrl": "a\t\n\x00\x1f " * 60000,
    "brackets cleaner": "[" * 100000 + "]" * 100000,
}
check("25 shapes defined", len(shapes) == 25, len(shapes))
worst = 0.0
for name, s in shapes.items():
    dt = 1e9
    for _ in range(3):                                      # best of 3: a scheduler hiccup is not an algorithmic problem
        t0 = time.perf_counter()
        out = seg(s)
        dt = min(dt, (time.perf_counter() - t0) * 1000)
    worst = max(worst, dt)
    # sentence_gate on the biggest sentence that segment produced (or on a 30k slice of the raw shape)
    big = max(out, key=lambda x: len(x.text)) if out else Sent("0:0", 0, s[:30000], 0, min(len(s), 30000), 30, False)
    t0 = time.perf_counter()
    gg = G.sentence_gate(big)
    dg = (time.perf_counter() - t0) * 1000
    oi = time.perf_counter()
    G.opaque_indices(tokenize(big.text))
    do = (time.perf_counter() - oi) * 1000
    ok = dt < 100 and dg < 100 and do < 100 and isinstance(gg, Gate)
    check(f"{name}: segment {dt:.0f} ms, gate {dg:.0f} ms, opaque {do:.0f} ms", ok, (dt, dg, do))
print(f"   worst segment time: {worst:.0f} ms")
sent_big = Sent("0:0", 0, "word and then " * 2000, 0, 28000, 6000, False)
sent_small = Sent("0:1", 0, "I went home today.", 0, 18, 4, True)
t0 = time.perf_counter()
FL.flow_metrics([sent_big] + [sent_small] * 7, source="whisper")
check("flow_metrics on a 30k-char turn (one huge sentence + 7 small) < 100 ms", (time.perf_counter() - t0) * 1000 < 100)
t0 = time.perf_counter()
SG.apply_starts("word " * 6000, ["word word"] * 100)
SG.align_hints("word " * 6000, [["word", i * 0.1, i * 0.1 + 0.05] for i in range(6000)], [[0, 1]] * 2000)
check("apply_starts / align_hints on huge inputs < 100 ms", (time.perf_counter() - t0) * 1000 < 100)

main("unit_segment")
