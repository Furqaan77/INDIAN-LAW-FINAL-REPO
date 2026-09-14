// Visual QA for the IndianLawGPT frontend. Usage: node shoot.mjs [step ...]
// Steps: home research citations source compare search mobile dark errors
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://127.0.0.1:5173";
const here = (p) => new URL(p, import.meta.url).pathname;
const OUT = here("./shots/");
const LAST_URL = here("./last-research-url.txt");
const QUESTION = "Can a cheque bounce complaint proceed if the demand notice was sent late?";

fs.mkdirSync(OUT, { recursive: true });
const requested = process.argv.slice(2);
const want = (name) => requested.length === 0 || requested.includes(name);
const log = [];

const context = await chromium.launchPersistentContext(here("./profile"), {
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",
});
const page = context.pages()[0] ?? (await context.newPage());
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") log.push(`[console.${m.type()}] ${page.url()} :: ${m.text()}`);
});
page.on("pageerror", (e) => log.push(`[pageerror] ${page.url()} :: ${e.message}`));
page.on("requestfailed", (r) => {
  if (!r.url().includes("/api/research")) log.push(`[requestfailed] ${r.url()} :: ${r.failure()?.errorText}`);
});

const shot = async (name, options = {}) => {
  await page.screenshot({ path: `${OUT}${name}.png`, ...options });
  console.log("shot", name);
};

async function step(name, fn) {
  if (!want(name)) return;
  try {
    await fn();
  } catch (error) {
    console.log(`STEP ${name} FAILED: ${error.message.split("\n")[0]}`);
    await shot(`FAILED-${name}`).catch(() => {});
  }
}

const setTheme = async (theme) => {
  await page.evaluate((t) => localStorage.setItem("indianlawgpt.theme", t), theme);
};

await page.goto(BASE + "/");
await setTheme("light");

await step("home", async () => {
  await page.goto(BASE + "/");
  await page.waitForTimeout(1800);
  await shot("01-home");
  await shot("01-home-full", { fullPage: true });
});

await step("research", async () => {
  await page.goto(BASE + "/");
  await page.locator("textarea").first().fill(QUESTION);
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/research\//);
  fs.writeFileSync(LAST_URL, page.url());
  await page.waitForTimeout(2500);
  await shot("02-progress");
  await page.locator(".brief").waitFor({ timeout: 170_000 });
  await page.waitForTimeout(900);
  await shot("03-answer");
  await shot("03-answer-full", { fullPage: true });
});

await step("citations", async () => {
  await page.goto(fs.readFileSync(LAST_URL, "utf8").trim());
  await page.locator(".brief").waitFor({ timeout: 30_000 });
  const markers = page.locator(".brief button[aria-pressed]");
  console.log("citation markers:", await markers.count());
  await markers.first().hover();
  await page.waitForTimeout(600);
  await shot("04-citation-preview");
  await markers.first().click();
  await page.waitForTimeout(800);
  await shot("05-citation-active");
});

await step("source", async () => {
  await page.goto(fs.readFileSync(LAST_URL, "utf8").trim());
  await page.locator(".brief").waitFor({ timeout: 30_000 });
  await page.locator(".brief button[aria-pressed]").first().click();
  await page.locator('article:has(h3 button[aria-pressed="true"])').getByRole("link", { name: "Open source" }).click();
  await page.locator("#document-title").waitFor({ timeout: 20_000 });
  await page.waitForTimeout(1500);
  await shot("06-source");
});

await step("compare", async () => {
  await page.goto(BASE + "/compare?act=ipc&section=420");
  await page.getByText("Old code", { exact: true }).first().waitFor({ timeout: 20_000 });
  await page.waitForTimeout(800);
  await shot("07-compare");
  await page.goto(BASE + "/compare");
  await page.waitForTimeout(900);
  await shot("07b-compare-empty");
});

await step("search", async () => {
  await page.goto(BASE + "/search?" + new URLSearchParams({ q: "anticipatory bail", type: "statute" }));
  await page.locator('[aria-label="Search results"]').waitFor({ timeout: 40_000 });
  await page.waitForTimeout(500);
  await shot("08-search");
});

await step("mobile", async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(BASE + "/");
  await page.waitForTimeout(1500);
  await shot("09-mobile-home");
  if (fs.existsSync(LAST_URL)) {
    await page.goto(fs.readFileSync(LAST_URL, "utf8").trim());
    await page.locator(".brief").waitFor({ timeout: 30_000 });
    await page.waitForTimeout(700);
    await shot("10-mobile-research");
    await page.getByRole("button", { name: /Evidence/ }).last().click();
    await page.waitForTimeout(900);
    await shot("11-mobile-evidence");
    await page.keyboard.press("Escape");
  }
  await page.setViewportSize({ width: 1440, height: 900 });
});

await step("dark", async () => {
  await setTheme("dark");
  await page.goto(BASE + "/");
  await page.waitForTimeout(1500);
  await shot("12-dark-home");
  if (fs.existsSync(LAST_URL)) {
    await page.goto(fs.readFileSync(LAST_URL, "utf8").trim());
    await page.locator(".brief").waitFor({ timeout: 30_000 });
    await page.locator(".brief button[aria-pressed]").first().click().catch(() => {});
    await page.waitForTimeout(900);
    await shot("13-dark-research");
  }
  await setTheme("light");
});

await step("errors", async () => {
  await page.goto(BASE + "/source/STATUTE-does-not-exist-s1");
  await page.waitForTimeout(1500);
  await shot("14-source-404");
  await page.goto(BASE + "/research/unknownid123");
  await page.waitForTimeout(800);
  await shot("15-research-missing");
});

fs.writeFileSync(here("./console.log"), log.join("\n"));
console.log(`console issues: ${log.length}`);
log.slice(0, 25).forEach((line) => console.log(line));
await context.close();
