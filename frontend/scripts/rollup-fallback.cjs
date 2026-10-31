// Some older x86 CPUs (no AVX) crash Rollup's native binary with "Illegal instruction".
// If that happens, replace node_modules/rollup with the official @rollup/wasm-node build (same API).
// On machines where the native binary works, this script does nothing.
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const probe = spawnSync(process.execPath, ["-e", "require('rollup').rollup"], { cwd: __dirname + "/.." });
if (probe.status === 0) process.exit(0);
const wasm = path.join(__dirname, "..", "node_modules", "@rollup", "wasm-node");
const target = path.join(__dirname, "..", "node_modules", "rollup");
if (!fs.existsSync(wasm)) {
  console.warn("[rollup-fallback] native rollup failed and @rollup/wasm-node is not installed");
  process.exit(0);
}
fs.rmSync(target, { recursive: true, force: true });
fs.cpSync(wasm, target, { recursive: true });
console.log("[rollup-fallback] native rollup unusable on this CPU - using @rollup/wasm-node instead");
