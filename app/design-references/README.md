# design-references/

Zero Native Design Rule: every visual treatment in `app/` must trace to a
catalogued reference here, plus an attribution comment in the implementing
file. Nothing is designed "from nothing".

## Catalog

| File | What it covers |
|---|---|
| `themes.md` | The 11 themes in `src/styles/themes/` — source preset + adaptation notes |
| `chat.md` | Thread panel, message bubbles, channel list empty state |
| `workspace.md` | Workspace switcher popover |
| `notifications.md` | Notification center popover, notifications page, empty states |
| `files-wiki.md` | File preview dialog, upload states, wiki `[[links]]` |
| `performance.md` | Route budgets, long-list windowing policy (process doc, not a visual source) |

## Rules

1. New visual element → add a row in the relevant file (source URL/idiom +
   what was adapted) **and** a `Source:` comment in the implementing file.
2. Only token-level colors (`var(--*)` / Tailwind token utilities). Semantic
   status accents (`emerald`/`amber`/`red` for file-type and state badges)
   are allow-listed — see `themes.md#semantic-accents`.
3. Contrast: `bun scripts/theme-contrast-audit.mjs` must pass (WCAG AA 4.5:1
   on all foreground/background token pairs, light + dark).
