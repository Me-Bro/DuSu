# Grammar Lab - how to author a bank module

The Grammar Lab shows a learner a **Hindi sentence** (Devanagari). The learner says or types it in **English**. DuSu checks it against the accepted English answers you write here.
Learners are Indian, A1-B1, Hindi speakers who "know" English but freeze when they must speak it. Each sentence teaches one thing: **which tense form to use, and how it is built**.

You write ONE python file per unit: `backend/app/lab/bank/<unit>.py`. Read `backend/app/lab/bank/__init__.py` (the format) and `backend/app/lab/catalog.py` (the unit names, formulas,
the Hindi endings each unit signals, the trap ids) first. Then lint your work until it is clean:

    python3 tests/lab/lint_bank.py <unit> [<unit2>]        # run from the repo root; exit 0 = clean

## The file

```python
UNIT = "present_simple"
ITEMS = [
    # (id, level, hindi, [accepted english ...], trap)      trap is optional ("" or one of catalog.TRAP_IDS)
    ("prs-e-01", "easy", "राम रोज़ सुबह चाय पीता है।", ["Ram drinks tea every morning."], ""),
]
```
* id = `<unit code>-<level letter>-<nn>`: unit codes prs prc prp prpc pas pac pap papc fus fuc fup fupc; levels e m h x (easy, medium, hard, extra); nn = 01..12. **Exactly 12 items per level, 48 per unit.**
* Hindi: **natural spoken Hindi** (not Sanskritised), **Devanagari only** (no Latin letters at all - write names and loan words in Devanagari: "क्रिकेट", "ट्रेन"), ends with `।` or `?`, 3-18 words.
* English: a capital letter at the start, `.` `?` or `!` at the end. List only genuinely **different phrasings** (a synonym, a different structure; 1-3 is normal, 4 is the maximum). Do NOT list
  contractions (`doesn't`), `going to` for `will`, or a time phrase moved to the other end of the sentence ("Every day I go..." vs "I go ... every day") - those are accepted automatically.

## The four levels (12 items each)
| level | what it is | the lint enforces |
|---|---|---|
| easy (e) | short plain **affirmative** sentences, ONE clear time word, common verbs, 4-9 English words | >= 10 affirmative; <= 9 words |
| medium (m) | **negatives and questions**, irregular verbs, he / she / it subjects, 6-12 words | >= 3 negatives AND >= 3 questions |
| hard (h) | two ideas in one sentence (when / while / before / after / because / if), since / for, adverbs, 8-17 words | >= 4 two-clause sentences, >= 2 negatives, >= 2 questions |
| extra (x) | **the tricky ones**: tenses that look alike, idiomatic Hindi, 9-19 words | >= 6 items with a `trap` tag, >= 2 negatives, >= 2 questions |

## Hindi rules (the learner can be any gender)
* **Never use `मैं` with a gendered verb ending** (जाता हूँ / जाती हूँ / जाऊँगा / रहा हूँ ...). Use a name (राम, सीमा, अनिल, प्रिया, रोहन, नेहा, अमित, पूजा, कविता, सुनील), a family word (मेरा भाई,
  उसकी बहन, पिताजी), `वह`, `वे`, `हम`, `तुम`, `आप`, the object ("बारिश", "ट्रेन"). `मैंने` and `मुझे` are fine.
* never `तू / तेरा / तुझे`.
* Everyday Indian life: school, office, bus, train, market, chai, cricket, phone, exam, family, festivals, cooking, weather, shops. **Nothing** about politics, religion, romance, violence, money problems or health scares.
* **The Hindi must signal the tense.** The Hindi ending (see `catalog.UNIT_META[unit]["marker"]`) should naturally lead to the target form, so the learner learns the mapping. If the Hindi could
  reasonably be rendered in another tense, add a time word (अभी, कल, पहले से, दो घंटे से ...) - unless the item is a deliberate trap (then tag it).

## English rules
* Natural everyday English, the way a fluent speaker would say it. Every accepted answer must read as **this unit's tense** - the lint says "reads as X, not Y" if not.
* Avoid verbs spelled the same in V1 and V2 (put, cut, read, hit, set, let, hurt, shut) in the Past Simple unless a time word makes the tense obvious.
* Vary the verbs (regular AND irregular), the subjects (singular and plural, names, pronouns) and the situations. Do not use the same verb more than 3 times in one level.
* A sentence must have ONE correct answer set that a careful learner would give - avoid Hindi that has many equally good English renderings.

## Traps (use in the `trap` field; required in `extra`, welcome anywhere)
`since_for` `pp_vs_ps` `stative` `time_clause` `ps_pc` `ps_vs_pp_past` `irregular` `question_order` `negative` `third_person` - the texts are in `catalog.TRAPS`.
Tag an item only when it really needs that rule.

## What to report
Your final message: one short paragraph - the files written, the lint result (items / errors / warnings), and **any sentence you believe the classifier reads wrongly** (quote it). Do not fight
the classifier: rephrase to a clear natural alternative, and report the disagreement. Never edit any file except your own bank module(s).
