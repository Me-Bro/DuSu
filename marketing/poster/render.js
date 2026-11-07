// Renders poster.built.html in three variants:
//   dark          -> out/DuSu-poster-A4.pdf (216x303 mm, 3 mm bleed) + out/DuSu-poster-A4.png (300 dpi) + out/DuSu-poster-share.png (1079 px, for screens)
//   print-colour  -> out/DuSu-poster-A4-print-colour.pdf (210x297 mm, white paper, ink-saving) + .png (200 dpi)
//   print-bw      -> out/DuSu-poster-A4-print-bw.pdf     (210x297 mm, black only)             + .png (200 dpi)
// VARIANT=print (default) renders the two printer versions, all = all three, or one name; GUIDES=1 writes out/debug-guides-<name>.png (safe-area line) instead of the final files.
// It FAILS if a font did not load, the headline wraps, or any content leaves the safe area.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const DIR = __dirname;
const OUT = path.join(DIR, "out");
const MM = 96 / 25.4; // CSS px per mm
const guides = process.env.GUIDES === "1";

const VARIANTS = {
  "dark":         { theme: "",           w: 216, h: 303, dpi: 300, pdf: "DuSu-poster-A4.pdf",              png: "DuSu-poster-A4.png",              css: true  },
  "print-colour": { theme: "print",      w: 210, h: 297, dpi: 200, pdf: "DuSu-poster-A4-print-colour.pdf", png: "DuSu-poster-A4-print-colour.png", css: false },
  "print-bw":     { theme: "print mono", w: 210, h: 297, dpi: 200, pdf: "DuSu-poster-A4-print-bw.pdf",     png: "DuSu-poster-A4-print-bw.png",     css: false },
};

async function open(browser, v, scale) {
  const page = await browser.newPage({
    viewport: { width: Math.ceil(v.w * MM), height: Math.ceil(v.h * MM) },
    deviceScaleFactor: scale,
  });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("requestfailed", (r) => errors.push("request failed: " + r.url()));
  const q = [];
  if (v.theme) q.push("theme=" + encodeURIComponent(v.theme));
  if (guides) q.push("guides");
  await page.goto("file://" + path.join(DIR, "poster.built.html") + (q.length ? "?" + q.join("&") : ""));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  return { page, errors };
}

