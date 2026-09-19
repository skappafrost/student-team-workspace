/**
 * Prepend Zero-Native-Design attribution headers to theme CSS files.
 * Idempotent: skips files that already carry the marker.
 * Run: bun scripts/theme-attribution.mjs
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const THEMES_DIR = fileURLToPath(new URL('../src/styles/themes/', import.meta.url));
const MARKER = 'Design source:';

const SOURCES = {
  'teamspace.css': ['In-house brand theme', 'Original palette authored for Teamspace'],
  'claude.css': ['https://tweakcn.com (Claude preset)', 'OKLCH port; contrast-fixed foregrounds'],
  'discord.css': ['https://tweakcn.com (Discord preset)', 'Brand-blurple accent; contrast-fixed'],
  'supabase.css': ['https://tweakcn.com (Supabase preset)', 'Brand-green accent; OKLCH port'],
  'vercel.css': ['https://tweakcn.com (Vercel preset)', 'Monochrome geometric palette'],
  'mono.css': ['https://tweakcn.com (Mono preset)', 'Neutral grayscale, single accent'],
  'notebook.css': ['https://tweakcn.com (Notebook preset)', 'Paper-like warm neutrals'],
  'light-green.css': ['https://tweakcn.com (Light Green preset)', 'Fresh green light theme'],
  'zen.css': ['https://tweakcn.com (Zen preset)', 'Warm minimal palette'],
  'astro-vista.css': ['https://tweakcn.com (Astro Vista preset)', 'Cool blue-grey palette'],
  'whatsapp.css': ['https://tweakcn.com (WhatsApp preset)', 'Brand-green chat palette']
};

for (const [file, [source, note]] of Object.entries(SOURCES)) {
  const path = join(THEMES_DIR, file);
  const css = readFileSync(path, 'utf8');
  if (css.includes(MARKER)) {
    console.log(`skip ${file} (already attributed)`);
    continue;
  }
  const header = `/**\n * Theme: ${file.replace('.css', '')}\n * ${MARKER} ${source}\n * Adaptation: ${note}. Tokenized via CSS custom properties only —\n * no component-level hardcoded colors. Catalog: design-references/themes.md\n */\n`;
  writeFileSync(path, header + css);
  console.log(`attributed ${file}`);
}
