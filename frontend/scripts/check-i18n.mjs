// Verifies messages/ar.json and messages/en.json have identical keys, and that every
// literal t("key") used in the source exists. Run: npm run i18n:check
import fs from "node:fs";
import path from "node:path";

const flat = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? flat(v, p + k + ".") : [p + k]));
const ar = JSON.parse(fs.readFileSync("messages/ar.json", "utf8"));
const en = JSON.parse(fs.readFileSync("messages/en.json", "utf8"));
const A = new Set(flat(ar));
const E = new Set(flat(en));
let bad = 0;
for (const k of A) if (!E.has(k)) (console.error("missing in en:", k), bad++);
for (const k of E) if (!A.has(k)) (console.error("missing in ar:", k), bad++);

const files = [];
const walk = (d) => {
  for (const f of fs.readdirSync(d, { withFileTypes: true })) {
    if (["node_modules", ".next", ".screens", "mock", "scripts"].includes(f.name)) continue;
    const p = path.join(d, f.name);
    if (f.isDirectory()) walk(p);
    else if (/\.tsx?$/.test(f.name)) files.push(p);
  }
};
walk(".");
const used = new Set();
for (const f of files) {
  const src = fs.readFileSync(f, "utf8");
  const vars = {};
  for (const m of src.matchAll(/const\s+(\w+)\s*=\s*(?:await\s+)?(?:useTranslations|getTranslations)\(\s*["']([\w.]+)["']\s*\)/g)) (vars[m[1]] ||= []).push(m[2]);
  for (const [v, nss] of Object.entries(vars)) {
    const re = new RegExp("(?<![\\w.])" + v + "\\(\\s*([\"'`])([^\"'`]+?)\\1", "g");
    for (const m of src.matchAll(re)) {
      const key = m[2];
      if (key.includes("${")) {
        const prefix = key.split("${")[0];
        if (!nss.some((ns) => [...A].some((k) => k.startsWith(ns + "." + prefix)))) (console.error(`${f}: no keys with prefix ${prefix} in ${nss}`), bad++);
      } else {
        const hit = nss.find((ns) => A.has(ns + "." + key));
        if (hit) used.add(hit + "." + key);
        else (console.error(`${f}: missing key ${nss.join("|")}.${key}`), bad++);
      }
    }
  }
}
console.log(`ar keys: ${A.size}, en keys: ${E.size}, literal keys used: ${used.size}`);
process.exit(bad ? 1 : 0);
