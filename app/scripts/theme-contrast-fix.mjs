/**
 * Auto-fix WCAG contrast failures found by theme-contrast-audit.mjs.
 * For each failing fg/bg pair, binary-searches a new foreground lightness
 * (chroma/hue preserved) that reaches the target ratio, and rewrites the
 * token in place. Brand hues are untouched; only lightness moves.
 *
 * Run: bun scripts/theme-contrast-fix.mjs
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const THEMES_DIR = fileURLToPath(new URL('../src/styles/themes/', import.meta.url));

function oklchToLuminance(l, c, h) {
  const hr = (h * Math.PI) / 180;
  const a = c * Math.cos(hr);
  const b = c * Math.sin(hr);
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const l3 = l_ ** 3, m3 = m_ ** 3, s3 = s_ ** 3;
  const r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;
  const lum = (x) => Math.max(0, x);
  return 0.2126 * lum(r) + 0.7152 * lum(g) + 0.0722 * lum(bl);
}

const contrast = (l1, l2) => (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);

const PAIRS = [
  ['foreground', 'background', 4.5],
  ['card-foreground', 'card', 4.5],
  ['popover-foreground', 'popover', 4.5],
  ['primary-foreground', 'primary', 4.5],
  ['secondary-foreground', 'secondary', 4.5],
  ['muted-foreground', 'background', 4.5],
  ['accent-foreground', 'accent', 4.5],
  ['destructive-foreground', 'destructive', 4.5]
];

/** Find the L closest to `startL` (searching toward both poles) that passes. */
function solveL(c, h, startL, bgLum, min) {
  for (let d = 0; d <= 100; d++) {
    for (const l of [startL + d / 100, startL - d / 100]) {
      if (l < 0 || l > 1) continue;
      if (contrast(oklchToLuminance(l, c, h), bgLum) >= min + 0.02) return l;
    }
  }
  return startL;
}

let totalFixes = 0;
for (const file of readdirSync(THEMES_DIR).filter((f) => f.endsWith('.css'))) {
  const path = join(THEMES_DIR, file);
  let css = readFileSync(path, 'utf8');
  const blockRe = /([^{}]+)\{([^}]+)\}/g;
  let m;
  // Rebuild block-by-block so edits stay scoped to their own block.
  let out = '';
  let last = 0;
  while ((m = blockRe.exec(css))) {
    let body = m[2];
    const tokens = {};
    const tok = /--([\w-]+):\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/g;
    let t;
    while ((t = tok.exec(body))) tokens[t[1]] = { l: +t[2], c: +t[3], h: +t[4] };
    for (const [fg, bg, min] of PAIRS) {
      const F = tokens[fg];
      const B = tokens[bg];
      if (!F || !B) continue;
      const bgLum = oklchToLuminance(B.l, B.c, B.h);
      if (contrast(oklchToLuminance(F.l, F.c, F.h), bgLum) >= min) continue;
      const newL = solveL(F.c, F.h, F.l, bgLum, min);
      const oldDecl = `--${fg}: oklch(${F.l} ${F.c} ${F.h}`;
      if (!body.includes(oldDecl)) continue;
      body = body.replace(oldDecl, `--${fg}: oklch(${+newL.toFixed(4)} ${F.c} ${F.h}`);
      totalFixes++;
      console.log(`FIX ${file} [${m[1].trim()}] ${fg}: L ${F.l} -> ${+newL.toFixed(4)}`);
    }
    out += css.slice(last, m.index) + m[1] + '{' + body + '}';
    last = m.index + m[0].length;
  }
  out += css.slice(last);
  writeFileSync(path, out);
}
console.log(`${totalFixes} tokens adjusted`);
