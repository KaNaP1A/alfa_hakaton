import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, "node_modules/.cache/ui-test/controls.test.mjs");
await fs.mkdir(path.dirname(output), { recursive: true });
await build({
  entryPoints: [path.join(root, "tests/ui.test.jsx")],
  outfile: output,
  bundle: true,
  packages: "external",
  platform: "node",
  format: "esm",
  target: "node22",
});
const result = spawnSync(process.execPath, ["--test", output], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
