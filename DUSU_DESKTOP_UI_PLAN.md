# DuSu — Desktop UI Plan (≥ 1200px)

> **Scope:** presentation only. No JavaScript, no DOM, no backend, no copy, no routing,
> no feature changes. Everything below is implemented as **one appended CSS block**
> inside `@media (min-width:1200px)` (plus a small `min-width:1600px` tier) at the end of
> the existing `<style>` in `backend/test_client.html`.
>
> **Guarantee:** every new rule lives inside a `min-width` media query, so the phone /
> PWA / Android-TWA rendering below 1200px is byte-for-byte the same as before. Nothing
> existing is edited or deleted — only added.

---

## 1. Why

DuSu is built mobile-first: `.wrap` is capped at `max-width:440px` and the navigation is a
76px bar pinned to the bottom of the viewport. On a laptop that renders as a narrow phone
strip floating in the middle of a 1440–1920px screen with a bottom bar that belongs on a
phone. The product looks unfinished on the device a placement-season user actually does
their homework on.

The fix is **not** a redesign. It is a desktop *layer*: give the shell a real desktop
chrome (left sidebar + centred content column + sticky header), then let the screens that
are genuinely lists-of-peers use the horizontal space they were always meant to have.

## 2. The breakpoint

| Range | Layout |
|---|---|
| `< 1200px` | **Untouched.** Current mobile-first shell, bottom nav, 440px column. |
| `≥ 1200px` | Desktop shell: left rail nav, 1120px content column, sticky header, multi-column screens. |
| `≥ 1600px` | Same as desktop, slightly wider (`--rail:280px`, `--shell:1240px`). |

One hard breakpoint, exactly as specified — no tablet tier. A 1024px iPad keeps the
mobile layout, which is the correct call for a touch device with a mic.

## 3. Design tokens (desktop only)

```css
@media (min-width:1200px){
  :root{ --rail:264px;  /* fixed sidebar width  */
         --shell:1120px;/* content column width */
         --gut:44px; }  /* content gutter       */
}
```

Nothing about colour, type family, radius, or motion changes. The desktop layer reuses the
existing `--grad`, `--gold`, `--glass`, `--font-d` / `--font-b` tokens so both breakpoints
stay one brand.

## 4. The shell

### 4.1 Bottom nav → left sidebar rail

`nav.bnav` is `position:fixed` already, so it re-anchors with pure CSS: `left:0; top:0;
height:100dvh; width:var(--rail); flex-direction:column`. Every `.btab` flips from a
stacked icon-over-label tab to a horizontal row (icon, then label, left-aligned) with a
hover wash and a gold pill for `.active`. The click handlers, the `NAV_TAB` map, the
`MutationObserver` that derives nav visibility — all untouched, because only the painting
changed.

* A `::before` on the rail carries the `/logo.png` mark + "DuSu" wordmark — the app
  identity a desktop sidebar is expected to have.
* `[data-tab="more"]` gets `margin-top:auto`, so *More* sits at the foot of the rail
  (standard desktop convention) instead of in the middle of the list.
* `.bnav.hide` (login / level check) still wins — and `body:has(#login.on)`,
  `body:has(#assessment.on)` drop the rail's reserved space so those two screens stay
  full-bleed and centred.

### 4.2 Content column

`body { padding-left:var(--rail) }` reserves the rail; `.wrap` becomes
`max-width:var(--shell)` with `padding:0 var(--gut) 64px` — dropping the 76px bottom-nav
reserve that no longer exists on desktop. `.wrap` stays the single scroll region, so the
`scrollShellTop()` helper and the `overflow:hidden` body contract keep working unchanged.

### 4.3 Sticky header

`header.top` becomes `position:sticky; top:0` inside `.wrap`, with a blurred translucent
background and negative side margins so it spans the full column. `.wrap`'s `padding-top`
goes to `0` so the header sits flush against the scrollport edge (a sticky element inside a
padded scroller otherwise leaves a see-through strip above it). Usage chips, the day chip,
the voice toggle and the user chip are all already visible above 560px.

### 4.4 Overlays

| Element | Mobile | Desktop |
|---|---|---|
| `#msheet` / `#rgSheet` (`.msheet`) | bottom sheet sliding up over the nav | centred modal dialog, 520px, scale-in; `.mrow` rows laid out **2-up** |
| `.notif` | full-width bar pinned to the top centre | rounded toast, top-right, 420px |
| `.bootgate` | full-screen | unchanged (must cover the rail too) |

The `.msheet` off-state must gain `opacity:0; pointer-events:none` on desktop — on mobile
it is parked off-screen by `translateY(130%)`, but a centred modal that is merely
transparent would still swallow clicks over the middle of the screen.

### 4.5 Ambient + affordances

Above 640px the aurora blobs, film grain, floating hero words and hero particles are
already enabled — on desktop they finally have room to read. Added on desktop only:
a `:focus-visible` gold outline so keyboard navigation (a real desktop input method) is
visible.

## 5. Screen-by-screen

