/**
 * WCAG contrast audit for all themes in src/styles/themes/.
 * Parses oklch() tokens, converts to relative luminance, and reports
 * foreground/background pair ratios for both light and dark blocks.
 *
 * Run: bun scripts/theme-contrast-audit.mjs
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const THEMES_DIR = fileURLToPath(new URL('../src/styles/themes/', import.meta.url));

// oklch(L C H) -> OKLab -> linear sRGB -> relative luminance
function oklchToLuminance(l, c, h) {
  const hr = (h * Math.PI) / 180;
  const a = c * Math.cos(hr);
  const b = c * Math.sin(hr);
  const L = l;
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l3 = l_ ** 3, m3 = m_ ** 3, s3 = s_ ** 3;
  const r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;
  const lum = (x) => Math.max(0, x); // clamp gamut overflows
  return 0.2126 * lum(r) + 0.7152 * lum(g) + 0.0722 * lum(bl);
}

function contrast(l1, l2) {
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

function parseBlocks(css) {
  // Returns [{selector, tokens: {name: {l,c,h}}}]
  const blocks = [];
  const re = /([^{}]+)\{([^}]+)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const tokens = {};
    const tok = /--([\w-]+):\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/g;
    let t;
    while ((t = tok.exec(m[2]))) {
      tokens[t[1]] = { l: +t[2], c: +t[3], h: +t[4] };
    }
    if (Object.keys(tokens).length) blocks.push({ selector: m[1].trim(), tokens });
  }
  return blocks;
}

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

let failures = 0;
for (const file of readdirSync(THEMES_DIR).filter((f) => f.endsWith('.css'))) {
  const css = readFileSync(join(THEMES_DIR, file), 'utf8');
  for (const block of parseBlocks(css)) {
    const mode = block.selector.includes('dark') ? 'dark' : 'light';
    for (const [fg, bg, min] of PAIRS) {
      const F = block.tokens[fg];
      const B = block.tokens[bg];
      if (!F || !B) continue;
      const ratio = contrast(oklchToLuminance(F.l, F.c, F.h), oklchToLuminance(B.l, B.c, B.h));
      if (ratio < min) {
        failures++;
        console.log(`FAIL ${file} [${mode}] ${fg}/${bg}: ${ratio.toFixed(2)} < ${min}`);
      }
    }
  }
}
console.log(failures === 0 ? 'All theme contrast pairs pass WCAG AA (4.5:1).' : `${failures} failing pairs`);
process.exit(failures ? 1 : 0);
