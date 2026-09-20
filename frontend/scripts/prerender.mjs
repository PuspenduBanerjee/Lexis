// Runs after `vite build` (see package.json's "build" script). Vite's client
// build already produced dist/index.html + dist/assets/*; this step renders
// the public, auth-free pages (HomePage, PrivacyPolicyPage, TermsOfServicePage
// - see scripts/ssr-entry.tsx) to static markup and writes it straight into
// the HTML each route serves, so a client that never executes JavaScript
// (e.g. Google's OAuth consent screen homepage/policy verifier) still sees
// real content instead of the bare `<div id="root"></div>` shell.
//
// The client bundle still loads and calls createRoot(...).render(...) on top
// (see main.tsx) for full interactivity - this only changes what the initial
// HTML response contains, not how the app runs once JS is loaded.
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const frontendDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const distDir = path.join(frontendDir, "dist");
const ssrOutDir = path.join(frontendDir, "node_modules/.tmp/ssr-prerender");

async function buildSsrBundle() {
  await build({
    root: frontendDir,
    configFile: path.join(frontendDir, "vite.config.ts"),
    build: {
      ssr: path.join(frontendDir, "scripts/ssr-entry.tsx"),
      outDir: path.relative(frontendDir, ssrOutDir),
      emptyOutDir: true,
      write: true,
      minify: false,
      rollupOptions: { output: { entryFileNames: "ssr-entry.mjs" } },
    },
    logLevel: "warn",
  });
  return path.join(ssrOutDir, "ssr-entry.mjs");
}

function injectIntoTemplate(template, { title, bodyHtml }) {
  let html = template.replace(
    /<title>.*?<\/title>/,
    `<title>${title}</title>`,
  );
  html = html.replace(
    '<div id="root"></div>',
    `<div id="root">${bodyHtml}</div>`,
  );
  if (!html.includes(bodyHtml)) {
    throw new Error("prerender: could not find <div id=\"root\"></div> to inject into dist/index.html");
  }
  return html;
}

async function main() {
  const template = await readFile(path.join(distDir, "index.html"), "utf8");

  const ssrEntryPath = await buildSsrBundle();
  const { ROUTES, renderRoute } = await import(pathToFileURL(ssrEntryPath).href);

  for (const routePath of Object.keys(ROUTES)) {
    const { title } = ROUTES[routePath];
    const bodyHtml = renderRoute(routePath);
    const html = injectIntoTemplate(template, { title, bodyHtml });

    const outFile =
      routePath === "/"
        ? path.join(distDir, "index.html")
        : path.join(distDir, routePath.replace(/^\//, ""), "index.html");
    await mkdir(path.dirname(outFile), { recursive: true });
    await writeFile(outFile, html, "utf8");
    console.log(`prerendered ${routePath} -> ${path.relative(frontendDir, outFile)}`);
  }

  await rm(ssrOutDir, { recursive: true, force: true });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
