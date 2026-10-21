/* PyBox docs: theme, search, copy, tabs, mobile nav, on-page contents. No dependencies. */
(function () {
  "use strict";
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  // Theme: explicit choice wins, otherwise follow the OS.
  var root = document.documentElement;
  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function paintToggle() {
    var dark = currentTheme() === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      b.querySelector(".sun").style.display = dark ? "block" : "none";
      b.querySelector(".moon").style.display = dark ? "none" : "block";
    });
  }
  document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store.set("pybox-theme", next);
      paintToggle();
    });
  });
  paintToggle();

  // Mobile navigation drawer.
  var menu = document.querySelector("[data-menu]");
  if (menu) {
    menu.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      menu.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.querySelectorAll(".sidebar a").forEach(function (a) {
      a.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
    });
  }

  // Copy buttons on code blocks.
  document.querySelectorAll(".code").forEach(function (block) {
    var pre = block.querySelector("pre");
    if (!pre) return;
    var button = document.createElement("button");
    button.className = "copy";
    button.type = "button";
    button.textContent = "Copy";
    button.addEventListener("click", function () {
      var text = Array.prototype.map.call(pre.childNodes, function (n) {
        return n.nodeType === 1 && n.classList.contains("p") ? "" : n.textContent;
      }).join("");
      var done = function () { button.textContent = "Copied"; setTimeout(function () { button.textContent = "Copy"; }, 1400); };
      if (navigator.clipboard) { navigator.clipboard.writeText(text.trim()).then(done, function () {}); }
    });
    var caption = block.querySelector("figcaption");
    if (caption) { button.classList.add("inline"); caption.appendChild(button); } else { block.appendChild(button); }
  });

  // Tabs: <div class="tabs"><div class="tab-panel" data-label="…">…</div>…</div>
  document.querySelectorAll(".tabs").forEach(function (tabs, n) {
    var panels = tabs.querySelectorAll(":scope > .tab-panel");
    var list = document.createElement("div");
    list.className = "tablist";
    list.setAttribute("role", "tablist");
    var buttons = [];
    panels.forEach(function (panel, i) {
      var id = "tab-" + n + "-" + i;
      panel.id = id;
      panel.setAttribute("role", "tabpanel");
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", id);
      b.textContent = panel.getAttribute("data-label");
      b.addEventListener("click", function () { select(i); });
      b.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          var j = (i + (e.key === "ArrowRight" ? 1 : panels.length - 1)) % panels.length;
          select(j); buttons[j].focus();
        }
      });
      buttons.push(b);
      list.appendChild(b);
    });
    function select(i) {
      panels.forEach(function (p, j) { p.hidden = j !== i; });
      buttons.forEach(function (b, j) { b.setAttribute("aria-selected", j === i ? "true" : "false"); b.tabIndex = j === i ? 0 : -1; });
    }
    tabs.insertBefore(list, tabs.firstChild);
    select(0);
  });

  // On-page contents: highlight the section being read.
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var targets = tocLinks.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); }).filter(Boolean);
    var visible = new Map();
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible.set(e.target.id, e.isIntersecting); });
      var first = targets.find(function (t) { return visible.get(t.id); });
      if (first) {
        tocLinks.forEach(function (a) { a.classList.toggle("active", a.getAttribute("href") === "#" + first.id); });
      }
    }, { rootMargin: "-80px 0px -60% 0px" });
    targets.forEach(function (t) { observer.observe(t); });
  }

  // Search: index is embedded at build time so it works from file:// too.
  var dialog = document.querySelector(".search-dialog");
  var input = dialog && dialog.querySelector("input");
  var results = dialog && dialog.querySelector(".search-results");
  var index = window.PYBOX_SEARCH || [];
  var selected = 0;
  function escapeHtml(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function highlight(text, words) {
    var out = escapeHtml(text);
    words.forEach(function (w) {
      if (w.length < 2) return;
      out = out.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    });
    return out;
  }
  function search(q) {
    var words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return index.filter(function (e) { return e.top; }).slice(0, 8);
    return index.map(function (e) {
      var hay = (e.title + " " + e.page + " " + e.text).toLowerCase();
      var score = 0;
      for (var i = 0; i < words.length; i++) {
        if (hay.indexOf(words[i]) < 0) return null;
        if (e.title.toLowerCase().indexOf(words[i]) >= 0) score += 5;
        if (e.page.toLowerCase().indexOf(words[i]) >= 0) score += 2;
        score += 1;
      }
      return { e: e, s: score + (e.top ? 1 : 0) };
    }).filter(Boolean).sort(function (a, b) { return b.s - a.s; }).slice(0, 12).map(function (r) { return r.e; });
  }
  function render() {
    var q = input.value.trim();
    var words = q.toLowerCase().split(/\s+/).filter(Boolean);
    var found = search(q);
    selected = 0;
    if (!found.length) { results.innerHTML = '<li class="search-empty">No results for “' + escapeHtml(q) + '”</li>'; return; }
    results.innerHTML = found.map(function (e, i) {
      var where = e.title === e.page ? "" : e.page + " › ";
      var snippet = "";
      if (e.text) {
        var lower = e.text.toLowerCase(), at = -1;
        words.forEach(function (w) { var i = lower.indexOf(w); if (i >= 0 && (at < 0 || i < at)) at = i; });
        var start = at > 40 ? at - 40 : 0;
        snippet = (start ? "…" : "") + e.text.slice(start, start + 130) + (e.text.length > start + 130 ? "…" : "");
      }
      return '<li><a href="' + e.url + '" aria-selected="' + (i === 0) + '">' + where + highlight(e.title, words) +
        (snippet ? "<small>" + highlight(snippet, words) + "</small>" : "") + "</a></li>";
    }).join("");
  }
  function move(d) {
    var links = results.querySelectorAll("a");
    if (!links.length) return;
    selected = (selected + d + links.length) % links.length;
    links.forEach(function (a, i) { a.setAttribute("aria-selected", i === selected ? "true" : "false"); });
    links[selected].scrollIntoView({ block: "nearest" });
  }
  function openSearch() {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    input.value = "";
    render();
    input.focus();
  }
  if (dialog) {
    document.querySelectorAll("[data-search]").forEach(function (b) { b.addEventListener("click", openSearch); });
    input.addEventListener("input", render);
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { var a = results.querySelectorAll("a")[selected]; if (a) { window.location.href = a.href; dialog.close && dialog.close(); } }
    });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); openSearch(); }
      else if (e.key === "/" && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); openSearch(); }
    });
  }
})();