| Screen | Desktop treatment |
|---|---|
| **login** | Card centred at 460px with a taller top offset and a larger mark. Rail hidden. |
| **home** | Hero (`.hstage`) centred and scaled up: 200px character, `clamp(38px,3.4vw,54px)` title, larger Start button, and the 340px home cards (Speaker Rank, League, Today's goal, Missions, Career) widened to 420px. `#moreHome`'s children are centred at 780px so banners stay readable, while `.foot` keeps the full 1060px and renders its existing 3-column layout. Companion-Moment recommendations (`.moment-recs`) become a **3-up grid** instead of a stack. |
| **practice** | The flagship change. `.modes` becomes a **3-column grid**, and `.mode-card` returns to its full card form — the description, feature chips, badge and watermark that mobile hides for density are re-shown, the card grows to a 24px-radius panel with a 52px icon tile, and all three cards stretch to equal height. |
| **setup** | Interview card centred at 520px with roomier padding. |
| **session** (Talk / Interview) | **Two columns**: the orb stage + state label + End control on the left, the live transcript `.feed` on the right as a bordered panel at `min(60vh,520px)` instead of a 34vh strip under the orb. Orb and face scale from 150 → 180px. |
| **daily** | Centred at 900px, larger orb (`#dorb`), 132px mic, `.trans-card` to 640px, bigger quick-action buttons. |
| **learning** | Centred at 900px, 132px mic, `.trans-card` to 640px. |
| **lesson** | Centred at 820px, 30px prompt, larger mic. |
| **assessment** | Body to 720px, larger step heading, and `.opt-list` becomes `repeat(auto-fit,minmax(260px,1fr))` so multiple-choice answers sit 2-up instead of one long stack. |
| **report** | 980px; `#report.on` becomes a grid so **Strengths and Fixes sit side by side**, everything else spans full width; `.metrics` goes from 2 → **3 columns**. |
| **sessionResult** | Centred at 640px. |
| **journey** | 1000px; `.dash-skills` 2 → **3 columns**; `.roadmap` levels in a **2-column grid**; stat chips given more padding. |
| **leaderboard / league** | 900px; larger podium; `.lb-list` rows in a **2-column grid**. |
| **achievements** | `#achGrid` 2 → **4 columns**. |
| **keys** | **Two columns**: mode picker spans the top, the numbered walkthrough + tutorial video on the left, the key form on the right — so a first-time user reads the steps and fills the inputs without scrolling between them. |
| **profile / help / subscribe / superadmin / career** | Centred at 720–820px (forms should not stretch to 1120px). |
| **admin** | `#adminBody` becomes a grid where headings/stats/switches span full width and `.uCard` user cards auto-place **2-up**. |

## 6. Techniques and constraints

Things that had to be respected while writing the layer:

1. **`.screen.on` specificity.** The base is `.screen.on{display:block}` (0,2,0). Any
   desktop rule that changes a screen's `display` must use `#id.on` (1,1,0), which wins on
   ID count. Used for `#session.on` and `#report.on` only.
2. **`[hidden]{display:none !important}`** must keep winning — no desktop rule sets
   `display` on an element that JS toggles with the `hidden` attribute.
3. **Grid row linkage.** Two independent stacks cannot share a grid without their rows
   locking together, which would tear a `.sec-label` away from the block it labels. So
   multi-column layouts are only applied where the children are genuine peers
   (`.uCard`, `.lvl-row`, `.lb-row`, `.ach-card`, `.metric`, `.mode-card`) or where every
   child's row can be placed explicitly (`#session`, `#report`, `#keys .keys-wrap`).
   `#moreHome` deliberately stays a single column for this reason.
4. **Shorthand ordering.** `.wrap`'s base rule sets `padding` then overrides
   `padding-bottom`; the desktop rule therefore re-declares the whole `padding` shorthand.
   `body:has(#login.on) .wrap` has higher specificity and keeps its own padding-bottom.
5. **SVG size attributes.** `#face`, `#dorb .wface` and the practice icons carry
   `width`/`height` presentation attributes; CSS beats those, so the orb and its face are
   scaled together rather than one growing inside the other. `.score-ring` is left alone —
   its `<svg>` and absolutely-positioned value overlay are size-coupled.
6. **`!important` overrides.** `.mode-card p, .mc-chips, .mc-badge, .mc-wm` are hidden with
   `!important` in the mobile density pass, so the desktop re-show needs `!important` too.

## 7. What is explicitly *not* changed

* No JS, no event handlers, no router, no `NAV_TAB`/`PATH_TAB`, no WebSocket flow.
* No backend, no templates, no endpoints, no service-worker logic.
* No copy, no icons, no colours, no fonts, no new dependencies.
* No behaviour below 1200px — phone, PWA and the `com.dusu.app` TWA are bit-identical.

## 8. Ship checklist

1. Append the desktop block before `</style>` in `backend/test_client.html`.
2. `node --check` the extracted inline `<script>` (unchanged, but the file was edited).
3. Confirm the CSS block is balanced and the file still parses.
4. Bump `CACHE` in `backend/sw.js` (`dusu-v13` → `dusu-v14`) — documented practice for any
   shell change.
5. `docker compose up -d --build backend` (code is baked into the image; a bare `up` would
   not pick up the edit).
6. `curl -s localhost:3878/ | grep` for a desktop-layer marker to confirm the live build
   actually serves it.
7. Commit + push `main`.
