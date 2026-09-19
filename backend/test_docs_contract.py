"""docs/API.md must cover every route the app exposes.

This file is hand-maintained (there is no generator: `app/scripts/gen-api.mjs`
emits TypeScript types, not Markdown), and nothing used to check it — which is
how presence shipped with zero documented rows while the changelog still listed
#123-#159 as unmerged. These three assertions are the cheap, machine-checkable
part of that contract:

1. every HTTP route is a row in the endpoint map,
2. every WebSocket route is described in the realtime section,
3. the file has exactly one Changelog, and its stated route count is the count
   of rows it actually contains,
4. every `bun run <script>` named anywhere in the docs is a real key in
   `app/package.json` (see `test_documented_bun_scripts_exist`).

Prose accuracy stays a review duty; path coverage and command existence do not.
"""

import json
import re
from pathlib import Path

import pytest

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "API.md"

#: Routes intentionally absent from the teammate guide: OpenAPI/Swagger plumbing
#: and the SPA fallback mount, none of which a client integrates against.
UNDOCUMENTED_OK = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

_NON_HTTP_METHODS = {"HEAD", "OPTIONS", "TRACE"}


def _norm(path: str) -> str:
    """Collapse `{any_param_name}` to `{}` so doc and code can disagree on naming."""
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/") or "/"


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def live_http_routes():
    from fastapi.routing import APIRoute

    from app import app as _app

    def _walk(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
                continue
            sub = getattr(getattr(route, "original_router", None), "routes", None)
            if sub is None:
                sub = getattr(route, "routes", None)
            if sub:
                yield from _walk(sub)

    out = set()
    for route in _walk(_app.routes):
        path = _norm(route.path)
        if path in UNDOCUMENTED_OK:
            continue
        for method in route.methods or ():
            if method.upper() not in _NON_HTTP_METHODS:
                out.add((method.upper(), path))
    return out


_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")
# A path cell may carry the query string it documents (`/x?limit=`) and may sit
# alone in a cell prefixed by its method (`GET /readyz`), so both shapes parse.
_PATH_CELL = re.compile(rf"`(?:({'|'.join(_METHODS)}) )?(/[^`?]*)[^`]*`")


#: Backend paths that appear in the guide without existing as a route, and are
#: meant to: the BFF table documents this handler as proxying to a route the
#: backend never shipped, so a reader can see the gap instead of hitting it.
STALE_ROWS_OK = {"/notifications/mark-all-read"}


def _documented_rows(doc_text: str) -> set[tuple[str, str]]:
    """Every `(method, path)` pair named in a table row of the guide."""
    pairs = set()
    for line in doc_text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        methods_in_first_cell = set(re.split(r", ?", cells[0])) & set(_METHODS)
        for cell in cells:
            for inline_method, path in _PATH_CELL.findall(cell):
                path = _norm(path)
                # `` `/` `` is what the prose idiom `literal `%`/`_`` looks like to
                # this regex, and `/x...` is table shorthand for a path family.
                if path == "/" or path.endswith("."):
                    continue
                if path.startswith("/api/"):
                    # Frontend half of the BFF mapping table, not a backend route.
                    continue
                if inline_method:
                    pairs.add((inline_method, path))
                elif methods_in_first_cell:
                    pairs.update((method, path) for method in methods_in_first_cell)
    return pairs


def test_every_http_route_is_documented(doc_text, live_http_routes):
    missing = sorted(live_http_routes - _documented_rows(doc_text))
    assert not missing, (
        "routes exist in the app but have no row in docs/API.md — add them in "
        f"the PR that added the route: {missing}"
    )


def test_no_row_documents_a_route_that_does_not_exist(doc_text, live_http_routes):
    """The other half of the drift: a row the code no longer backs."""
    live_paths = {path for _method, path in live_http_routes}
    stale = {path for _method, path in _documented_rows(doc_text)} - live_paths - STALE_ROWS_OK
    assert not stale, f"docs/API.md has rows for routes that are not in the app: {sorted(stale)}"


def test_every_websocket_route_is_documented(doc_text):
    from starlette.routing import WebSocketRoute

    from app import app as _app

    ws_paths = []
    for route in _app.routes:
        target = getattr(route, "original_router", None) or route
        for sub in getattr(target, "routes", ()) or ():
            if isinstance(sub, WebSocketRoute):
                ws_paths.append(_norm(sub.path))
    assert ws_paths, "no WebSocket routes found; the walk broke, not the app"
    for path in sorted(set(ws_paths)):
        pattern = re.escape(path).replace(re.escape("{}"), r"\{[^}]+\}")
        assert re.search(pattern, doc_text), (
            f"WebSocket route {path} is not described in docs/API.md"
        )


def test_single_changelog_section(doc_text):
    found = re.findall(r"^## Changelog$", doc_text, re.MULTILINE)
    assert len(found) == 1, f"expected exactly one '## Changelog', found {len(found)}"


def test_stated_route_count_matches_the_table(doc_text, live_http_routes):
    """The header's 'N HTTP paths' claim is checked, not trusted.

    Counts live routes that have at least one row — which is what the sentence
    means — so an intentional note about a route the backend never shipped does
    not inflate it.
    """
    stated = re.search(r"(\d+) HTTP paths", doc_text)
    assert stated, "docs/API.md header must state its coverage as 'N HTTP paths'"
    live_paths = {path for _method, path in live_http_routes}
    covered = {path for _method, path in _documented_rows(doc_text)} & live_paths
    assert int(stated.group(1)) == len(live_paths) == len(covered), (
        f"header claims {stated.group(1)} paths; the app exposes {len(live_paths)} "
        f"and the tables cover {len(covered)}"
    )


#: Docs a command name can be promised in. `bun run <script>` is the shape this
#: checks, because a script that is not in package.json is a claim no reader can
#: execute — `audit:themes` was cited as "the WCAG AA contrast gate" for weeks
#: while no such script, or any contrast machinery, existed.
DOC_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "RELEASE-CHECKLIST.md",
    "PROJECT-STATUS.md",
    "docs/API.md",
    "app/README.md",
    "app/AGENTS.md",
)


def test_documented_bun_scripts_exist():
    root = DOC_PATH.parents[1]
    scripts = set(json.loads((root / "app" / "package.json").read_text(encoding="utf-8"))["scripts"])
    named = set()
    for rel in DOC_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        named.update(re.findall(r"bun run ([a-z][a-z0-9:_-]*)", text))
    assert named, "the scan found no `bun run …` mentions at all; the regex or the docs moved"
    missing = sorted(named - scripts)
    assert not missing, (
        "docs promise `bun run` scripts that package.json does not define: "
        f"{missing}. Delete the sentence or add the script — do not leave it."
    )
