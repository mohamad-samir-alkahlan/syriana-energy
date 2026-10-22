// `output: "standalone"` does not copy static assets; do it so `npm start` works locally.
import fs from "node:fs";
const out = ".next/standalone";
if (fs.existsSync(out)) {
  fs.cpSync(".next/static", `${out}/.next/static`, { recursive: true });
  if (fs.existsSync("public")) fs.cpSync("public", `${out}/public`, { recursive: true });
}
