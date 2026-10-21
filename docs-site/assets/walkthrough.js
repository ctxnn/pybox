/* "How one PyBox run works": a time-driven walkthrough. render(t) is pure, so the
   same code drives the in-page player and the frame-by-frame MP4 render.
   The run shown is a real recorded one (M5, 19 Oct 2026); timings inside a run are
   slowed down so they can be seen. */
(function () {
  "use strict";
  var W = 1600, H = 900;
  // Each scene has a heading and narration captions, timed to what is on screen.
  var SCENES = [
    { t: 0,  cap: "How one PyBox run works", cues: [] },
    { t: 5,  cap: "You hand PyBox a program.", cues: [
      [5, "Here is a real program, from a recorded test."],
      [8, "It tries to read a file that exists on your Mac, and a private setting."]] },
    { t: 11, cap: "It makes sure it's the only run, and tidies up.", cues: [
      [11, "First, PyBox takes a lock, so only one run can happen at a time."],
      [13.6, "Then it removes expired leftovers from earlier runs, and nothing else."]] },
    { t: 17, cap: "It writes down what it's about to build, before building it.", cues: [
      [17, "Before building anything, it writes a note saying what it is about to build."],
      [20, "If PyBox crashes halfway, the next run reads the note and cleans up."]] },
    { t: 23, cap: "It builds a fresh, sealed box.", cues: [
      [23, "A brand-new box appears inside a private Linux VM."],
      [25.6, "No files from your Mac, no internet, and strict limits on memory, processes and CPU."]] },
    { t: 30, cap: "It reads the settings back and checks every one.", cues: [
      [30, "PyBox asks the container engine what it actually built."],
      [32.8, "One difference from the policy, and the program never starts."]] },
    { t: 36, cap: "A watcher outside the box gets ready to take notes.", cues: [
      [36, "A watcher outside the box reads memory, processes and CPU from the Linux kernel."],
      [39, "It only reads. It can't stop or change anything."]] },
    { t: 42, cap: "The program runs. Two clocks start.", cues: [
      [42, "The program goes in on standard input, never on a command line."],
      [44.4, "Two clocks start: a 2-second deadline on your Mac, and a 3-second timer inside the box."],
      [47.6, "This program finished by itself in 0.054 seconds. It is slowed down here so you can see it."]] },
    { t: 50, cap: "It finishes. PyBox asks the engine what happened.", cues: [
      [50, "The exit code comes from the engine's own record, not from the program."],
      [52.6, "What the program printed is kept, but marked as untrusted."]] },
    { t: 56, cap: "The box is removed, and PyBox checks it's really gone.", cues: [
      [56, "The box is removed. Then PyBox looks for it again, to be sure it is gone."],
      [58.8, "Only then does it close the note it wrote before building."]] },
    { t: 62, cap: "You get the receipt.", cues: [
      [62, "You get a receipt for the run."],
      [64.6, "It shows what was measured, what the program said, and what is not known."]] },
    { t: 70, cap: "What if PyBox itself crashes?", cues: [
      [70, "A different test: this program sleeps for 8 seconds."],
      [71.6, "PyBox is force-killed a moment after it starts. Nothing on the Mac can stop the program now."],
      [75.2, "But the timer inside the box keeps counting."],
      [79.6, "At 3.03 seconds it stops the program, with no help from PyBox."],
      [80.6, "The stopped box stays behind. The next run removes it once it expires."]] },
    { t: 82, cap: "", cues: [] }
  ];
  var DURATION = 87;
  var WALLS = [["No files", 24, 58], ["No internet", 160, 58], ["Read-only", 330, 58], ["128 MiB", 24, 106], ["32 processes", 160, 106], ["½ CPU", 352, 106]];
  var SPARK = [8, 18, 26, 31, 34, 35, 35, 35];
  // Sound events for the soundtrack (render_video.mjs), on the same clock as render().
  var SOUNDS = SCENES.slice(1, -1).map(function (s) { return [s.t, "chime"]; }).concat(
    WALLS.map(function (w, i) { return [24.2 + i * 0.35, "tick"]; }),
    WALLS.map(function (w, i) { return [30.6 + i * 0.55, "tick"]; }),
    [[47.6, "bell"], [57.8, "bell"], [62.5, "receipt"], [71.6, "thud"], [79.6, "thud"], [79.7, "bell"], [82.2, "receipt"]]);

  var CHECK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor" opacity=".14"/><path d="M6 10.4l2.6 2.6L14 7.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var LOCK = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true"><rect x="4" y="9" width="12" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
  var NOTE = '<svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true"><rect x="4" y="2.5" width="12" height="15" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7 7h6M7 10h6M7 13h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var MARK = '<svg class="mark" viewBox="0 0 22 22" aria-hidden="true"><rect x="1.5" y="1.5" width="19" height="19" rx="5.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.8 11.4l2.8 2.8 5.7-6.1" fill="none" style="stroke:var(--accent)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function template() {
    var walls = WALLS.map(function (w, i) {
      return '<div class="wt-wall" data-el="wall' + i + '" style="left:' + w[1] + 'px;top:' + w[2] + 'px"><span class="tick">✓</span>' + w[0] + '</div>';
    }).join("");
    var spark = SPARK.map(function () { return "<i></i>"; }).join("");
    return '' +
      '<div class="wt-el wt-panel" data-el="mac" style="left:40px;top:40px;width:560px;height:660px">' +
        '<div class="wt-panel-head">Your Mac · PyBox</div>' +
        '<div class="wt-el wt-code" data-el="code"><b>recorded program · 19 Oct 2026</b><pre>import os,json\ntry:\n    open(\'/private/tmp/…/host-only-canary.txt\').read()\n    code=0\nexcept OSError as e:code=e.errno\nprint(json.dumps([code,os.getenv("PYBOX_M5_CANARY")]))</pre></div>' +
        '<div class="wt-el wt-row" data-el="lock" style="top:300px">' + LOCK + 'Only run right now</div>' +
        '<div class="wt-el wt-row" data-el="tidy" style="top:358px">' + CHECK + 'Expired leftovers: none to remove</div>' +
        '<div class="wt-el wt-row" data-el="journal" style="top:416px">' + NOTE + '<span data-el="journaltext">Note: about to build box <b>8f3a</b></span></div>' +
        '<div class="wt-el wt-clock" data-el="macclock" style="top:492px"><div class="wt-clock-label"><span>Mac deadline</span><b data-el="macval">0.000 s of 2 s</b></div><div class="wt-bar"><i data-el="macbar"></i></div></div>' +
        '<div class="wt-el wt-verdict" data-el="verdict" style="top:568px">' + CHECK + '<span>Engine: exited, code 0, after 0.054 s</span></div>' +
        '<div class="wt-el wt-crash" data-el="crash"><div>PyBox was killed</div></div>' +
      '</div>' +
      '<div class="wt-el wt-panel wt-vm" data-el="vm" style="left:660px;top:40px;width:900px;height:660px">' +
        '<div class="wt-panel-head">Private Linux VM</div>' +
        '<div class="wt-el wt-box" data-el="box"><div class="wt-box-head" data-el="boxhead">fresh box · run 8f3a</div>' + walls +
          '<div class="wt-el wt-prog" data-el="prog"><span data-el="progtext">Python</span><small data-el="progsub">running</small></div>' +
          '<div class="wt-el wt-said" data-el="said">It printed <code>[2, null]</code><br>(the program\'s own words: untrusted)</div>' +
          '<div class="wt-el wt-clock wt-boxclock" data-el="boxclock"><div class="wt-clock-label"><span>Timer inside the box</span><b data-el="boxval">0.00 s of 3 s</b></div><div class="wt-bar"><i data-el="boxbar"></i></div></div>' +
        '</div>' +
        '<div class="wt-el wt-watch" data-el="watch"><div class="wt-watch-title">Kernel watcher</div><p>Outside the box. Reads, never touches.</p><div class="wt-spark" data-el="spark">' + spark + '</div><div class="m" data-el="watchval">memory —</div></div>' +
        '<div class="wt-el wt-gone" data-el="gone">Box removed · confirmed gone ✓</div>' +
        '<div class="wt-el wt-gone" data-el="later" style="top:560px;font-size:20px;color:var(--text-2);font-weight:500">Stopped. The next run removes it once it expires.</div>' +
      '</div>' +
      '<div class="wt-el wt-flight" data-el="flight">import os,json …</div>' +
      '<div class="wt-el wt-dim" data-el="dim"></div>' +
      '<div class="wt-el wt-receipt" data-el="receipt"><div class="receipt">' +
        '<div class="receipt-head"><b>PYBOX RECEIPT</b><span>recorded run · 19 Oct 2026 · 15:59 UTC</span></div>' +
        '<div class="row"><span>Ran for</span><span>0.054 s of 2 s</span></div>' +
        '<div class="row"><span>Ended because</span><span>exited 0 by itself</span></div>' +
        '<div class="row"><span>Folders from your Mac</span><span>none (verified)</span></div>' +
        '<div class="row"><span>Network</span><span>none (verified)</span></div>' +
        '<div class="row"><span>Memory peak</span><span>4.3 of 128 MiB</span></div>' +
        '<div class="row"><span>Box</span><span class="yes">removed ✓</span></div>' +
        '<div class="block"><span class="dim">It printed (untrusted):</span><br><span class="said">[2, null]</span> <span class="dim">→ "file not found, setting empty"</span></div>' +
        '<div class="block"><span class="dim">Not known for certain:</span><br>final counters · clock alignment</div>' +
        '<div class="barcode"></div></div></div>' +
      '<div class="wt-el wt-caption" data-el="caption"><div class="wt-step" data-el="step"></div><div class="wt-cap" data-el="cap"></div><div class="wt-sub" data-el="sub"></div></div>' +
      '<div class="wt-el wt-intro" data-el="intro">' + MARK + '<h3>How one PyBox run works</h3><p>87 seconds · a real recorded run, slowed down</p></div>' +
      '<div class="wt-el wt-outro" data-el="outro">' + MARK + '<h3>Every run, every time.</h3><p>A fresh box · a checked seal · two clocks · a receipt you can check</p></div>';
  }

  function clamp(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function ease(x) { x = clamp(x); return (1 - Math.cos(Math.PI * x)) / 2; }
  function p(t, a, d) { return ease((t - a) / d); }
  function lin(t, a, b) { return clamp((t - a) / (b - a)); }

  function Walkthrough(root) {
    this.root = root;
    root.innerHTML = template();
    var els = {};
    root.querySelectorAll("[data-el]").forEach(function (n) { els[n.getAttribute("data-el")] = n; });
    this.els = els;
    this.lastScene = -1;
  }
  Walkthrough.prototype.render = function (t) {
    var e = this.els;
    function show(name, o, dx, dy, s) {
      var n = e[name];
      n.style.opacity = o;
      n.style.visibility = o <= 0.001 ? "hidden" : "visible";
      n.style.transform = "translate(" + (dx || 0) + "px," + (dy || 0) + "px) scale(" + (s == null ? 1 : s) + ")";
    }
    var crashRun = t >= 70;
    // Panels
    var panels = p(t, 3.2, 1.2);
    show("mac", panels, 0, (1 - panels) * 14);
    show("vm", p(t, 3.6, 1.2), 0, (1 - p(t, 3.6, 1.2)) * 14);
    // Intro and outro cards
    show("intro", 1 - p(t, 4, 1));
    show("outro", p(t, 82.2, 1));
    // Scene 1: the program
    var code = p(t, 5.4, 0.8);
    show("code", code, 0, (1 - code) * 18);
    // Scene 2: lock and tidy
    show("lock", p(t, 11.4, 0.6), (1 - p(t, 11.4, 0.6)) * -16, 0);
    show("tidy", p(t, 12.6, 0.6), (1 - p(t, 12.6, 0.6)) * -16, 0);
    // Scene 3: the journal note, closed after removal; reopened for the crash run
    show("journal", p(t, 17.4, 0.6), (1 - p(t, 17.4, 0.6)) * -16, 0);
    var closed = t >= 58.6 && !crashRun;
    e.journaltext.innerHTML = closed ? "<s>Note: about to build box <b>8f3a</b></s> closed ✓" :
      (crashRun ? "Note: about to build box <b>2c41</b>" : "Note: about to build box <b>8f3a</b>");
    // Scene 4: the box; it leaves in scene 9 and returns for the crash run
    var boxIn = p(t, 23.4, 0.9), boxOut = crashRun ? 0 : p(t, 56.6, 1);
    var boxBack = p(t, 70.6, 0.8);
    var boxO = crashRun ? boxBack : boxIn * (1 - boxOut);
    var dimmed = crashRun ? 1 - 0.45 * p(t, 80.2, 0.8) : 1;
    show("box", boxO * dimmed, 0, 0, crashRun ? 0.94 + 0.06 * boxBack : 0.94 + 0.06 * boxIn - 0.08 * boxOut);
    e.boxhead.textContent = crashRun ? "fresh box · run 2c41" : "fresh box · run 8f3a";
    for (var i = 0; i < WALLS.length; i++) {
      var w = e["wall" + i];
      var wo = crashRun ? 1 : p(t, 24.2 + i * 0.35, 0.5);
      w.style.opacity = wo;
      w.classList.toggle("ok", crashRun || t >= 30.6 + i * 0.55);
    }
    // Scene 6: the watcher
    var watchO = crashRun ? 0 : p(t, 36.4, 0.7) * (1 - p(t, 56.6, 1));
    show("watch", watchO, (1 - p(t, 36.4, 0.7)) * 20, 0);
    var run = lin(t, 44.3, 47.5);
    var bars = e.spark.children;
    for (var j = 0; j < bars.length; j++) {
      var on = clamp(run * bars.length - j);
      bars[j].style.height = (4 + SPARK[j] * 1.8 * on) + "px";
    }
    e.watchval.textContent = run > 0 ? "memory peak " + (4.3 * Math.min(1, run * 1.4)).toFixed(1) + " MiB · tasks 6" : "waiting for start";
    // Scene 7: the program travels into the box, clocks start
    var fly = p(t, 42.4, 1.4);
    var flyO = t < 42.4 || t > 44 ? 0 : Math.min(1, (t - 42.4) * 4) * (1 - p(t, 43.6, 0.4));
    show("flight", flyO, 70 + fly * 790, 140 + fly * 170, 1);
    var progO = crashRun ? boxBack : p(t, 43.6, 0.5) * (1 - boxOut);
    show("prog", progO);
    if (crashRun && t >= 79.6) {
      e.progtext.textContent = "Stopped by the timer";
      e.progsub.textContent = "at 3.03 s · exit 137";
    } else if (!crashRun && t >= 47.6) {
      e.progtext.textContent = "Finished";
      e.progsub.textContent = "by itself · 0.054 s";
    } else {
      e.progtext.textContent = "Python";
      e.progsub.textContent = "running";
    }
    var clocksO = crashRun ? p(t, 70.8, 0.5) : p(t, 44, 0.6);
    var macV = crashRun ? 0.098 * lin(t, 70.9, 71.6) : 0.054 * run;
    show("macclock", clocksO * (crashRun ? 1 : 1));
    e.macval.textContent = macV.toFixed(3) + " s of 2 s" + (crashRun && t >= 71.6 ? " · stopped" : "");
    e.macbar.style.width = (macV / 2 * 100) + "%";
    var boxV = crashRun ? 3.03 * lin(t, 72, 79.5) : 0.054 * run;
    show("boxclock", clocksO * (crashRun ? 1 : 1 - boxOut));
    e.boxval.textContent = boxV.toFixed(2) + " s of 3 s" + (crashRun && t >= 79.6 ? " · KILL" : "");
    e.boxbar.style.width = Math.min(100, boxV / 3 * 100) + "%";
    e.boxbar.style.background = crashRun && t >= 79.6 ? "#c23b2f" : "";
    // Scene 8: the engine's verdict, and what the program said
    var verdictO = crashRun ? 0 : p(t, 50.5, 0.6);
    show("verdict", verdictO, 0, (1 - verdictO) * 12);
    show("said", crashRun ? 0 : p(t, 51.6, 0.6) * (1 - boxOut));
    // Scene 9: gone
    show("gone", crashRun ? 0 : p(t, 57.8, 0.6) * (1 - p(t, 70, 0.4)));
    // Scene 10: the receipt
    var rec = p(t, 62.5, 0.9) * (1 - p(t, 69.6, 0.5));
    show("dim", p(t, 62.3, 0.6) * (1 - p(t, 69.6, 0.5)));
    show("receipt", rec, 0, (1 - rec) * 40, 0.97 + 0.03 * rec);
    // Scene 11: PyBox crashes; the timer still fires
    show("crash", p(t, 71.6, 0.5) * (1 - p(t, 82, 0.5)));
    show("later", p(t, 80.4, 0.6));
    // Captions: the step heading, then narration cues that change with the picture
    var k = 0;
    for (var s = 0; s < SCENES.length; s++) { if (t >= SCENES[s].t) k = s; }
    var scene = SCENES[k];
    var capO = k === 0 || k === SCENES.length - 1 ? 0 : p(t, scene.t + 0.1, 0.5);
    show("caption", capO, 0, (1 - capO) * 10);
    var c = -1;
    for (var m = 0; m < scene.cues.length; m++) { if (t >= scene.cues[m][0]) c = m; }
    var cueEnd = c + 1 < scene.cues.length ? scene.cues[c + 1][0] : (SCENES[k + 1] ? SCENES[k + 1].t : DURATION);
    var subO = c < 0 ? 0 : (c === 0 ? 1 : p(t, scene.cues[c][0], 0.35)) * (1 - p(t, cueEnd - 0.3, 0.3));
    show("sub", subO, 0, (1 - subO) * 6);
    if (k !== this.lastScene) {
      e.step.textContent = k > 0 && k < SCENES.length - 1 ? (k <= 10 ? "Step " + k + " of 10" : "Bonus") : "";
      e.cap.textContent = scene.cap;
      this.lastScene = k;
    }
    var cueText = c >= 0 ? scene.cues[c][1] : "";
    if (cueText !== this.lastCue) { e.sub.textContent = cueText; this.lastCue = cueText; }
    return k;
  };

  function format(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }

  function Player(host) {
    var frame = document.createElement("div");
    frame.className = "wt-frame";
    var stage = document.createElement("div");
    stage.className = "wt-stage";
    stage.setAttribute("role", "img");
    stage.setAttribute("aria-label", "Animated walkthrough of one PyBox run. The same steps are listed as text below.");
    frame.appendChild(stage);
    host.appendChild(frame);
    var wt = new Walkthrough(stage);
    var render = host.hasAttribute("data-render");
    function fit() { stage.style.transform = "scale(" + (frame.clientWidth / W) + ")"; }
    fit();
    window.addEventListener("resize", fit);
    var t = 0, playing = false, last = 0;
    if (render) {
      document.body.classList.add("wt-render");
      wt.render(0);
      window.PYBOX_WALKTHROUGH = { duration: DURATION, scenes: SCENES.map(function (x) { return x.t; }), sounds: SOUNDS,
        seek: function (x) { wt.render(x); return true; } };
      return;
    }
    var big = document.createElement("button");
    big.className = "wt-big-play";
    big.type = "button";
    big.innerHTML = '<span><svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>Watch the walkthrough · 1:27</span>';
    frame.appendChild(big);
    var controls = document.createElement("div");
    controls.className = "wt-controls";
    var audioSrc = host.getAttribute("data-audio");
    controls.innerHTML = '<button type="button" data-k="play" aria-label="Play"></button>' +
      (audioSrc ? '<button type="button" data-k="sound"></button>' : '') + '<span class="wt-time" data-k="time">0:00 / ' + format(DURATION) + '</span>' +
      '<div class="wt-track" data-k="track" role="slider" tabindex="0" aria-label="Walkthrough position" aria-valuemin="0" aria-valuemax="' + DURATION + '" aria-valuenow="0"><div class="wt-fill" data-k="fill"></div></div>' +
      (host.getAttribute("data-video") ? '<a class="wt-download" href="' + host.getAttribute("data-video") + '" download>Download video</a>' : "");
    host.appendChild(controls);
    var q = function (k) { return controls.querySelector('[data-k="' + k + '"]'); };
    var track = q("track");
    SCENES.slice(1, -1).forEach(function (s) {
      var tick = document.createElement("span");
      tick.className = "wt-tick";
      tick.style.left = (s.t / DURATION * 100) + "%";
      track.appendChild(tick);
    });
    var list = document.createElement("ol");
    list.className = "wt-chapters";
    SCENES.slice(1, -1).forEach(function (s, i) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.innerHTML = "<b>" + format(s.t) + "</b><span></span>";
      b.querySelector("span").textContent = (i < 10 ? i + 1 + ". " : "") + s.cap;
      b.addEventListener("click", function () { seek(s.t + 0.05); if (!playing) { seek(s.t + 5.5 > DURATION ? s.t : s.t + 5.5); } });
      li.appendChild(b);
      list.appendChild(li);
    });
    host.appendChild(list);
    var PLAY = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>';
    var PAUSE = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor"/></svg>';
    // Background music: an audio element that follows the player's clock.
    var SOUND_ON = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 6h2.5l3.5-3v10l-3.5-3H2.5z" fill="currentColor"/><path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.6a6 6 0 0 1 0 8.8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
    var SOUND_OFF = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 6h2.5l3.5-3v10l-3.5-3H2.5z" fill="currentColor"/><path d="M11 6l3.5 4M14.5 6L11 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
    var audio = audioSrc ? new Audio() : null, muted = false, loading = false;
    try { muted = localStorage.getItem("pybox-walkthrough-muted") === "1"; } catch (err) { /* storage unavailable */ }
    function loadAudio() {
      // Loaded whole as a blob so it can always seek, even from servers without range requests.
      loading = true;
      fetch(audioSrc).then(function (r) { if (!r.ok) throw new Error(r.status); return r.blob(); })
        .then(function (b) { audio.src = URL.createObjectURL(b); }, function () { audio.src = audioSrc; })
        .then(function () { audio.addEventListener("canplay", function () { syncAudio(true); }, { once: true }); audio.load(); });
    }
    function syncAudio(force) {
      if (!audio) return;
      if (!playing || muted) { if (!audio.paused) audio.pause(); return; }
      if (!audio.src) { if (!loading) loadAudio(); return; }
      if (force || Math.abs(audio.currentTime - t) > 0.3) { try { audio.currentTime = t; } catch (err) { /* not seekable yet */ } }
      if (audio.paused) audio.play().catch(function () { /* blocked; the picture plays on */ });
    }
    function paintSound() {
      var b = q("sound");
      if (!b) return;
      b.innerHTML = muted ? SOUND_OFF : SOUND_ON;
      b.setAttribute("aria-label", muted ? "Turn sound on" : "Turn sound off");
      b.setAttribute("aria-pressed", muted ? "false" : "true");
    }
    if (audio) {
      paintSound();
      q("sound").addEventListener("click", function () {
        muted = !muted;
        try { localStorage.setItem("pybox-walkthrough-muted", muted ? "1" : "0"); } catch (err) { /* storage unavailable */ }
        paintSound(); syncAudio(true);
      });
    }
    function paint() {
      var k = wt.render(t);
      q("fill").style.width = (t / DURATION * 100) + "%";
      q("time").textContent = format(t) + " / " + format(DURATION);
      track.setAttribute("aria-valuenow", Math.round(t));
      track.setAttribute("aria-valuetext", format(t) + " of " + format(DURATION) + (k > 0 && k < SCENES.length - 1 ? ", " + SCENES[k].cap : ""));
      q("play").innerHTML = playing ? PAUSE : PLAY;
      q("play").setAttribute("aria-label", playing ? "Pause" : "Play");
      list.querySelectorAll("button").forEach(function (b, i) { if (i + 1 === k) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current"); });
    }
    function frameLoop(now) {
      if (!playing) return;
      // While the music plays it is the clock, so picture and sound never drift apart.
      var audible = audio && !muted && audio.src && !audio.paused && audio.readyState >= 2;
      t = audible ? audio.currentTime : t + (now - last) / 1000;
      last = now;
      if (t >= DURATION) { t = DURATION; playing = false; }
      paint(); syncAudio(false);
      if (playing) requestAnimationFrame(frameLoop);
    }
    function play() {
      if (t >= DURATION) t = 0;
      playing = true; big.hidden = true; last = performance.now();
      requestAnimationFrame(frameLoop); paint(); syncAudio(true);
    }
    function pause() { playing = false; paint(); syncAudio(false); }
    function seek(x) { t = Math.max(0, Math.min(DURATION, x)); big.hidden = true; paint(); syncAudio(true); }
    big.addEventListener("click", play);
    q("play").addEventListener("click", function () { if (playing) pause(); else play(); });
    function fromEvent(ev) { var r = track.getBoundingClientRect(); seek((ev.clientX - r.left) / r.width * DURATION); }
    track.addEventListener("click", fromEvent);
    track.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowRight") { seek(t + 5); ev.preventDefault(); }
      if (ev.key === "ArrowLeft") { seek(t - 5); ev.preventDefault(); }
      if (ev.key === " ") { if (playing) pause(); else play(); ev.preventDefault(); }
    });
    // A still frame that already explains something, before anyone presses play.
    t = 0; wt.render(66); q("play").innerHTML = PLAY;
  }

  document.querySelectorAll("[data-walkthrough]").forEach(function (host) { new Player(host); });
})();
