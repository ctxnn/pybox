# PyBox docs site (source)

The published site lives in [`../site/`](../site/index.html) and is generated from
this folder. Like PyBox itself, the build uses only the Python standard library.

```bash
python3 docs-site/build.py
```

```bash
node docs-site/render_video.mjs
node docs-site/render_images.mjs
```

The first command rebuilds every page into `site/` and copies `docs-site/data/` to `site/data/`.
The second re-renders the walkthrough video with its captions and music
(`--audio-only` remakes just the music). The third renders the social preview image
and PNG icons. Both need Google Chrome and `ffmpeg`; build the site first.

## Publishing

`.github/workflows/pages.yml` builds the site and deploys it with GitHub Pages on every
push to `main` that touches `docs-site/`. Turn it on once under Settings → Pages →
Source: GitHub Actions. The build also writes `sitemap.xml`, `robots.txt`, `.nojekyll`
and a `404.html`.

Social previews and the sitemap need the site's absolute address. It defaults to
`https://ctxnn.github.io/pybox`; for a custom domain set the repository variable
`PYBOX_SITE_URL` (for example `https://pybox.example.com`) and the build writes the
`CNAME` file too. Locally: `PYBOX_SITE_URL=https://… python3 docs-site/build.py`.

## Layout

| Path | What it is |
| --- | --- |
| `nav.json` | Sidebar sections and page order (also sets prev/next) |
| `pages/*.html` | One fragment per page. The first line is `<!--meta {…}-->` with `title`, `description`, optional `lede`, `nav`, `layout` (`home` or `bare`) and `assets` |
| `assets/site.css`, `site.js` | Design tokens (light/dark), layout, components, search, theme toggle, tabs, copy buttons |
| `assets/walkthrough.*` | The "How one PyBox run works" player. `render(t)` is pure, so the page player and the video share one source |
| `assets/how-pybox-works.mp4`, `.jpg`, `.m4a` | The rendered walkthrough (1920×1080, 30 fps, 87 s, captions in the picture, music), its poster, and the music alone for the page player |
| `assets/og.png`, `apple-touch-icon.png`, `favicon-32.png` | Social preview and icons, from `render_images.mjs` (`social/og.html` is the preview's layout) |
| `data/replay/` | Sanitised copies of recorded runs, from `tools/export_replay.py`; copied to `site/data/` |
| `build.py` | Adds heading anchors, wraps tables, builds sidebar / on-page contents / prev-next, and embeds a search index in every page (so `file://` works) |
| `render_video.mjs`, `cdp.mjs` | Drive headless Chrome over the DevTools protocol frame by frame, then encode with ffmpeg |
| `soundtrack.mjs` | Synthesises the walkthrough's music from sine waves (original, no licence needed), timed to the same events as the picture |

## Writing pages

- Use plain language first and the exact setting second. Every number must match
  the source or a recorded run. Say when something is recorded, illustrative or unknown.
- Components: `<figure class="code"><figcaption>…</figcaption><pre>…</pre></figure>`,
  `<div class="tabs"><div class="tab-panel" data-label="…">…</div></div>`,
  `<ol class="steps">`, `<div class="cards">`, and callouts written as
  `<div class="callout note|warn|limit">…<!--/callout--></div>`. Write bare `<table>`s;
  the build wraps them for scrolling.
- Program output shown on the site comes from recorded evidence
  (`tools/export_replay.py` writes `docs-site/data/replay/`). Never present it as a live run.
