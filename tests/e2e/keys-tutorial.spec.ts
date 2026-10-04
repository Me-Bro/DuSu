/**
 * Keys screen — "how to add your free AI keys" guides.
 *
 * Contract under test: BOTH walkthroughs (mobile + laptop) are visible at once as
 * thumbnail cards, one shared player loads only after a tap (nothing is fetched from
 * YouTube before that — budget-Android data), the card for the visitor's device is
 * marked "recommended", and Hide / leaving the screen stops playback.
 *
 * Runs from the machine-global Playwright runner (nothing is installed in this repo):
 *   1. start the app WITHOUT Google sign-in or a DB, so a fresh browser lands on the
 *      forced key-setup screen:
 *        cd backend
 *        GOOGLE_CLIENT_ID= DATABASE_URL= .venv/Scripts/python -m uvicorn app.main:app --port 8011
 *   2. copy this file into ~/.claude/playwright-runner/tests/ and, with node >= 18:
 *        DUSU_URL=http://127.0.0.1:8011 node node_modules/@playwright/test/cli.js \
 *          test tests/keys-tutorial.spec.ts --reporter=list
 *
 * Hermetic: YouTube + thumbnail hosts are stubbed, everything else off-box is aborted.
 */
import { test, expect, Page } from '@playwright/test';

// Globals of the single-file client (top-level declarations, reachable by bare name).
declare let userState: any;
declare let useMode: string;
declare function show(id: string): void;
declare function loadKeysUI(): void;

const BASE = process.env.DUSU_URL || 'http://127.0.0.1:8011';
const PHONE_ID = 'vVcqXxnxmko';
const LAPTOP_ID = 'Oe0bYdxG6sg';
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64'
);

test.use({ serviceWorkers: 'block' });

type Net = { youtube: string[]; thumbs: string[]; errors: string[] };

/** Fresh browser → key-setup screen, with all off-box traffic stubbed and recorded. */
async function open(page: Page): Promise<Net> {
  const net: Net = { youtube: [], thumbs: [], errors: [] };
  page.on('pageerror', e => net.errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource|net::ERR/.test(m.text())) net.errors.push(m.text());
  });
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.startsWith(BASE)) return route.continue();
    if (u.includes('youtube-nocookie.com')) {
      net.youtube.push(u);
      return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>stub</title>' });
    }
    if (u.includes('i.ytimg.com')) {
      net.thumbs.push(u);
      return route.fulfill({ status: 200, contentType: 'image/png', body: PNG });
    }
    return route.abort();
  });
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { show('keys'); loadKeysUI(); });
  await expect(page.locator('#keys')).toHaveClass(/\bon\b/);
  return net;
}

/** Keys NOT mandatory for this account, Office mode open → the Hide button is offered. */
async function optionalSetup(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('dusu_tutorial_seen');
    userState = { office: false, onboarded: true };
    useMode = 'office';
    loadKeysUI();
  });
}

const card = (page: Page, which: 'phone' | 'laptop') => page.locator(`#keysTutorial .kvid[data-vid="${which}"]`);
const frame = (page: Page) => page.locator('#keysTutorialFrame');
/** URLs of YouTube player frames that are ACTUALLY loaded right now (an attribute alone proves nothing). */
const ytFrames = (page: Page) => page.frames().map(f => f.url()).filter(u => u.includes('youtube-nocookie'));

