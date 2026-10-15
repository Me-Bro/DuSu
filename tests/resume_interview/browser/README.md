# Resume Interview — browser tests (client half)

Real Chromium (Playwright) against a **copy** of `backend/test_client.html` and a **stateful in-memory stand-in for the
`/rinterview/*` API**, written from the client/server contract — not from the real server. Nothing here needs the Python backend,
a database or a network: every `/rinterview/*`, `/me` and `api.groq.com` request is answered by the harness, and anything else
that leaves the box (fonts, analytics) is aborted.

What it proves: the client follows the contract, every failure branch ends in a plain sentence and keeps the learner's recording,
the screen works at 360×640 / 390×844 / 1280×800, a stored XSS is impossible through any field, and **with the feature flag off
the app is identical to the original** (text, element order, markup and pixels).
What it cannot prove: a real phone / the Android TWA microphone, real Whisper or Gemini output, the real server's wording of its
errors, a real `visualViewport` on-screen keyboard (it is faked), push of any kind.

## One-time setup

Docker is the only requirement (the Playwright npm package is cached outside the repo; nothing is installed in it):

```bash
mkdir -p ~/.cache/dusu-ri-pwrun && cd ~/.cache/dusu-ri-pwrun
docker run --rm -v "$PWD":/w -w /w -e npm_config_cache=/w/.npm mcr.microsoft.com/playwright:v1.60.0-noble \
  bash -lc 'npm init -y >/dev/null; npm i playwright@1.60.0 pngjs@7'
```

(Docker Desktop on Linux only shares paths under `$HOME`, so the cache and the screenshots live there. The image tag and the npm
version must match: v1.60.0 here. 1.55 / 1.56 images are also on this box.)

## Run

```bash
tests/resume_interview/browser/run.sh flow.spec.cjs            # one spec, one throw-away container, no host port bound
tests/resume_interview/browser/run-all.sh                      # every spec (about 18 minutes); prints one summary line per spec
tests/resume_interview/browser/run-all.sh quick                # without the screenshots / old=old tiers and the 17-second case
```

Environment knobs (forwarded into the container): `WRAP=0|1` (error bodies as the bare contract `{"error": …}` or FastAPI-style
`{"detail": …}` — the client must cope with both, so the flow and edge specs are run in each), `CASES=a,b` (edge scenarios),
`VP=360x640` (looks), `VERBOSE=1`. Screenshots, logs and diffs land in `~/.cache/dusu-ri-shots/` (`OUT_DIR=` to change).

## The specs

