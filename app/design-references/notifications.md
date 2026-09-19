# Notifications

| Element | Source idiom | Adaptation |
|---|---|---|
| Notification center popover (`notification-center.tsx`) | GitHub/GitLab header bell | Badge count, scrollable list, mark-all action; React Query with optimistic read state |
| Notifications page (`notification-list.tsx`) | Linear inbox | Unread dot + muted read rows, card layout, mark-as-read per row |
| Empty states | shadcn `Empty` component | Bell icon, "You are all caught up", description line |