async function checks(page, v, errors) {
  const report = await page.evaluate(({ MM, margin }) => {
    const faces = [...document.fonts].map((f) => `${f.family} ${f.weight}: ${f.status}`);
    const safe = document.querySelector(".safe").getBoundingClientRect();
    const pg = document.querySelector(".page").getBoundingClientRect();
    const outside = [];
    for (const el of document.querySelectorAll(".safe *")) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const e = 0.6;
      if (r.left < safe.left - e || r.right > safe.right + e || r.top < safe.top - e || r.bottom > safe.bottom + e) {
        outside.push(`${el.tagName.toLowerCase()}.${el.className || ""} "${(el.textContent || "").trim().slice(0, 30)}" ` +
          `L${((r.left - pg.left) / MM).toFixed(1)} R${((r.right - pg.left) / MM).toFixed(1)} T${((r.top - pg.top) / MM).toFixed(1)} B${((r.bottom - pg.top) / MM).toFixed(1)} mm`);
      }
    }
    const sf = document.querySelector(".safe");
    const foot = document.querySelector(".foot").getBoundingClientRect();
    const qa = document.querySelector(".qa").getBoundingClientRect();
    const h1 = document.querySelector("h1");
    return {
      faces, outside,
      pageMm: [+(pg.width / MM).toFixed(2), +(pg.height / MM).toFixed(2)],
      safeMarginMm: +((safe.left - pg.left) / MM).toFixed(1),
      gapQaToFootMm: +((foot.top - qa.bottom) / MM).toFixed(2),
      overflowY: sf.scrollHeight - sf.clientHeight,
      h1Lines: Math.round(h1.getBoundingClientRect().height / parseFloat(getComputedStyle(h1).lineHeight)),
      themeClass: document.documentElement.className,
    };
  }, { MM });
  const bad = [];
  if (report.faces.some((f) => f.endsWith("error"))) bad.push("a font failed to load");
  if (!report.faces.includes("Baloo2 800: loaded") || !report.faces.includes("Mukta 500: loaded")) bad.push("the main fonts are not loaded");
  if (report.outside.length) bad.push("content outside the safe area: " + report.outside.slice(0, 3).join(" | "));
  if (report.overflowY > 0) bad.push("safe area overflows by " + report.overflowY + " px");
  if (report.gapQaToFootMm < 1.5) bad.push("Q&A and footer are too close / overlapping (" + report.gapQaToFootMm + " mm)");
  if (report.h1Lines !== 1) bad.push("headline wraps onto " + report.h1Lines + " lines");
  if (Math.abs(report.pageMm[0] - v.w) > 0.2 || Math.abs(report.pageMm[1] - v.h) > 0.2) bad.push("page is " + report.pageMm.join(" x ") + " mm, expected " + v.w + " x " + v.h);
  if (v.theme && !v.theme.split(" ").every((c) => report.themeClass.split(" ").includes(c))) bad.push("theme class not applied: " + report.themeClass);
  if (!v.theme && report.themeClass) bad.push("unexpected theme class on the dark poster: " + report.themeClass);
  if (!v.css && report.safeMarginMm < 12) bad.push("print margin " + report.safeMarginMm + " mm < 12 mm");
  if (errors.length) bad.push("page errors: " + errors.join(" | "));
  return { report, bad };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  // default = the two printer versions; VARIANT=dark builds the dark print-shop / screen version, VARIANT=all builds all three
  const want = process.env.VARIANT || "print";
  const names = want === "print" ? ["print-colour", "print-bw"] : want === "all" ? Object.keys(VARIANTS) : [want];
  const browser = await chromium.launch();
  let failed = false;
  for (const name of names) {
    const v = VARIANTS[name];
    if (!v) { console.error("unknown variant " + name); process.exit(2); }
    const { page, errors } = await open(browser, v, v.dpi / 96);
    const { report, bad } = await checks(page, v, errors);
    console.log(`== ${name}: page ${report.pageMm.join(" x ")} mm, margin ${report.safeMarginMm} mm, gap Q&A->footer ${report.gapQaToFootMm} mm, headline lines ${report.h1Lines}, fonts ${report.faces.filter((f) => f.endsWith("loaded")).length} loaded`);
    if (bad.length) { console.error(`CHECK FAILED (${name}): ` + bad.join("; ")); failed = true; }
    if (guides) {
      await page.locator(".page").screenshot({ path: path.join(OUT, `debug-guides-${name}.png`) });
    } else if (!bad.length) {
      if (v.css) {
        await page.pdf({ path: path.join(OUT, v.pdf), width: v.w + "mm", height: v.h + "mm", printBackground: true, preferCSSPageSize: true });
      } else {
        // the page's own @page rule says 216 x 303; the printer variants must be exactly A4, so the size comes from here
        await page.pdf({ path: path.join(OUT, v.pdf), width: v.w + "mm", height: v.h + "mm", printBackground: true, preferCSSPageSize: false, margin: { top: "0", right: "0", bottom: "0", left: "0" } });
      }
      await page.locator(".page").screenshot({ path: path.join(OUT, v.png) });
      if (name === "dark") {
        // trimmed copy for screens: cut the 3 mm bleed, 1080 px wide
        const w = 210 * MM;
        const o2 = await open(browser, v, 1080 / w);
        await o2.page.screenshot({ path: path.join(OUT, "DuSu-poster-share.png"), clip: { x: 3 * MM, y: 3 * MM, width: w, height: 297 * MM } });
        await o2.page.close();
      }
    }
    await page.close();
  }
  await browser.close();
  if (failed) process.exit(2);
  console.log("render ok");
})();
