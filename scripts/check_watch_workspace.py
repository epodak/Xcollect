#!/usr/bin/env python3
"""Offline UX contract for user-initiated Topic Watch and shared reading."""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "public/index.html").read_text(encoding="utf-8")
controller = (ROOT / "public/js/app.js").read_text(encoding="utf-8")
render = (ROOT / "public/js/render.js").read_text(encoding="utf-8")
api = (ROOT / "public/js/api.js").read_text(encoding="utf-8")
watch = (ROOT / "public/js/watch.js").read_text(encoding="utf-8")
css = (ROOT / "public/css/watch.css").read_text(encoding="utf-8")


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.id_ancestors = {}
        self.scopes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if attr.get("data-scope"):
            self.scopes.append(attr["data-scope"])
        if attr.get("id"):
            self.ids.append(attr["id"])
            self.id_ancestors[attr["id"]] = list(self.stack)
        if tag not in {"meta", "link", "img", "input", "br", "hr", "source"}:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


page = Elements()
page.feed(html)
assert len(page.ids) == len(set(page.ids)), "Duplicate element IDs in the UI"
assert set(("watch", "discovery", "bookmarks", "all")).issubset(page.scopes)
for required in (
    "watchWorkspace", "watchCreateToggle", "watchCreatePanel", "watchCreate",
    "watchTitle", "watchIntent", "watchList", "watchDetailTitle", "watchDetailIntent",
    "watchPause", "watchStatusStrip", "watchSearchInput", "watchSort", "watchResults",
    "watchResultEmpty", "watchScopeCount",
):
    assert required in page.ids, required
assert all("control-bar" not in classes for tag, classes
           in page.id_ancestors["watchWorkspace"]), "Workspace nested in toolbar"
assert "watchPanel" not in html
assert "btnWatch" not in html
assert 'href="/css/watch.css"' in html
assert 'data-scope="watch"' in html
assert "window.dispatchEvent(new CustomEvent(\"xcollect:watch-open\"))" in controller
assert "newScope === \"watch\"" in controller
assert "body.classList.toggle" in controller or "document.body.classList.toggle" in controller
assert "window.watchReaderItems" in render and "window.watchReaderItems" in api
assert "window.watchDropItem" in watch
assert "generateTweetCardHtml(item, index)" in watch
assert "observeTweetImpressions" in watch
assert "检索命中依据" in watch and "item.discovery_query" in watch
assert "CreateBookmark" not in watch and "toggleXBookmark" not in watch
assert "btn-bookmark" not in watch
assert "xcollect:watch-open" in watch
assert "#watchWorkspace[hidden]" in css
assert "body.watch-mode .app-layout" in css
assert "@media (max-width: 900px)" in css
assert "window.watchReaderItems" in controller, "Watch impression fallback missing"
print("research workspace UI contract: OK")
