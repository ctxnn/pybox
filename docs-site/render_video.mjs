// Render the walkthrough to MP4 with its soundtrack: headless Chrome steps the
// time-driven stage frame by frame, soundtrack.mjs writes the music, ffmpeg encodes both.
//   node docs-site/render_video.mjs [--fps 30] [--frames-dir DIR] [--audio-only]
// --audio-only keeps the current video picture and only remakes the sound.
// Needs Google Chrome and ffmpeg. Build the site first (python docs-site/build.py).
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, copyFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { openChrome } from "./cdp.mjs";
import { soundtrack } from "./soundtrack.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const fps = Number(opt("--fps", "30"));
const audioOnly = args.includes("--audio-only");
const framesDir = resolve(opt("--frames-dir", mkdtempSync(join(tmpdir(), "pybox-frames-"))));
const page = pathToFileURL(resolve(here, "../site/walkthrough.html")).href;
const out = resolve(here, "assets/how-pybox-works.mp4");
const music = resolve(here, "assets/how-pybox-works.m4a");
const poster = resolve(here, "assets/how-pybox-works.jpg");
const work = mkdtempSync(join(tmpdir(), "pybox-audio-"));
const ffmpeg = (list) => { if (spawnSync("ffmpeg", ["-y", "-loglevel", "error", ...list], { stdio: "inherit" }).status !== 0) throw new Error("ffmpeg failed"); };

const chrome = await openChrome({ width: 1920, height: 1080 });
await chrome.open(page, { ready: "window.PYBOX_WALKTHROUGH" });
const info = await chrome.evaluate("({ duration: PYBOX_WALKTHROUGH.duration, scenes: PYBOX_WALKTHROUGH.scenes, sounds: PYBOX_WALKTHROUGH.sounds })");
if (!audioOnly) {
  mkdirSync(framesDir, { recursive: true });
  const total = Math.round(info.duration * fps);
  console.log(`rendering ${total} frames at ${fps} fps into ${framesDir}`);
  for (let i = 0; i < total; i++) {
    await chrome.evaluate(`PYBOX_WALKTHROUGH.seek(${(i / fps).toFixed(4)})`);
    writeFileSync(join(framesDir, `f${String(i).padStart(5, "0")}.jpg`), await chrome.shot());
    if (i % 300 === 0) console.log(`  frame ${i}/${total}`);
  }
  await chrome.evaluate("PYBOX_WALKTHROUGH.seek(66)");
  writeFileSync(poster, await chrome.shot("jpeg", 90));
}
await chrome.close();

const wav = join(work, "music.wav");
writeFileSync(wav, soundtrack(info));
ffmpeg(["-i", wav, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", music]);
const tmp = join(work, "out.mp4");
const picture = audioOnly ? ["-i", out] : ["-framerate", String(fps), "-i", join(framesDir, "f%05d.jpg")];
const video = audioOnly ? ["-c:v", "copy"] : ["-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p"];
ffmpeg([...picture, "-i", wav, "-map", "0:v", "-map", "1:a", ...video, "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", tmp]);
copyFileSync(tmp, out);
rmSync(work, { recursive: true, force: true });
if (!audioOnly && !args.includes("--frames-dir")) rmSync(framesDir, { recursive: true, force: true });
console.log("wrote " + out + " and " + music);
