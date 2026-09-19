# Themes

All themes live in `src/styles/themes/*.css` and are OKLCH token sets consumed
through `data-theme` + `.dark`. Each file carries a header comment with its
source; this file is the catalog.

| Theme | Source | Adaptation |
|---|---|---|
| teamspace | In-house brand theme | Original palette authored for Teamspace |
| claude | tweakcn.com (Claude preset) | OKLCH port; `primary-foreground`/`muted-foreground` lightness raised for WCAG AA |
| discord | tweakcn.com (Discord preset) | Brand-blurple accent; muted/accent foregrounds contrast-fixed |
| supabase | tweakcn.com (Supabase preset) | Brand-green accent; OKLCH port |
| vercel | tweakcn.com (Vercel preset) | Monochrome geometric palette; destructive-foreground contrast-fixed |
| mono | tweakcn.com (Mono preset) | Neutral grayscale, single accent |
| notebook | tweakcn.com (Notebook preset) | Paper-like warm neutrals; secondary/destructive foregrounds fixed |
| light-green | tweakcn.com (Light Green preset) | Fresh green light theme; destructive-foreground fixed |
| zen | tweakcn.com (Zen preset) | Warm minimal palette; destructive-foreground fixed |
| astro-vista | tweakcn.com (Astro Vista preset) | Cool blue-grey palette; primary/muted/destructive foregrounds fixed |
| whatsapp | tweakcn.com (WhatsApp preset) | Brand-green chat palette; muted/accent/destructive foregrounds fixed |

## Contrast policy

`bun scripts/theme-contrast-audit.mjs` checks every foreground/background
token pair (background, card, popover, primary, secondary, muted, accent,
destructive) in light and dark blocks against WCAG AA 4.5:1. The audit must
pass before a theme change ships.

## Semantic accents

A small allow-list of hardcoded Tailwind palette utilities is permitted for
**semantic status only** (never for surfaces or brand color):

- File-type icons in `file-preview.tsx` (emerald/red/blue/green/yellow/amber)
- Status badges in `project-list.tsx`, `deadlines-page.tsx` (emerald/amber/blue)
- Unread dot `bg-sky-500` in notification components
- `badge.tsx` warning variant (amber)

These communicate state, not theme, and are consistent across all 11 themes.

## Allow-listed hex literals

- `layout.tsx` / `theme-mode-toggle.tsx`: `theme-color` meta values (browser
  chrome API requires hex)
- `global-error.tsx`: last-resort inline styles when CSS may not load
- `chart.tsx`: recharts internal stroke-attribute selectors (`#ccc`/`#fff`
  are recharts' own defaults being overridden to tokens)
