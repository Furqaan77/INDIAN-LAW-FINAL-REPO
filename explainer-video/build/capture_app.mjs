// Captures real IndianLawGPT interface screenshots for the explainer video.
// Requires the app running: frontend :5174, API :8010, Ollama, LoRA service :8095.
// Usage: node capture_app.mjs   (run from a folder where `playwright` resolves)
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://localhost:5174";
const OUT = "/Users/furqaanahmed/LAW LLM/Ai Law video/assets/screens/";
fs.mkdirSync(OUT, { recursive: true });

const Q1 = "What is the limitation period for filing a complaint under Section 138 of the Negotiable Instruments Act?";
const Q2 = "What is the punishment for dishonour of a cheque under Section 138 of the Negotiable Instruments Act?";

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2,
  colorScheme: "light",
});
const page = await ctx.newPage();
const shot = async (name, opts = {}) => {
  await page.screenshot({ path: `${OUT}${name}.png`, ...opts });
  console.log("captured", name);
};
const waitAnswer = async (header, timeout = 300000) =>
  page.waitForFunction(
    (h) =>
      document.querySelector("[role='alert']") ||
      (document.querySelector("section[aria-label='Citation verification']") && document.body.innerText.includes(h)),
    header,
    { timeout },
  );

try {
  // 1. Home page — question box with the three engine toggles
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await shot("01_home");
  await page.locator("form").first().scrollIntoViewIfNeeded();
  await shot("02_questionbox", { clip: { x: 0, y: 120, width: 1600, height: 620 } });

  // 2. Single-engine research answer (Claude)
  const form = page.locator("form").first();
  await form.locator("textarea").fill(Q1);
  await form.locator("textarea").press("Enter");
  await page.waitForURL(/\/research\//);
  await page.waitForTimeout(2500);
  await shot("03_progress");
  await waitAnswer("Claude · RAG");
  await page.waitForTimeout(1200);
  await shot("04_answer_full");
  await shot("04b_answer_top", { clip: { x: 0, y: 60, width: 1600, height: 760 } });

  // 3. Citation verification panel
  const verif = page.locator("section[aria-label='Citation verification']");
  await verif.scrollIntoViewIfNeeded();
  await page.waitForTimeout(600);
  await shot("05_citation_verification");
  const box = await verif.boundingBox();
  if (box) await shot("05b_citation_zoom", { clip: { x: Math.max(0, box.x - 30), y: Math.max(0, box.y - 30), width: Math.min(1600, box.width + 60), height: Math.min(1000, box.height + 80) } });

  // 4. Evidence rail — all retrieved evidence with retrieval signals
  const rail = page.locator("aside[aria-label='Evidence']");
  if (await rail.count()) {
    await shot("06_evidence_rail", { clip: { x: 1060, y: 60, width: 540, height: 940 } });
    const details = rail.locator("summary", { hasText: "All retrieved evidence" });
    if (await details.count()) {
      await details.first().click();
      await page.waitForTimeout(700);
      await shot("07_retrieved_evidence", { clip: { x: 1060, y: 60, width: 540, height: 940 } });
    }
  }

  // 5. Model details expanded
  const md = page.getByText("Model details").first();
  if (await md.count()) {
    await md.click();
    await page.waitForTimeout(600);
    await md.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await shot("08_model_details");
  }

  // 6. Document reader with highlighted cited passage
  const openSrc = page.locator("aside[aria-label='Evidence'] a", { hasText: "Open source" });
  if (await openSrc.count()) {
    await openSrc.first().click();
    await page.waitForURL(/\/source\//);
    await page.waitForSelector("mark", { timeout: 30000 });
    await page.waitForTimeout(800);
    await shot("09_document_reader");
    const mk = page.locator("mark").first();
    await mk.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await shot("09b_highlight_zoom");
  }

  // 7. Old law -> new law comparison
  await page.goto(`${BASE}/compare?act=ipc&section=420`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => /BNS|Bharatiya Nyaya/.test(document.body.innerText), null, { timeout: 30000 });
  await page.waitForTimeout(1200);
  await shot("10_law_map");

  // 8. Statute search
  await page.goto(`${BASE}/search?q=anticipatory+bail&type=statute`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await shot("11_search");

  // 9. Three engines side by side on identical evidence
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  const form2 = page.locator("form").first();
  await form2.getByRole("button", { name: "All 3" }).click();
  await page.waitForTimeout(400);
  await shot("12_all3_selected", { clip: { x: 0, y: 120, width: 1600, height: 620 } });
  await form2.locator("textarea").fill(Q2);
  await form2.locator("textarea").press("Enter");
  await page.waitForURL(/\/research\//);
  await page.waitForFunction(() => document.querySelectorAll("article[data-engine]").length === 3, null, { timeout: 30000 });
  await page.waitForTimeout(2000);
  await shot("13_three_engines_running");
  await page.waitForFunction(
    () => [...document.querySelectorAll("article[data-engine]")].every((a) => !/ANSWERING|QUEUED/.test(a.querySelector("header")?.textContent ?? "")),
    null,
    { timeout: 420000 },
  );
  await page.waitForTimeout(1500);
  await shot("14_three_engines_done");
  const cmp = page.locator("section[aria-label='Engine comparison']");
  if (await cmp.count()) {
    await cmp.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    const cb = await cmp.boundingBox();
    if (cb) await shot("15_engine_comparison", { clip: { x: Math.max(0, cb.x - 20), y: Math.max(0, cb.y - 40), width: Math.min(1600, cb.width + 40), height: Math.min(1000, cb.height + 90) } });
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await shot("16_three_columns_top", { clip: { x: 0, y: 60, width: 1600, height: 900 } });
} catch (e) {
  console.log("CAPTURE ERROR:", e.message.split("\n")[0]);
} finally {
  await browser.close();
}
console.log("done");
