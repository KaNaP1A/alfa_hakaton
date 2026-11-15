import { build } from "esbuild";
import { pathToFileURL } from "node:url";
import fs from "node:fs/promises";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const temporary = path.join(root, "node_modules/.cache/design-review");
await fs.mkdir(temporary, { recursive: true });
const bundle = path.join(temporary, "screens.mjs");
await build({
  entryPoints: [path.join(root, "tests/review/screens.jsx")],
  outfile: bundle,
  bundle: true,
  platform: "node",
  format: "esm",
  packages: "external",
  target: "node22",
});
// Keep fixture resolution independent of where esbuild puts the generated module.
let source = await fs.readFile(bundle, "utf8");
source = source.replace(
  "../../../data/synthetic/test/catalog.json",
  pathToFileURL(path.resolve(root, "../data/synthetic/test/catalog.json")).href,
);
await fs.writeFile(bundle, source);
const { screens } = await import(
  pathToFileURL(bundle).href + "?v=" + Date.now()
);
const assets = await fs.readdir(path.join(root, "dist/assets"));
const css = assets.find((x) => x.endsWith(".css"));
for (const [name, markup] of Object.entries(screens)) {
  await fs.writeFile(
    path.join(root, "dist", `review-${name}.html`),
    `<!doctype html><html lang="ru" data-type="software" data-radius="soft" data-buttons="solid"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="page-type" content="software"><meta name="site-kind" content="software"><title>Альфа-Курс — ${name}</title><link rel="stylesheet" href="/taste/motion/motion.css"><link rel="stylesheet" href="/assets/${css}"></head><body>${markup}</body></html>`,
  );
}
console.log("Rendered visual QA screens:", Object.keys(screens).join(", "));
