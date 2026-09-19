# Chat

| Element | Source idiom | Adaptation |
|---|---|---|
| Thread panel (`thread-panel.tsx`) | Slack/Linear thread sidebar | Right-hand aside: pinned parent card, reply list, composer at bottom; grid column opens on `lg` only |
| Message bubbles (`message-list.tsx`) | Slack/Discord message rows | Own messages right-aligned with `bg-primary text-primary-foreground`; inline edit form; `· edited` marker |
| Channel list empty state (`channel-list.tsx`) | shadcn `Empty` component | Icon + title + hint, same anatomy as notifications empty state |
