"""Build the PyBox docs into ../site. Standard library only, like PyBox itself.

    python docs-site/build.py

Pages are HTML fragments in pages/. The first line of each is
<!--meta {"title": "...", "description": "..."}-->. nav.json orders the sidebar.
The build adds heading anchors, the on-page contents, prev/next links and a
search index embedded in every page, so the site also works from file://.
"""
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "site"
SITE_NAME = "PyBox"
REPO = "https://github.com/ctxnn/pybox"
# Where the site is published. Social previews, the sitemap and the canonical links
# need absolute URLs. For a custom domain, set PYBOX_SITE_URL=https://your.domain and
# the build also writes the CNAME file GitHub Pages reads.
SITE_URL = os.environ.get("PYBOX_SITE_URL", "https://ctxnn.github.io/pybox").rstrip("/")
NO_INDEX = {"404", "walkthrough"}
FONTS = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap"

ICON = {
    "logo": '<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><rect x="1.5" y="1.5" width="19" height="19" rx="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6.8 11.4l2.8 2.8 5.7-6.1" fill="none" style="stroke:var(--accent)" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "search": '<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l3.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "moon": '<svg class="moon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "sun": '<svg class="sun" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" style="display:none"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9L13 13M3 13l1.1-1.1M11.9 4.1L13 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "menu": '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "github": '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 .2a8 8 0 0 0-2.5 15.6c.4 0 .5-.2.5-.4v-1.5c-2.2.5-2.7-1-2.7-1-.4-.9-.9-1.2-.9-1.2-.7-.5.1-.5.1-.5.8.1 1.2.8 1.2.8.7 1.3 1.9.9 2.3.7.1-.5.3-.9.5-1.1-1.8-.2-3.6-.9-3.6-4 0-.9.3-1.6.8-2.1-.1-.2-.4-1 .1-2.1 0 0 .7-.2 2.2.8a7.5 7.5 0 0 1 4 0c1.5-1 2.2-.8 2.2-.8.4 1.1.2 1.9.1 2.1.5.6.8 1.3.8 2.1 0 3.1-1.9 3.7-3.6 3.9.3.3.5.8.5 1.5v2.2c0 .2.1.5.6.4A8 8 0 0 0 8 .2z"/></svg>',
}
CALLOUT_ICON = {
    "note": '<svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 9v5M10 6.2v.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "warn": '<svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l8 14H2z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M10 8v4M10 14.4v.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "limit": '<svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="2.5" width="14" height="15" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 7h7M6.5 10h7M6.5 13h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
}
HEADER_NAV = [("Docs", "introduction.html"), ("How it works", "how-it-works.html"),
              ("MCP", "mcp.html"), ("Evidence", "evidence.html")]


