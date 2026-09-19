# Files & Wiki

| Element | Source idiom | Adaptation |
|---|---|---|
| Image preview dialog (`file-list.tsx`) | Google Drive / Dropbox quick preview | Eye action per row → dialog with full image; content proxied via BFF (`/api/files/[id]/content`) since backend returns API-origin URLs |
| Upload states (`file-uploader.tsx`) | Linear/Slack upload toasts | 10MB client-side guard with formatted-size error toast; dialog stays open on failure |
| Wiki `[[links]]` (`page-viewer.tsx`) | Obsidian/Roam wiki-link syntax | `[[Title]]` resolves against page list → primary dotted-underline button; unresolved renders muted italic |
