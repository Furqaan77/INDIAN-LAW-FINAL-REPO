// Renders the animated scenes.
//   · build/anim/<id>/NNNN.jpg — every frame of the scene's entrance animation at 30 fps
//     (each animation is paused and seeked to an exact time, so frames are deterministic)
//   · build/slides/<id>.png    — the settled final frame, held for the rest of the scene
//   · build/anim/manifest.json — frame counts per scene
// Then a geometric layout check on every settled slide:
//   · content clipped by the frame · a heading overlapped by a screenshot
//   · any content inside the avatar circle for that slide's avatar position
// Usage: node shoot_slides.mjs [slideId ...]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const HERE = "/Users/furqaanahmed/LAW LLM/Ai Law video/build";
const SLIDES = path.join(HERE, "slides");
const ANIM = path.join(HERE, "anim");
const FPS = 30;
fs.mkdirSync(SLIDES, { recursive: true });
fs.mkdirSync(ANIM, { recursive: true });

const timeline = JSON.parse(fs.readFileSync(path.join(HERE, "timeline.json"), "utf8"));
const avatarFor = {}, segFor = {};
for (const s of timeline.scenes) {
  if (!(s.id in avatarFor)) avatarFor[s.id] = timeline.avatar_states[s.avatar];
  if (!(s.id in segFor)) segFor[s.id] = s.dur + 0.5;
}
const RING_PAD = 26;
const only = process.argv.slice(2);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto("file://" + path.join(HERE, "slides.html"), { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => window.__ready === true);
await page.waitForTimeout(500);

const ids = (await page.$$eval(".slide", (els) => els.map((e) => e.id))).filter((id) => !only.length || only.includes(id));
const manifestPath = path.join(ANIM, "manifest.json");
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : {};
const problems = [];
let totalFrames = 0;
const started = Date.now();

for (const id of ids) {
  // show only this slide, pinned at the viewport origin, so a viewport screenshot is exactly the frame
  await page.evaluate((id) => {
    for (const s of window.__slides) s.style.display = s.id === id ? "flex" : "none";
    window.scrollTo(0, 0);
  }, id);
  const seg = segFor[id] ?? 8;
  const end = Math.min(await page.evaluate((id) => window.introEnd(id), id), seg);
  const n = Math.max(1, Math.ceil(end * FPS) + 1);
  const dir = path.join(ANIM, id);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  for (let f = 0; f < n; f++) {
    await page.evaluate(([id, t]) => window.seek(id, t), [id, f / FPS]);
    await page.screenshot({ path: path.join(dir, String(f).padStart(4, "0") + ".jpg"), type: "jpeg", quality: 92 });
  }
  totalFrames += n;
  // settled final frame
  await page.evaluate((id) => window.seek(id, 9999), id);
  await page.screenshot({ path: path.join(SLIDES, `${id}.png`) });
  manifest[id] = { frames: n, fps: FPS, seconds: +(n / FPS).toFixed(3) };

  // layout check on the settled frame
  const found = await page.evaluate(
    ({ id, av, RING_PAD }) => {
      const out = [];
      const slide = document.getElementById(id);
      const o = slide.getBoundingClientRect();
      const rel = (r) => ({ left: r.left - o.left, right: r.right - o.left, top: r.top - o.top, bottom: r.bottom - o.top });
      const hit = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      if (slide.scrollHeight > slide.clientHeight + 2 || slide.scrollWidth > slide.clientWidth + 2) out.push(`${id}: content clipped by the frame`);
      const heads = [...slide.querySelectorAll("h1,h2")].map((e) => rel(e.getBoundingClientRect()));
      for (const s of slide.querySelectorAll(".shot")) {
        const r = rel(s.getBoundingClientRect());
        if (heads.some((h) => hit(h, r))) out.push(`${id}: screenshot overlaps the heading`);
        if (r.bottom > 1081 || r.right > 1921 || r.top < -1) out.push(`${id}: screenshot runs off the frame`);
      }
      if (!av) return out;
      const cx = av.x + av.size / 2, cy = av.y + av.size / 2, rad = av.size / 2 + RING_PAD - 4;
      const CONTENT = "h1,h2,.eyebrow,.sub,.shot,.node,.stat,.bar-row,.st,.chip,.col,.matchbox,ul.big li,.mono-note";
      for (const el of slide.querySelectorAll(CONTENT)) {
        const isText = ["H1", "H2", "LI"].includes(el.tagName) || /\b(eyebrow|sub|mono-note)\b/.test(el.className);
        let rects;
        if (isText) { const rg = document.createRange(); rg.selectNodeContents(el); rects = [...rg.getClientRects()]; }
        else rects = [el.getBoundingClientRect()];
        const collides = rects.some((rr) => {
          const r = rel(rr);
          if (r.right - r.left < 2 || r.bottom - r.top < 2) return false;
          const nx = Math.max(r.left, Math.min(cx, r.right)), ny = Math.max(r.top, Math.min(cy, r.bottom));
          return (nx - cx) ** 2 + (ny - cy) ** 2 < rad * rad;
        });
        if (collides) out.push(`${id}: ${String(el.className || el.tagName).split(" ")[0]} "${(el.innerText || "").replace(/\s+/g, " ").slice(0, 40)}" under the avatar`);
      }
      return out;
    },
    { id, av: avatarFor[id], RING_PAD },
  );
  problems.push(...found);
  process.stdout.write(`  ${id.padEnd(22)} ${String(n).padStart(4)} frames\n`);
}
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 1));
await browser.close();
console.log(`rendered ${ids.length} scenes, ${totalFrames} animation frames in ${((Date.now() - started) / 1000).toFixed(0)}s`);
if (problems.length) {
  console.log(`LAYOUT PROBLEMS (${problems.length}):`);
  for (const p of [...new Set(problems)]) console.log("  " + p);
} else console.log("layout check: no clipping, no heading/screenshot overlap, nothing under the avatar");
