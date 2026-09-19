# UI Scout Picks — 6 sites, inner pages included

Target app: Next.js 16 + shadcn/ui, `teamspace` theme — near-white bg, orange-red primary
`oklch(0.577 0.245 27.325)`, Plus Jakarta Sans, radius 0.5rem, hairline borders.

## 1. uiverse.io/elements (01, 07, 08, 16, 17)
- Category sidebar w/ icon list (Buttons, Loaders, Inputs, Cards…) → our settings/docs nav.
- Element detail = split preview/code + tabs + Copy/Export (08) → pattern for any future component gallery.
- **COPIED CODE**: `MuhammadHasann/quick-goose-5` — 3D-tilt button. Invisible 6-cell grid overlay drives
  `rotateX/rotateY(±15deg)` toward cursor + hard offset `box-shadow ±2px` + `:active scale(0.95)`.
  Recolor: keep orange bg = `--primary`, shadow `#18181888` → `oklch(0.21 0.02 265 / 0.5)`.
  Fits teamspace accent exactly. Use on primary CTAs (Create workspace, New task).

## 2. swishy.ai (02, 09, 09b)
- Prompt-hero (big input as hero) + template card grid w/ live animated demos.
- Inner = SPA, /templates redirects, /changelog 404 — landing scroll only.
- Steal: animated demo cards (30s counter, stretchy text, timeline) → dashboard empty-states / onboarding.

## 3. designspells.com (03, 10, 10b)
- Floating dark pill nav (rounded-full, Subscribe pill inside) → our topbar could get pill variant.
- Numbered index cards (264/265…) + app label top-right, tinted card bg, media flush top →
  project/activity cards: index number + workspace name, tinted `--accent` bg.
- Delete-confirmation micro-animation spell → our task delete confirm.

## 4. uiguideline.com/components (04, 11)
- Toast detail: breadcrumb, live example card + **big-number stat cards** (42% blue) →
  workspace stats (tasks done, members) as oversized-number cards.
- **Overlapping avatar stack + "+N" pill** → workspace member lists, task assignees. Direct fit.
- Gradient "NEW" badge on nav item → badge new features (AI summarize).

## 5. app.iconsax.io (05, 12, 13)
- Left filter sidebar w/ per-row counts + gradient "New" chips → task filter sidebar (status w/ counts).
- Segmented pill toggles (Static/Animated/Ai; Personal/Team) → view switchers (List/Board/Calendar).
- Icon grid w/ hairline cell dividers → dense grid layouts.
- Pricing: 4 hairline-separated columns, rainbow gradient CTA pill, strikethrough disabled features →
  future plan/upgrade page; gradient CTA reserved for single hero action only.
- Floating glass Download bar bottom-right → bulk-action bar (selected tasks → floating action bar).

## 6. freefaces.gallery (06, 14, 15)
- Full-bleed dark rows, giant centered specimen, hairline separators → marketing/landing hero.
- Detail: live-editable preview text + size slider + bg swatch dots → theme customizer preview pattern
  (we already ship 9 themes; add live preview pane w/ slider + swatches).

## Priority for our UI
1. Avatar stack +N (uiguideline) — members UX, cheap.
2. Big-number stat cards (uiguideline) — dashboard.
3. 3D-tilt orange button code (uiverse, copied) — primary CTAs.
4. Filter sidebar w/ counts + segmented toggle (iconsax) — tasks page.
5. Floating bulk-action bar (iconsax) — task multi-select.
6. Numbered tinted cards (designspells) — project list.
