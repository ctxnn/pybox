// Render the site's raster images with headless Chrome:
//   assets/og.png               social preview (1200×630), from social/og.html
//   assets/apple-touch-icon.png 180×180 home-screen icon
//   assets/favicon-32.png       32×32 fallback for browsers without SVG favicons
//   node docs-site/render_images.mjs
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { openChrome } from "./cdp.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const icon = (size, radius) => "data:text/html," + encodeURIComponent(
  `<body style="margin:0"><svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 22 22">` +
  `<rect width="22" height="22" rx="${radius}" fill="#16171A"/><path d="M6.8 11.4l2.8 2.8 5.7-6.1" fill="none" stroke="#8DA2FF" ` +
  `stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></body>`);

const chrome = await openChrome({ width: 1200, height: 630, port: 9334 });
await chrome.open(pathToFileURL(resolve(here, "social/og.html")).href);
writeFileSync(resolve(here, "assets/og.png"), await chrome.shot("png"));
// Icons keep transparent corners.
await chrome.send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
await chrome.open(icon(180, 0), { w: 180, h: 180 });
writeFileSync(resolve(here, "assets/apple-touch-icon.png"), await chrome.shot("png"));
await chrome.open(icon(32, 6), { w: 32, h: 32 });
writeFileSync(resolve(here, "assets/favicon-32.png"), await chrome.shot("png"));
await chrome.close();
console.log("wrote og.png, apple-touch-icon.png, favicon-32.png");
