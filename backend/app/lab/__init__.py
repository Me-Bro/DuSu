"""Grammar Lab - Hindi sentences into English, the twelve tenses x four levels, checked by RULES (no AI call anywhere), explained in Hindi (design: the learner-first plan, Part 3).

Pure modules (no database, no network, no clock):
  forms      the twelve tense forms: which form does an English sentence use? (+ the token helpers)
  catalog    the units, levels, formulas, what the Hindi ending signals, the traps Hindi speakers fall into
  checker    one answer against the accepted answers -> ok / wrong (+ exactly why) / unsure
  explain    the verdict in Hindi and English (fixed templates)
  bank/      the item bank: one module per unit, authored once, linted by tests/lab/lint_bank.py
Async / DB: models (gl_*), service, api (/lab/*).

Switch: settings.grammar_lab = off (default) / owner / on.  No learner text is ever stored; progress is stars per unit and level plus server-graded attempts the Path will read.
"""
