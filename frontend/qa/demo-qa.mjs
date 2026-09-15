// Browser-level demo check for IndianLawGPT. Drives the real UI (no mocks) and asserts on page content.
// Flow: choose all three answer engines in the question box → ask → three side-by-side answers from the same
// evidence → evidence drawer → source reader → narrow to two engines → one engine → old/new-law map.
// Prerequisites: API :8010, LoRA service :8095, Ollama, frontend dev server.
// Usage: node qa/demo-qa.mjs [baseUrl]      (default http://localhost:5174 — Vite may listen on IPv6 only, so not 127.0.0.1)
// Needs the `playwright` package (not a frontend dependency): e.g. run it from a folder where `npm i playwright` was done.
// Screenshots are saved to qa/shots/demo-*.png for manual review.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:5174";
const OUT = new URL("./shots/", import.meta.url).pathname;
fs.mkdirSync(OUT, { recursive: true });
const QUESTION = "What is the limitation period for filing a complaint under Section 138 of the Negotiable Instruments Act?";
const ALL_ANSWERS_TIMEOUT = 420_000;

const failures = [];
const passes = [];
const expect = (condition, label) => (condition ? passes : failures).push(label);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => message.type() === "error" && errors.push(message.text()));

const text = async (locator) => ((await locator.count()) ? (await locator.first().innerText()).trim() : "");
const engineButton = (scope, name) => scope.locator("[role='group'][aria-label='Answer engines'] button", { hasText: name });

try {
  // 1. Question box: engine toggles, choose all three, ask
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  expect(!(await page.locator("nav a", { hasText: "Demo" }).count()), "home: no separate Demo page link");
  const form = page.locator("form").first();
  for (const name of ["Claude API", "Plain Qwen", "LoRA Qwen"]) {
    expect((await engineButton(form, name).count()) === 1, `question box: ${name} button present`);
  }
  expect((await text(engineButton(form, "LoRA Qwen"))).includes("EXPERIMENTAL"), "question box: LoRA marked EXPERIMENTAL");
  await form.getByRole("button", { name: "All 3" }).click();
  const pressed = await form.locator("[aria-label='Answer engines'] button[aria-pressed='true']").count();
  expect(pressed === 3, `question box: all three engines selected (${pressed})`);
  await form.locator("textarea").fill(QUESTION);
  await form.locator("textarea").press("Enter");
  await page.waitForURL(/\/research\//);
  expect(new URL(page.url()).searchParams.get("engines") === "claude,qwen,lora_qwen", "research URL carries the three engines");

  // 2. Three columns answer from the same evidence
  await page.waitForFunction(() => document.querySelectorAll("article[data-engine]").length === 3, null, { timeout: 30_000 });
  expect(true, "research: three side-by-side engine columns");
  await page.screenshot({ path: `${OUT}demo-compare-running.png` });
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll("article[data-engine]")].every(
        (article) => !/ANSWERING|QUEUED/.test(article.querySelector("header")?.textContent ?? ""),
      ),
    null,
    { timeout: ALL_ANSWERS_TIMEOUT },
  );
  for (const [engine, subtitle] of [
    ["claude", "Claude · RAG"],
    ["qwen", "Qwen3-1.7B · Base · RAG"],
    ["lora_qwen", "Qwen3-1.7B · LoRA · RAG · Experimental"],
  ]) {
    const column = page.locator(`article[data-engine='${engine}']`);
    expect(!(await column.locator("[role='alert']").count()), `${engine}: answered without error`);
    expect((await text(column)).includes(subtitle), `${engine}: identifies its model (${subtitle})`);
    expect((await column.locator("section[aria-label='Citation verification']").count()) === 1, `${engine}: citation verification shown`);
  }
  expect((await text(page.locator("article[data-engine='lora_qwen'] header"))).includes("EXPERIMENTAL"), "lora_qwen: EXPERIMENTAL tag in column");
  const comparison = await text(page.locator("section[aria-label='Engine comparison']"));
  expect(/Identical frozen evidence for every engine \(ev-[0-9a-f]{16}\)/.test(comparison), "comparison: identical frozen evidence confirmed");
  const flow = await text(page.locator("ol[aria-label='How this answer is produced']"));
  expect(/evidence sources/.test(flow) && /ev-[0-9a-f]{16}/.test(flow), "flow strip: frozen evidence id and source count");
  await page.screenshot({ path: `${OUT}demo-compare-done.png`, fullPage: true });

  // 3. Evidence drawer → source reader
  await page.locator("article[data-engine='claude'] button", { hasText: "Evidence" }).click();
  const drawer = page.getByRole("dialog", { name: "Evidence" });
  await drawer.waitFor({ timeout: 10_000 });
  expect((await text(drawer)).includes("Evidence as cited by Claude API"), "evidence drawer opens for the chosen engine");
  const researchUrl = page.url();
  await drawer.locator("a", { hasText: "Open source" }).first().click();
  await page.waitForURL(/\/source\//);
  await page.waitForSelector("mark", { timeout: 30_000 });
  expect((await page.locator("mark").count()) > 0, "source reader: cited passage highlighted");
  await page.screenshot({ path: `${OUT}demo-source.png` });

  // 4. Narrow to two engines, then one
  await page.goto(researchUrl, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelectorAll("article[data-engine]").length === 3, null, { timeout: 30_000 });
  await engineButton(page.locator("section[aria-label='Answer engines']"), "LoRA Qwen").click();
  await page.waitForFunction(() => document.querySelectorAll("article[data-engine]").length === 2, null, { timeout: 10_000 });
  expect(new URL(page.url()).searchParams.get("engines") === "claude,qwen", "deselecting LoRA leaves two columns");
  await engineButton(page.locator("section[aria-label='Answer engines']"), "Plain Qwen").click();
  await page.waitForSelector("aside[aria-label='Evidence'] article", { timeout: 10_000 });
  expect(!(await page.locator("article[data-engine]").count()) && (await text(page.locator("body"))).includes("Claude · RAG"), "one engine: single answer with evidence rail");
  await page.screenshot({ path: `${OUT}demo-single.png`, fullPage: true });

  // 5. Old → new law map
  await page.goto(`${BASE}/compare?act=ipc&section=420`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => /BNS|Bharatiya Nyaya/.test(document.body.innerText), null, { timeout: 30_000 });
  expect(/BNS|Bharatiya Nyaya/.test(await text(page.locator("body"))), "law map: IPC 420 shows its BNS counterpart");
} catch (error) {
  failures.push(`exception: ${error.message.split("\n")[0]}`);
} finally {
  await browser.close();
}

const relevantErrors = errors.filter((message) => !/favicon|DevTools/.test(message));
if (relevantErrors.length) failures.push(`browser errors: ${relevantErrors.slice(0, 5).join(" | ")}`);
console.log(passes.map((p) => `PASS  ${p}`).join("\n"));
console.log(failures.length ? failures.map((f) => `FAIL  ${f}`).join("\n") : "\nALL UI DEMO CHECKS PASSED");
process.exit(failures.length ? 1 : 0);