def slugify(text):
    text = re.sub(r"<[^>]+>", "", html.unescape(text)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def strip_tags(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def load_page(path):
    raw = path.read_text()
    match = re.match(r"<!--meta (\{.*?\})-->\n", raw, re.S)
    if not match:
        raise SystemExit("missing meta header: " + path.name)
    meta = json.loads(match.group(1))
    meta["slug"] = path.stem
    meta["body"] = raw[match.end():]
    return meta


def process(body):
    """Anchor headings, wrap tables, expand callouts; return body and contents."""
    toc = []
    used = set()

    def heading(m):
        level, attrs, inner = m.group(1), m.group(2), m.group(3)
        ident = re.search(r'id="([^"]+)"', attrs)
        ident = ident.group(1) if ident else slugify(inner)
        base, n = ident, 2
        while ident in used:
            ident, n = base + "-" + str(n), n + 1
        used.add(ident)
        toc.append((int(level), ident, strip_tags(inner)))
        attrs = re.sub(r'\s*id="[^"]+"', "", attrs)
        return ('<h{0} id="{1}"{2}>{3}<a class="anchor" href="#{1}" aria-label="Link to this section">#</a></h{0}>'
                .format(level, ident, attrs, inner))

    body = re.sub(r"<h([23])([^>]*)>(.*?)</h\1>", heading, body, flags=re.S)
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)

    def callout(m):
        kind = m.group(1)
        return '<div class="callout {0}">{1}<div>'.format(kind, CALLOUT_ICON[kind])
    body = re.sub(r'<div class="callout (note|warn|limit)">', callout, body)
    body = body.replace("<!--/callout-->", "</div>")
    return body, toc


def search_entries(meta, body, toc):
    url = meta["slug"] + ".html"
    entries = [dict(title=meta["title"], page=meta["title"], url=url, text=meta.get("description", ""), top=True)]
    parts = re.split(r'<h2 id="([^"]+)"[^>]*>', body)
    for i in range(1, len(parts), 2):
        ident, chunk = parts[i], parts[i + 1]
        title = strip_tags(chunk.split("</h2>", 1)[0]).rstrip("#").strip()
        text = strip_tags(chunk.split("</h2>", 1)[1] if "</h2>" in chunk else "")[:600]
        entries.append(dict(title=title, page=meta["title"], url=url + "#" + ident, text=text, top=False))
    return entries


def head(meta, scripts=()):
    slug = meta["slug"]
    title = SITE_NAME if slug == "index" else meta["title"] + " · " + SITE_NAME
    desc = html.escape(meta.get("description", ""), quote=True)
    url = SITE_URL + "/" + ("" if slug == "index" else slug + ".html")
    if slug in NO_INDEX:
        # 404.html is served at any missing path, so its relative links need a base.
        extra = '<meta name="robots" content="noindex">\n' + (
            '<base href="{}/">\n'.format(SITE_URL) if slug == "404" else "")
    else:
        extra = '<link rel="canonical" href="{}">\n'.format(url)
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
{extra}<meta property="og:type" content="website">
<meta property="og:site_name" content="PyBox">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="PyBox: run Python you don't trust, and get a receipt for what it did.">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{site}/assets/og.png">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0e10" media="(prefers-color-scheme: dark)">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="assets/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<link rel="stylesheet" href="assets/site.css">
{extra_css}<script>try{{var t=localStorage.getItem("pybox-theme");if(t)document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
</head>
""".format(title=html.escape(title), desc=desc, fonts=html.escape(FONTS, quote=True), extra=extra,
           url=html.escape(url, quote=True), site=html.escape(SITE_URL, quote=True),
           extra_css="".join('<link rel="stylesheet" href="assets/{}">\n'.format(s) for s in scripts if s.endswith(".css")))


def header(active, docs):
    hrefs = [h for _, h in HEADER_NAV]
    current = active if active in hrefs else ("introduction.html" if docs else None)
    nav = "".join('<a href="{1}"{2}>{0}</a>'.format(label, href, ' aria-current="page"' if href == current else "")
                  for label, href in HEADER_NAV)
    menu = ('<button class="icon-button menu-button" type="button" data-menu aria-label="Open navigation" aria-expanded="false">{}</button>'
            .format(ICON["menu"]) if docs else "")
    return """<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
<div class="header-inner">
{menu}<a class="brand" href="index.html">{logo}<span>PyBox</span>{small}</a>
<nav class="header-nav" aria-label="Main">{nav}</nav>
<span class="header-spacer"></span>
<button class="search-button" type="button" data-search aria-label="Search the docs">{search}<span>Search the docs</span><kbd>⌘K</kbd></button>
<a class="icon-button" href="{repo}" aria-label="PyBox on GitHub">{github}</a>
<button class="icon-button" type="button" data-theme-toggle aria-label="Switch theme">{moon}{sun}</button>
</div>
</header>
""".format(menu=menu, logo=ICON["logo"], small=" <small>Docs</small>" if docs else "", nav=nav,
           search=ICON["search"], repo=REPO, github=ICON["github"], moon=ICON["moon"], sun=ICON["sun"])


def footer(index, scripts=()):
    return """<footer class="site-footer">
<div class="footer-inner">
<span>PyBox is a local research prototype for Apple Silicon Macs. Not a hosted service.</span>
<nav aria-label="Footer"><a href="introduction.html">Docs</a><a href="evidence.html">Evidence and limits</a><a href="faq.html">FAQ</a><a href="{repo}">GitHub</a></nav>
</div>
</footer>
<dialog class="search-dialog" aria-label="Search the docs">
<div class="search-field">{search}<input type="search" placeholder="Search the docs" aria-label="Search the docs" autocomplete="off" spellcheck="false"><kbd>esc</kbd></div>
<ul class="search-results" role="listbox"></ul>
</dialog>
<script>window.PYBOX_SEARCH = {index};</script>
<script src="assets/site.js"></script>
{extra}</body>
</html>
""".format(repo=REPO, search=ICON["search"], index=json.dumps(index, ensure_ascii=False).replace("</", "<\\/"),
           extra="".join('<script src="assets/{}"></script>\n'.format(s) for s in scripts if s.endswith(".js")))


def sidebar(nav, pages, slug):
    out = ['<nav class="sidebar" aria-label="Documentation">']
    for section in nav:
        out.append('<div class="nav-section"><h2>{}</h2>'.format(html.escape(section["title"])))
        for s in section["pages"]:
            out.append('<a href="{0}.html"{1}>{2}</a>'.format(
                s, ' aria-current="page"' if s == slug else "", html.escape(pages[s].get("nav", pages[s]["title"]))))
        out.append("</div>")
    out.append("</nav>")
    return "\n".join(out)


def contents(toc):
    items = [t for t in toc if t[0] in (2, 3)]
    if len(items) < 2:
        return '<aside class="toc" aria-label="On this page"></aside>'
    links = "".join('<a href="#{1}"{2}>{0}</a>'.format(html.escape(text), ident, ' class="sub"' if level == 3 else "")
                    for level, ident, text in items)
    return '<aside class="toc" aria-label="On this page"><h2>On this page</h2>{}</aside>'.format(links)


def pager(order, pages, slug):
    i = order.index(slug)
    prev = pages[order[i - 1]] if i > 0 else None
    nxt = pages[order[i + 1]] if i + 1 < len(order) else None
    parts = ['<nav class="pager" aria-label="Previous and next">']
    if prev:
        parts.append('<a class="prev" href="{0}.html"><small>Previous</small>{1}</a>'.format(prev["slug"], html.escape(prev["title"])))
    if nxt:
        parts.append('<a class="next" href="{0}.html"><small>Next</small>{1}</a>'.format(nxt["slug"], html.escape(nxt["title"])))
    parts.append("</nav>")
    return "".join(parts)


def publish_files(slugs):
    """Files for hosting: sitemap, robots.txt, .nojekyll and, for a custom domain, CNAME."""
    urls = "".join("  <url><loc>{}/{}</loc></url>\n".format(SITE_URL, "" if s == "index" else s + ".html")
                   for s in slugs if s not in NO_INDEX)
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: {}/sitemap.xml\n".format(SITE_URL))
    (OUT / ".nojekyll").write_text("")
    host = urlparse(SITE_URL).hostname or ""
    cname = OUT / "CNAME"
    if host and not host.endswith(".github.io"):
        cname.write_text(host + "\n")
    elif cname.exists():
        cname.unlink()


def main():
    nav = json.loads((HERE / "nav.json").read_text())["sections"]
    order = [s for section in nav for s in section["pages"]]
    pages = {p.stem: load_page(p) for p in sorted((HERE / "pages").glob("*.html"))}
    missing = [s for s in order + ["index"] if s not in pages]
    if missing:
        raise SystemExit("nav names missing pages: " + ", ".join(missing))
    processed, index = {}, []
    for slug, meta in pages.items():
        body, toc = process(meta["body"])
        processed[slug] = (body, toc)
        if slug in order:
            index.extend(search_entries(meta, body, toc))

    if OUT.exists():
        for old in list(OUT.glob("*.html")) + [OUT / "assets"]:
            if old.is_dir():
                shutil.rmtree(old)
            elif old.exists():
                old.unlink()
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    for asset in (HERE / "assets").iterdir():
        if asset.is_file():
            shutil.copyfile(asset, OUT / "assets" / asset.name)
    if (OUT / "data").exists():
        shutil.rmtree(OUT / "data")
    shutil.copytree(HERE / "data", OUT / "data")

    for slug, meta in pages.items():
        body, toc = processed[slug]
        scripts = meta.get("assets", [])
        if meta.get("layout") == "bare":
            page = (head(meta, scripts) + '<body class="bare">\n' + body +
                    "".join('<script src="assets/{}"></script>\n'.format(x) for x in scripts if x.endswith(".js")) + "</body>\n</html>\n")
        elif meta.get("layout") == "home":
            page = (head(meta, scripts) + '<body class="home">\n' + header("index.html", False) +
                    '<main id="main">\n' + body + "</main>\n" + footer(index, scripts))
        else:
            section = next(s["title"] for s in nav if slug in s["pages"])
            article = ('<p class="eyebrow">{}</p><h1>{}</h1>'.format(html.escape(section), meta["title"]) +
                       ('<p class="lede">{}</p>'.format(meta["lede"]) if meta.get("lede") else "") + body +
                       '<p class="page-meta">Checked against the source on {}.</p>'.format(meta.get("checked", "20 October 2026")) +
                       pager(order, pages, slug))
            page = (head(meta, scripts) + '<body class="docs">\n' + header(slug + ".html", True) +
                    '<div class="shell">\n' + sidebar(nav, pages, slug) +
                    '\n<main id="main" class="content"><article class="prose">\n' + article +
                    "\n</article></main>\n" + contents(toc) + "\n</div>\n" + footer(index, scripts))
        (OUT / (slug + ".html")).write_text(page)
    publish_files(["index"] + order)
    print("built {} pages into {}".format(len(pages), OUT.relative_to(HERE.parent)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
