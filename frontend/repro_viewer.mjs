import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:5173/viewer/spider_100";

const browser = await chromium.launch({
  args: [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
  ],
});
const page = await browser.newPage();

page.on("console", (msg) => {
  console.log(`[console.${msg.type()}] ${msg.text()}`);
});
page.on("pageerror", (err) => {
  console.log(`[pageerror] ${err.message}\n${err.stack ?? ""}`);
});

console.log(`Navigating to ${url}`);
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(6000);

const errText = await page
  .locator("text=Viewer error")
  .first()
  .textContent()
  .catch(() => null);
console.log("ON-PAGE ERROR:", errText);

const shot = "/tmp/viewer_shot.png";
await page.screenshot({ path: shot, fullPage: true });
console.log("SCREENSHOT:", shot);

await browser.close();