test.describe('phone (390×844, touch)', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('both guides are visible above the fold; nothing is fetched from YouTube yet', async ({ page }) => {
    const net = await open(page);
    await expect(page.locator('#keysTutorial .kvid')).toHaveCount(2);
    await expect(page.locator('#keysTutorial .kvid').nth(0)).toHaveAttribute('data-vid', 'phone');
    await expect(page.locator('#keysTutorial .kvid').nth(1)).toHaveAttribute('data-vid', 'laptop');

    for (const which of ['phone', 'laptop'] as const) {
      const c = card(page, which);
      await expect(c).toBeVisible();
      const b = (await c.boundingBox())!;
      expect(b.x, `${which} card left edge`).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width, `${which} card right edge`).toBeLessThanOrEqual(390);
      expect(b.y + b.height, `${which} card must be above the fold`).toBeLessThanOrEqual(844);
      expect(b.height, `${which} card tap target`).toBeGreaterThanOrEqual(44);
    }
    await expect(card(page, 'phone').locator('img')).toHaveAttribute('src', new RegExp(`/vi/${PHONE_ID}/`));
    await expect(card(page, 'laptop').locator('img')).toHaveAttribute('src', new RegExp(`/vi/${LAPTOP_ID}/`));

    // device match → "recommended" on the phone card only
    await expect(card(page, 'phone')).toHaveClass(/\brec\b/);
    await expect(card(page, 'laptop')).not.toHaveClass(/\brec\b/);

    // data-saving contract: no player, no YouTube request until a tap
    await expect(frame(page)).not.toHaveAttribute('src', /.+/);
    await expect(page.locator('#keysTutorialStage')).toBeHidden();
    expect(net.youtube).toEqual([]);

    // no sideways scroll on the shell
    const overflow = await page.evaluate(() => {
      const w = document.querySelector('.wrap') as HTMLElement;
      return w.scrollWidth - w.clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(0);
    expect(net.errors).toEqual([]);
  });

  test('tapping a card loads that video in the single player; tapping the other swaps it', async ({ page }) => {
    const net = await open(page);
    await card(page, 'phone').tap();
    await expect(frame(page)).toHaveAttribute(
      'src',
      new RegExp(`^https://www\\.youtube-nocookie\\.com/embed/${PHONE_ID}\\?(?=.*autoplay=1)(?=.*rel=0)(?=.*playsinline=1)`)
    );
    await expect(frame(page)).toHaveAttribute('title', /mobile|phone/i);
    await expect(page.locator('#keysTutorialStage')).toBeVisible();
    await expect(card(page, 'phone')).toHaveAttribute('aria-pressed', 'true');
    await expect(card(page, 'laptop')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('#keysTutorialYt')).toHaveAttribute('href', `https://youtu.be/${PHONE_ID}`);
    await expect.poll(() => ytFrames(page).join(' ')).toContain(PHONE_ID);   // the player really loaded

    await card(page, 'laptop').tap();
    await expect(frame(page)).toHaveAttribute('src', new RegExp(`/embed/${LAPTOP_ID}\\?`));
    await expect.poll(() => ytFrames(page).join(' ')).toContain(LAPTOP_ID);
    expect(ytFrames(page)).toHaveLength(1);
    await expect(frame(page)).toHaveAttribute('title', /laptop|computer|desktop/i);
    await expect(card(page, 'laptop')).toHaveAttribute('aria-pressed', 'true');
    await expect(card(page, 'phone')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('#keysTutorialYt')).toHaveAttribute('href', `https://youtu.be/${LAPTOP_ID}`);
    await expect(page.locator('#keysTutorial iframe')).toHaveCount(1);   // ONE player, never two
    expect(net.errors).toEqual([]);
  });

  test('"Best for you" is fully painted, sits on the card border and never covers the thumbnail', async ({ page }) => {
    await open(page);
    const tagOf = (which: 'phone' | 'laptop') => page.locator(`#keysTutorial .kvid-item:has(.kvid[data-vid="${which}"]) .kvid-tag`);
    const tag = tagOf('phone');
    await expect(tag).toBeVisible();
    const t = (await tag.boundingBox())!;
    const thumb = (await card(page, 'phone').locator('.kvid-thumb').boundingBox())!;
    expect(t.y + t.height, 'pill must end above the thumbnail').toBeLessThanOrEqual(thumb.y + 0.5);
    // Painted, not clipped: a <button> clips children that poke outside its box (that is exactly how
    // the pill first shipped — a sliver). Its own top edge must hit-test as the pill itself.
    const painted = await tag.evaluate(el => {
      const r = el.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + 2) === el;
    });
    expect(painted, 'pill top edge is visible (not clipped by an ancestor)').toBe(true);
    await expect(page.locator('#keysTutorial button .kvid-tag'), 'pill must not live inside a <button>').toHaveCount(0);
    await expect(tagOf('laptop')).toBeHidden();   // only the matching card is marked
    await tag.tap();                              // tapping the pill counts as tapping its card
    await expect(frame(page)).toHaveAttribute('src', new RegExp(`/embed/${PHONE_ID}\\?`));
  });

  test('each player has its video\'s real shape: mobile guide portrait (9:20), laptop guide 16:9', async ({ page }) => {
    await open(page);
    const ratio = async () => {
      const b = (await page.locator('#keysTutorialStage').boundingBox())!;
      return b.width / b.height;
    };
    await card(page, 'phone').tap();
    await expect(page.locator('#keysTutorialStage')).toBeVisible();
    expect(await ratio(), 'mobile guide is a portrait phone recording').toBeCloseTo(0.45, 1);   // ±0.05
    await card(page, 'laptop').tap();
    expect(await ratio(), 'laptop guide is landscape').toBeCloseTo(16 / 9, 1);
  });

  test('tapping the selected card again closes the player (the only way to collapse it on first run)', async ({ page }) => {
    await open(page);
    await expect(page.locator('#keysTutorialHide')).toBeHidden();   // keys mandatory → no Hide button
    await card(page, 'laptop').tap();
    await expect.poll(() => ytFrames(page).length).toBe(1);
    await card(page, 'laptop').tap();
    await expect(page.locator('#keysTutorialStage')).toBeHidden();
    await expect(card(page, 'laptop')).toHaveAttribute('aria-pressed', 'false');
    await expect.poll(() => ytFrames(page)).toEqual([]);
    await expect(page.locator('#keysTutorial')).toBeVisible();      // cards stay, ready to pick again
  });

  test('cards work from the keyboard (real buttons: Enter plays)', async ({ page }) => {
    await open(page);
    await card(page, 'laptop').focus();
    await page.keyboard.press('Enter');
    await expect(frame(page)).toHaveAttribute('src', new RegExp(`/embed/${LAPTOP_ID}\\?`));
  });

  test('re-running loadKeysUI() while a video plays leaves it playing', async ({ page }) => {
    await open(page);
    await card(page, 'phone').tap();
    const before = await frame(page).getAttribute('src');
    await page.evaluate(() => loadKeysUI());   // fired by mode toggles / verify flow
    await expect(frame(page)).toHaveAttribute('src', before!);
    await expect(page.locator('#keysTutorialStage')).toBeVisible();
  });

  test('leaving the keys screen stops playback', async ({ page }) => {
    await open(page);
    await card(page, 'phone').tap();
    await expect(frame(page)).toHaveAttribute('src', /.+/);
    await expect.poll(() => ytFrames(page).length).toBe(1);
    await page.evaluate(() => show('home'));
    await expect(frame(page)).not.toHaveAttribute('src', /.+/);
    await expect.poll(() => ytFrames(page)).toEqual([]);   // genuinely unloaded — audio must not carry on in the background
    await page.evaluate(() => { show('keys'); loadKeysUI(); });
    await expect(page.locator('#keysTutorialStage')).toBeHidden();
    await expect(card(page, 'phone')).toHaveAttribute('aria-pressed', 'false');
  });

  test('keys mandatory (first run): no Hide button — it would be a trap', async ({ page }) => {
    await open(page);
    await expect(page.locator('#keysTutorial')).toBeVisible();
    await expect(page.locator('#keysTutorialHide')).toBeHidden();
  });

  test('optional setup: Hide stops playback and collapses videos + steps, and stays hidden', async ({ page }) => {
    await open(page);
    await optionalSetup(page);
    await expect(page.locator('#keysTutorialHide')).toBeVisible();
    await card(page, 'phone').tap();
    await expect(frame(page)).toHaveAttribute('src', /.+/);
    await expect.poll(() => ytFrames(page).length).toBe(1);
    await page.locator('#keysTutorialHide').tap();
    await expect(frame(page)).not.toHaveAttribute('src', /.+/);
    await expect.poll(() => ytFrames(page)).toEqual([]);
    await expect(page.locator('#keysTutorial')).toBeHidden();
    await expect(page.locator('#keysSteps')).toBeHidden();
    expect(await page.evaluate(() => localStorage.getItem('dusu_tutorial_seen'))).toBe('1');
    await page.evaluate(() => loadKeysUI());
    await expect(page.locator('#keysTutorial')).toBeHidden();
    // Hiding the videos must never take the key form with it.
    await expect(page.locator('#keysForm')).toBeVisible();
    await expect(page.locator('#kGroq')).toBeVisible();
  });

  test('Personal mode (keys not needed): no guide, no player, no YouTube traffic', async ({ page }) => {
    const net = await open(page);
    await page.evaluate(() => {
      userState = { office: false, onboarded: true };
      useMode = 'personal';
      loadKeysUI();
    });
    await expect(page.locator('#keysTutorial')).toBeHidden();
    await expect(page.locator('#keysSteps')).toBeHidden();
    await expect(page.locator('#keysForm')).toBeHidden();
    await expect(frame(page)).not.toHaveAttribute('src', /.+/);
    expect(net.youtube).toEqual([]);
  });

  test('page structure: steps and key form are siblings of the video box, never inside it', async ({ page }) => {
    await open(page);
    // A missing closing tag once nested these inside #keysTutorial: invisible on a phone, but the
    // desktop grid fell apart AND hiding the videos would have hidden the key form with them.
    await expect(page.locator('#keys .keys-wrap > #keysTutorial')).toHaveCount(1);
    await expect(page.locator('#keys .keys-wrap > #keysSteps')).toHaveCount(1);
    await expect(page.locator('#keys .keys-wrap > #keysForm')).toHaveCount(1);
    await expect(page.locator('#keysTutorial #keysForm, #keysTutorial #keysSteps')).toHaveCount(0);
    await expect(page.locator('#keysTutorial > .kvid-pick > .kvid-item')).toHaveCount(2);
  });
});

