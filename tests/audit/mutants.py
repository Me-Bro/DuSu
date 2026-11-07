#!/usr/bin/env python3
"""Planted bugs for the CLIENT side of the audit fixes: writes one deliberately broken copy of the page per mutant to tests/audit/.out/mut/<name>.html and prints
"<name> <sections>" - the verify.cjs sections that must FAIL when the app is served that copy (tests/audit/mutants.sh runs them). Each replacement must match EXACTLY once, so a
refactor that moves the code fails loudly here instead of silently planting nothing.

    python3 tests/audit/mutants.py            (from the repo root)
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = open(os.path.join(ROOT, "backend", "test_client.html"), encoding="utf-8").read()
SRC = SRC.replace("__GOOGLE_CLIENT_ID__", "audit-client").replace("__AUTH_ENABLED__", "true").replace("__MAX_SESSIONS__", "20")   # what the server does on GET /
OUT = os.path.join(ROOT, "tests", "audit", ".out", "mut")
os.makedirs(OUT, exist_ok=True)

# (name, [(old, new)], sections that must fail, what the bug is)
M = [
    ("m01_history_always_true", [('return flag || (p.xp || 0) > 0 ||', 'return true || (p.xp || 0) > 0 ||')], "F,H", "a brand-new learner counts as having history: the rewards lecture and 'where we left off' come back"),
    ("m02_history_never", [(re.compile(r'return flag \|\| \(p\.xp \|\| 0\) > 0 \|\| \(sp\.speaker_xp[^\n]*?\.trim\(\);'), 'return false;')], "F,H", "nobody has history: the established learner loses 'where we left off', the rewards guide never opens"),
    ("m03_deeplink_never_waits", [('function flagPending(path){ const f = flagForPath(path); return !!f && !_meLanded &&', 'function flagPending(path){ const f = flagForPath(path); return false && !!f && !_meLanded &&')], "R", "the original race: a cold deep link is judged before /me answers"),
    ("m04_plural_always_s", [('(Number(n) === 1 ? one : (many || one + "s"))', '(false ? one : (many || one + "s"))')], "H", "'1 sessions'"),
    ("m05_time_style_unnormalised", [('.replace(/\\b(am|pm)\\b/gi, m => m.toUpperCase())', '.replace(/\\b(am|pm)\\b/gi, m => m)')], "H", "'7:00 pm' next to '8:30 PM'"),
    ("m06_key_prefix_swapped", [('const PREFIX = [["groq", /^gsk_/], ["gemini", /^AIza/]', 'const PREFIX = [["gemini", /^gsk_/], ["groq", /^AIza/]')], "K", "the wizard names the wrong service for a pasted key"),
    ("m07_reserve_wrong_plan", [('body: JSON.stringify({ plan:_plan, price_feel:_feel })', 'body: JSON.stringify({ plan:"starter", price_feel:_feel })')], "P", "Reserve my plan saves a different plan from the one chosen"),
    ("m08_short_chat_scored", [('const tooShort = (sp.minutes || 0) < 0.5 || !(sp.overall > 0);', 'const tooShort = false;')], "F", "a 12-second chat ends with the red 'Speaking Score 0 (-64)'"),
    ("m09_report_strengths_unescaped", [('(d.strengths||[]).map(s=>`<li>${esc(s)}</li>`)', '(d.strengths||[]).map(s=>`<li>${s}</li>`)')], "X", "model-written strengths reach innerHTML as markup"),
    ("m10_lang_pill_back_at_bottom", [('#home.hm-on .hstage .lg-row > .lg-sw{ order:-1;', '#home.hm-on .hstage .lg-row > .lg-sw{ order:30;')], "U", "the Hindi / English pill goes back to the bottom of the first screen, behind the nav"),
    ("m11_numerals_default", [('color:var(--ink); font-variant-numeric:lining-nums;', 'color:var(--ink);')], "U", "old-style numerals ('0' like an 'o', '71' like '7I') come back"),
    ("m12_my_day_icons_40", [('.pl-ib{ width:44px; height:44px;', '.pl-ib{ width:40px; height:44px;')], "U", "My Day's edit / delete buttons shrink below 44 px"),
    ("m13_gate_has_no_fallback", [('if(homeAfter){ try{ if(authToken && !_meLanded', 'if(false){ try{ if(authToken && !_meLanded')], "R", "a hung /me leaves a signed-in learner on the sign-in card"),
    ("m14_header_alias_back", [('header.top .tag, header.top .uwho, header.top .signout{ display:none !important; }', 'header.top .tag, header.top .signout{ display:none !important; }')], "U", "the name / alias block returns to the phone header"),
    ("m15_badge_hint_gone", [('${esc(BADGE_HOW[id] || "")}', '')], "U", "locked badges say only 'Locked' again"),
    ("m16_empty_state_no_button", [('if(o.cta){ const b = document.createElement("button");', 'if(false){ const b = document.createElement("button");')], "H", "empty screens are dead ends again (no button)"),
    ("m17_rewards_before_speaking", [('if(!hasHistory()) return;                               // after the FIRST finished session', '// (removed)                               // after the FIRST finished session')], "F", "the four-card rewards lecture opens before the learner has spoken"),
    ("m18_fonts_from_google", [('src:url(/assets/fonts/inter-latin-v1.woff2) format("woff2");', 'src:url(https://fonts.gstatic.com/s/inter/v20/inter-latin.woff2) format("woff2");')], "W", "a font is fetched from Google again (an extra origin on the first visit)"),
    ("m20_funnel_card_missing", [('function wireOffice(){\n  loadApplink();\n  loadFunnel(30);', 'function wireOffice(){\n  loadApplink();')], "U", "the first-run funnel is not shown on the owner's dashboard any more (only the raw endpoint remains)"),
    ("m21_status_retry_loop", [('    if(!force && FAILAT && Date.now() - FAILAT < 30000) return S;', '    // (no pause after a failure)')], "V", "a failing /keys/status is retried in a tight loop again (review finding 1)"),
    ("m22_history_journey_xp_only", [('return flag || (p.xp || 0) > 0 || (sp.speaker_xp || 0) > 0 || (mf.total_sentences || 0) > 0 || !!String(mf.next_hook || "").trim();', 'return flag || (p.xp || 0) > 0 || !!String(mf.next_hook || "").trim();')], "V", "history = Journey XP only: a learner who only talks in Face to Face is brand new again (review finding 2)"),
    ("m23_empty_result_always_none", [('lgt(spoke ? "srSaved" : "srNone")', 'lgt("srNone")')], "V", "an empty session result always says \"No sentences yet\" (review finding 3)"),
    ("m24_wizard_wipes_second_key", [('if(cleanPaste(inp.value) === v) inp.value = "";', 'inp.value = "";')], "V", "the wizard wipes a key pasted while the first one was saving (review finding 6)"),
    ("m25_opinion_can_be_unpressed", [('if(_feel === b.dataset.feel && mine && mine.price_feel) return;', '')], "V", "a saved price opinion can be un-pressed but the server keeps it (review finding 7)"),
    ("m26_history_flag_is_device_wide", [('flag = !!v && (v === me || (!me && v === "1"));', 'flag = !!v;')], "V", "a second account on a shared phone inherits history (review finding 8)"),
    ("m27_home_chat_aap_hint", [('orbListenHint:"बोलो, फिर रुको"', 'orbListenHint:"बोलिए, फिर रुकिए"')], "H", "the Home chat's orb hint is in the formal register again beside DuSu's tum replies (C-2)"),
    ("m28_pointer_to_retired_name", [('keysLimit:"Your API keys hit their limit — add or replace a key in More → My AI keys."', 'keysLimit:"Your API keys hit their limit — add or replace a key in More → DuSu keys."')], "N", "a message sends the learner to a More row that is no longer called that (C-5)"),
    ("m29_plan_hint_always_hidden", [('const hint = $("planHint"); if(hint) hint.hidden = !!_plan;', 'const hint = $("planHint"); if(hint) hint.hidden = true;')], "Y", "the plans page is back to a dim 'Reserve my plan' with no reason (visual review 1)"),
    ("m30_plan_ring_never_fills", [('button.plan.sel .plan-top b::before{ border-color:var(--gold); background:radial-gradient(circle, var(--gold) 0 4px, transparent 5px); }', 'button.plan.sel .plan-top b::before{ border-color:var(--gold); }')], "Y", "choosing a plan does not mark its ring (visual review 1)"),
    ("m31_my_day_subtitle_cut_again", [('.pl-top .sess-sub{ white-space:normal; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }', '.pl-top .sess-sub{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }')], "Y", "My Day's summary is cut with an ellipsis again (visual review 4)"),
    ("m32_alias_breaks_mid_word", [('#pfAlias, #pfDay{ word-break:normal; overflow-wrap:break-word; }', '#pfAlias, #pfDay{ word-break:break-all; }')], "Y", "the leaderboard alias on Profile is cut in the middle of the word again (visual review 5)"),
    ("m33_chart_from_one_day", [('const tlOK = tl.length > 2 && new Set(tl.map(x => x.date)).size > 2;', 'const tlOK = tl.length > 2;')], "Y", "five equal bars from one day's sessions are drawn again (visual review 6)"),
    ("m34_iso_dates_back", [('return isNaN(d) ? String(iso) : d.toLocaleDateString("en-IN", { day:"numeric", month:"short" }); };', 'return String(iso); };')], "Y", "the Journey captions show 2026-10-30 again, cut in the middle (visual review 6)"),
    ("m35_empty_result_ring_loading", [('    $("srDuration").textContent = "—";\n    const k = $("srKick"); if(k && !spoke)', '    const k = $("srKick"); if(k && !spoke)')], "Y", "an empty session result keeps the loading dots in its ring (visual review 12)"),
    ("m36_grammar_buttons_side_by_side", [('h("div", { class:"gc-acts gc-stack" }, btn(t("setExport")', 'h("div", { class:"gc-acts" }, btn(t("setExport")')], "Y", "the Grammar data buttons share a row again and the delete label wraps to five lines (visual review 13)"),
    ("m37_keys_underline_floats", [('text-decoration:underline dotted color-mix(in srgb,var(--gold) 70%,transparent); text-underline-offset:4px }', 'text-decoration:none; border-bottom:1px dotted color-mix(in srgb,var(--gold) 55%,transparent) }')], "Y", "the 'Get free key' underline floats 20 px below the words again (visual review 14)"),
    ("m38_remove_looks_like_change", [('  .ky-acts .ky-del{ color:#f2c4ba; border-color:rgba(224,138,122,.45); }', '  .ky-acts .ky-del{ }')], "Y", "Remove looks exactly like Change and Test (visual review 14)"),
    ("m39_avatar_initial_dim", [('  .userchip .uav-init{ color:#241a08; font-size:14px; }', '  .userchip .uav-init{ }')], "Y", "the avatar initial is the dim tan text colour on periwinkle again (visual review 15)"),
    ("m40_mood_row_wraps", [('  .mood-opts { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; }', '  .mood-opts { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; }')], "Y", "the mood buttons wrap 4 + 1 again (visual review 16)"),
    ("m41_league_no_not_on_board_row", [('  } else if(!you){\n    // a learner with no practice this week', '  } else if(false){\n    // a learner with no practice this week')], "Y", "a learner who is not on the weekly board gets no explanation (visual review 8)"),
    ("m42_you_are_alias", [("'Others see you as <b style=\"color:var(--gold-lt)\">'", "'You are <b style=\"color:var(--gold-lt)\">'")], "Y", "the Ranks subtitle says 'You are <alias>' beside the real name again (visual review 8)"),
    ("m43_guide_does_not_scroll", [('if($("ksHelp").open){ paintKeysCards(); revealOpened($("ksHelp")); }', 'if($("ksHelp").open){ paintKeysCards(); }')], "Y", "the wizard's guide opens below the fold with nothing to show it happened (visual review 20)"),
    ("m44_sliders_icon_back", [('<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>\n          </div>\n          <h3 data-tag="Scored report">', '<path d="M20 7h-9M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>\n          </div>\n          <h3 data-tag="Scored report">')], "Y", "Interview Prep draws the 'sliders' (Settings) icon again (visual review 11)"),
    ("m45_hindi_priority_more", [('pLow:"कम", pNorm:"Normal", pHigh:"ज़रूरी"', 'pLow:"कम", pNorm:"Normal", pHigh:"ज़्यादा"')], "Y", "the Hindi priority chip reads 'ज़्यादा' (more) again (visual review 17)"),
    ("m46_badge_names_collide", [('consistent_speaker:"🏅 Marathon Speaker (50+ hrs)"', 'consistent_speaker:"🏅 Consistent Speaker (50+ hrs)"')], "Y", "two badges are both called 'Consistent Speaker' again (visual review 18)"),
    ("m48_help_address_never_filled", [('  const mail = $("helpMail"); if(mail){ const m = ["support", "ranabrothers.online"].join("@"); mail.href = "mailto:" + m; mail.textContent = m; }\n', '')], "N", "the Help screen's support address is never filled in: 'Or email us at' with nothing after it"),
    ("m49_help_address_in_markup", [('<a id="helpMail" style="color:var(--ink-faint)"></a>', '<a id="helpMail" href="mailto:support@ranabrothers.online" style="color:var(--ink-faint)">support@ranabrothers.online</a>')], "N", "the support address is written into the page markup again: Cloudflare rewrites it, injects a blocking script and drops the ETag"),
    ("m47_dusu_capitals", [('<span class="msub">Your DuSu badge collection</span>', '<span class="msub">Your DUSU badge collection</span>')], "Y", "the brand is spelled DUSU in the More sheet again (visual review 18)"),
    ("ctl_untouched_page", [('function loadGIS(){', 'function loadGIS(){ /* control: a harmless comment */')], "S,W,H", "CONTROL - a harmless change: every check must still PASS (proves the planted-bug runs fail because of the bug, not because of the override mechanism)"),
]

only = sys.argv[1:]
for name, subs, sections, why in M:
    if only and name not in only:
        continue
    s = SRC
    for old, new in subs:
        if isinstance(old, re.Pattern):
            hits = len(old.findall(s))
            if hits != 1:
                sys.exit(f"{name}: pattern matched {hits} times (need exactly 1): {old.pattern[:70]}")
            s = old.sub(lambda m: new, s, count=1)
        else:
            hits = s.count(old)
            if hits != 1:
                sys.exit(f"{name}: text matched {hits} times (need exactly 1): {old[:70]}")
            s = s.replace(old, new)
    open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8").write(s)
    print(f"{name} {sections} :: {why}")
