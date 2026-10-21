// A minimal headless Chrome driver over the DevTools protocol, using Node's built-in
// WebSocket. Shared by render_video.mjs and render_images.mjs.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function openChrome({ width, height, port = 9333 }) {
  if (!existsSync(CHROME)) throw new Error("Google Chrome not found");
  const profile = mkdtempSync(join(tmpdir(), "pybox-chrome-"));
  const browser = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, "--remote-allow-origins=*",
    `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
    `--window-size=${width},${height}`, "--force-device-scale-factor=1", "about:blank"], { stdio: "ignore" });

  let wsUrl;
  for (let i = 0; i < 50 && !wsUrl; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      wsUrl = list.find((t) => t.type === "page")?.webSocketDebuggerUrl;
    } catch (e) { /* not up yet */ }
    if (!wsUrl) await sleep(200);
  }
  if (!wsUrl) throw new Error("Chrome did not expose a page target");
  const ws = new WebSocket(wsUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let seq = 0;
  const pending = new Map();
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : ok(msg.result);
    }
  });
  const send = (method, params = {}) => new Promise((ok, reject) => {
    const id = ++seq;
    pending.set(id, { ok, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };

  await send("Page.enable");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }, { name: "prefers-reduced-motion", value: "no-preference" }] });

  return {
    send, evaluate,
    async open(url, { w = width, h = height, ready = "true" } = {}) {
      await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await send("Page.navigate", { url });
      for (let i = 0; i < 100; i++) {
        if (await evaluate(`document.readyState === 'complete' && !!(${ready})`).catch(() => false)) break;
        await sleep(100);
      }
      await evaluate("document.fonts.ready.then(() => true)");
      await sleep(300);
    },
    async shot(format = "jpeg", quality = 92) {
      const r = await send("Page.captureScreenshot", format === "png" ? { format } : { format, quality });
      return Buffer.from(r.data, "base64");
    },
    async close() {
      ws.close();
      const exited = new Promise((r) => browser.once("exit", r));
      browser.kill();
      await exited;
      rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    },
  };
}