// The portrait guide is tall — on the smallest phones it must still fit the screen whole.
for (const vp of [{ width: 360, height: 640 }, { width: 390, height: 844 }]) {
  test.describe(`player fits the screen (${vp.width}×${vp.height})`, () => {
    test.use({ viewport: vp, hasTouch: true, isMobile: true });

    for (const which of ['phone', 'laptop'] as const) {
      test(`${which} guide: whole player is scrolled into view after the tap`, async ({ page }) => {
        await open(page);
        await card(page, which).tap();
        await expect.poll(async () => {   // smooth scroll takes a moment
          const s = (await page.locator('#keysTutorialStage').boundingBox())!;
          const w = (await page.locator('.wrap').boundingBox())!;
          // The bottom nav is position:fixed OVER the scroller — "inside .wrap" is not "on screen".
          const nav = (await page.locator('#bnav').boundingBox())!;
          return s.y >= w.y - 1 && s.y + s.height <= Math.min(w.y + w.height, nav.y) + 1;
        }, { timeout: 5000 }).toBe(true);
      });
    }
  });
}

test.describe('desktop (1440×900)', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('laptop guide recommended; both cards side by side in the left column, form on the right', async ({ page }) => {
    const net = await open(page);
    await expect(card(page, 'laptop')).toHaveClass(/\brec\b/);
    await expect(card(page, 'phone')).not.toHaveClass(/\brec\b/);
    const p = (await card(page, 'phone').boundingBox())!;
    const l = (await card(page, 'laptop').boundingBox())!;
    expect(Math.abs(p.y - l.y), 'cards share a row').toBeLessThan(4);
    expect(p.x + p.width).toBeLessThanOrEqual(l.x + 1);
    const t = (await page.locator('#keysTutorial').boundingBox())!;
    const f = (await page.locator('#keysForm').boundingBox())!;
    expect(t.x + t.width, 'tutorial stays left of the key form').toBeLessThanOrEqual(f.x + 1);
    expect(net.youtube).toEqual([]);
    expect(net.errors).toEqual([]);
  });
});
