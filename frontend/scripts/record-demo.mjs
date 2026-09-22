// Records short GIF walkthroughs of the web UI for docs/web-ui-walkthrough.md:
// the Design tab (model editor), the Transpile tab (semantic model conversion),
// and the Test Metrics tab (semantic query execution).
//
// Requires the dev servers running first (LEXIS_DEV_SETUP_DEMO=1 so the demo
// datasets/connections exist - see scripts/demo-dev.sh) and drives the
// `retail_analytics` sample model that's seeded on first run.
//
// Usage: npm run record-demo   (override the frontend URL with LEXIS_WEB_URL)
import { chromium } from "@playwright/test";
import { mkdtemp, mkdir, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
const BASE_URL = process.env.LEXIS_WEB_URL ?? "http://localhost:5173";
const VIEWPORT = { width: 1280, height: 860 };
const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "media");

async function recordClip(name, steps) {
  const videoDir = await mkdtemp(path.join(tmpdir(), `lexis-demo-${name}-`));
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: VIEWPORT, recordVideo: { dir: videoDir, size: VIEWPORT } });
  const page = await context.newPage();
  try {
    await steps(page);
  } finally {
    await context.close();
    await browser.close();
  }
  const [webm] = (await readdir(videoDir)).filter((f) => f.endsWith(".webm"));
  const webmPath = path.join(videoDir, webm);
  const gifPath = path.join(OUT_DIR, `${name}.gif`);
  const palettePath = path.join(videoDir, "palette.png");

  // Two-pass palette approach for a much smaller/cleaner GIF than a naive
  // single-pass conversion; 8fps/880px keeps the docs page load light.
  await run("ffmpeg", ["-y", "-i", webmPath, "-vf", "fps=8,scale=880:-1:flags=lanczos,palettegen", palettePath]);
  await run("ffmpeg", [
    "-y",
    "-i", webmPath,
    "-i", palettePath,
    "-lavfi", "fps=8,scale=880:-1:flags=lanczos[x];[x][1:v]paletteuse",
    gifPath,
  ]);
  await rm(videoDir, { recursive: true, force: true });
  console.log(`wrote ${gifPath}`);
}

const pause = (page, ms) => page.waitForTimeout(ms);
const tabs = (page) => page.locator(".tabs");
const primaryButton = (page, text) => page.locator("button.primary", { hasText: text });
// Every label here wraps its <select> (`<label>Metric <select>…</select></label>`), which
// makes the select's *computed* accessible name "Metric" + every option's text concatenated
// - so getByLabel can't target it reliably. Scoping by the row's action button instead.
const rowWithButton = (page, buttonText) =>
  page.locator(".row").filter({ has: page.locator("button.primary", { hasText: buttonText }) });

async function openRetailAnalytics(page) {
  await page.goto(`${BASE_URL}/models`);
  await page.waitForSelector("table.data-table");
  await pause(page, 500);
  await page.getByRole("link", { name: "retail_analytics" }).click();
  await page.waitForSelector("h2");
  await pause(page, 400);
}

async function recordModelEditor() {
  await recordClip("model-editor-design", async (page) => {
    await openRetailAnalytics(page);
    await tabs(page).getByRole("button", { name: "Design", exact: true }).click();
    await page.waitForSelector(".react-flow");
    await pause(page, 1800); // let dagre finish laying out the graph

    await page.locator(".react-flow").getByText("total_revenue", { exact: true }).click();
    await pause(page, 1200); // metric panel opens with its expression + description

    await page.mouse.wheel(0, 400); // scroll the panel into view
    await pause(page, 1500); // time-series preview auto-runs at "year" grain

    await page.locator("table tbody tr").first().click();
    await pause(page, 1500); // drilled into "quarter"

    await page.getByRole("button", { name: "Roll up" }).click();
    await pause(page, 1200); // back to "year"
  });
}

async function recordTranspile() {
  await recordClip("semantic-model-conversion", async (page) => {
    await openRetailAnalytics(page);
    await tabs(page).getByRole("button", { name: "Transpile", exact: true }).click();
    await pause(page, 500);

    // Default target (duckdb SQL) first, for whichever metric is selected.
    await primaryButton(page, "Transpile").click();
    await pause(page, 1200);

    // Switch to a non-SQL semantic layer format to show cross-platform conversion.
    const targetSelect = rowWithButton(page, "Transpile").locator("select").first();
    await targetSelect.selectOption("sml");
    await pause(page, 500);
    await primaryButton(page, "Transpile").click();
    await pause(page, 1500);
    const files = page.locator(".file-tree-file");
    if ((await files.count()) > 1) {
      await files.nth(1).click();
      await pause(page, 1200);
    }

    await targetSelect.selectOption("snowflake_semantic_view");
    await pause(page, 500);
    await primaryButton(page, "Transpile").click();
    await pause(page, 1800);
  });
}

async function recordQueryExecution() {
  await recordClip("semantic-query-execution", async (page) => {
    await openRetailAnalytics(page);
    await tabs(page).getByRole("button", { name: "Test Metrics", exact: true }).click();
    await pause(page, 500);

    await rowWithButton(page, "Run").locator("select").selectOption("total_revenue");
    await page.locator("select[multiple]").selectOption("dim_item.i_category");
    await pause(page, 400);
    await primaryButton(page, "Run").click();
    await pause(page, 1800); // generated SQL + results table

    await page.getByLabel(/Time series/).check();
    await pause(page, 400);
    await primaryButton(page, "Run").click();
    await pause(page, 1500); // year-grain time series

    await page.locator("table tbody tr").first().click();
    await pause(page, 1500); // drilled into quarter
  });
}

await mkdir(OUT_DIR, { recursive: true });
await recordModelEditor();
await recordTranspile();
await recordQueryExecution();