| Spec | What it covers |
|---|---|
| `flow.spec.cjs` | The whole journey: Home card → hub → resume (paste, file, edit → new version, earlier version, consent) → job → analysing → match (ticks, copy, re-upload → comparison) → start → read-aloud question, mic disabled while DuSu speaks, `cancel()` before `getUserMedia`, recording, direct-from-phone Groq call (model / timestamps / language / ≤200-char prompt), feedback (bands, no raw numbers, mistakes with "not what I said"), Finish gating at exactly 3 → report → history, Practice again, settings, export, delete |
| `edge.spec.cjs` | Upload errors (413 / 415 doc & other / 422 ×4 / 500) · analysis (502, 402, 429, 202 pending polls without re-POST, dropped connection, "still working" at 15 s) · start (502, 202) · answers (too short locally and by the server, no speech, Groq 401 / 429 / network, DuSu's own transcription, no key, mic denied, feedback 502 + retry, 202 pending, 409, dropped connection, 429 + retry with the SAME `client_key`) · Finish 409 / 500, Next 500 · interruptions while recording (Back, tab hidden, mic muted / ended, recorder error, leaving the screen, reload) · deep links and reload · library rows, Back / Forward, session reuse · report extras · the 2:30 / 3:00 limits (fake clock) · IndexedDB missing · delete / delete-all · a never-analysed draft · the daily / document / interview caps · the keys gate · history beyond the newest 30 (`GET /sessions?before=`) · a take rebuilt from the saved 10 s chunks after the tab died mid-recording · "Still working" on a slow answer · feedback the server keeps `pending` for over a minute (fake clock: the page gives up and offers Retry) · a paused account (403) · the server's own error codes that the contract did not list (`bad_file`, `extract_unavailable`, `too_short.reason = no_speech`) |
| `coach.spec.cjs` | The coaching layer: a first report with the improvement plan, every weakness explained (what happened / why / steps / a drill / the learner's own stronger answer / the questions it happened in), every answer re-readable in full; the hub's focus card; the next interview's focus bar and per-answer tick / cross; "Since your last interview"; an old-format report still rendering |
| `device.spec.cjs` | Two contexts = two phones, one learner: Continue on the other phone, the exact open question, 409 on a stale page, "the recording is on your other phone", per-phone Listen buttons in the report |
| `xss.spec.cjs` | Stored-XSS canary: `<img onerror>`, `<script>` and attribute break-outs in EVERY dynamic string (typed, uploaded, Whisper transcript, and everything the server sends); `window.__xss` must stay undefined and the hostile text must be visible as text; also the second page of a long history ("Show older interviews") |
| `static.spec.cjs` | Flag off / undefined / switched off while open; entry points; Home 2.0 tile; owner dashboard select; source hygiene (no `innerHTML` & co., no unused / missing strings, every CSS selector `ri-`-prefixed, only a ≥ 1200 px media query); accessibility basics; soft keyboard; logout / account deletion hooks; pruning of old audio; unicode titles |
| `looks.spec.cjs`, `looks2.spec.cjs` | 360×640, 390×844, 1280×800: every view and the special states (incl. a history longer than one page with "Show older interviews"), with an audit per state (no overflow, tap targets ≥ 44 px, dock on screen and clear of the nav) and screenshots to look at |
| `oldnew.spec.cjs` | "Old = old": the same scripted session, flag OFF, against the committed file (`git show HEAD:…`) and the working copy — text, element order, static markup and pixels of 12 old screens × 3 viewports |
| `smoke_noauth.spec.cjs` | The recipe in the project's memory notes: `__AUTH_ENABLED__ → false`, a seeded `userState`, no `/me` at all |
| `real.spec.cjs` + `run_real.sh` | NOT part of `run-all.sh` (it needs the `dusu-ri-test` image and starts its own scratch Postgres + the real app, see `../README.md`): the same client against the **real server** — the whole journey as the owner, a second device, another learner's isolation, a learner with her own Groq key, an XSS canary. It reuses `harness.cjs`, so keep the helper names there stable |

Last full run (`run-all.sh`, 2026-10-15), every line `N passed, 0 failed`: flow 170 + 170 (bare / `detail`-wrapped errors) · edge 210 + 210 · device 22 · xss 97 · static 109 · smoke (auth off) 7 · looks 243 · looks (special states) 164 · old = old 25 (1,427 checks, about 18 minutes).

`mock.cjs` is the contract: shapes, endpoints, error codes, idempotency, plus fault injection (`mock.faults.analyzePending = 1`,
`feedback502`, `answerDrop`, `answerAlready`, `finishNeedMore`, `plan502`, `status402`, …). `harness.cjs` holds the static server,
the request router, the in-page init script (speech stub, error collectors, fake-mic wrapper) and the layout audit.

## Negative controls (the suite must FAIL on these)

```bash
# a DOM builder that renders strings as HTML -> xss.spec must report the canary firing
python3 - <<'PY'
s = open('backend/test_client.html').read()
old = "    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));\n  }\n  function h(tag, a, ...kids){"
import os; open(os.path.expanduser('~/.cache/dusu-ri-shots/mut.html'), 'w').write(s.replace(old, "    if(c instanceof Node) el.appendChild(c); else el.insertAdjacentHTML('beforeend', String(c));\n  }\n  function h(tag, a, ...kids){"))
PY
HTML_SRC_HOST=$HOME/.cache/dusu-ri-shots/mut.html tests/resume_interview/browser/run.sh xss.spec.cjs        # (the copy must live under $HOME - see above)

# a leaked flag -> static.spec;  a CSS change on an old screen -> oldnew.spec (the pixel tier catches what text/order cannot)
```

## Notes

- The old-feature Home cards live in `#moreHome`, which the existing `goHome()` → `closeMoment()` hides for the rest of the page's
  life — so after any trip home the Home card (this one, Practice Room's and My Day's alike) is gone until a reload. The specs reach
  the hub through the Practice tab's entry after that. Not changed here (an old screen).
- `isMobile` contexts are used below 800 px; the desktop layer is exercised at 1280 px.
- Tests never touch the running `dusu-*` containers and bind no host port (each spec serves itself on a random port inside its own
  throw-away container).
