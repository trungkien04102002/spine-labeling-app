// Open a study the way a clinician does and report why its picture looks wrong.
//
//   node tools/diagnose_viewer.mjs <BASE_URL> <STUDY_ID> <ROOM_ID> [OUT_DIR] [RUNS]
//   node tools/diagnose_viewer.mjs http://1.2.3.4:5678 p6-A-MRI 6 /tmp 4
//
// Per run it prints: page errors,
// WebGL-context warnings, the slice/VOI/camera the viewport ended up with, the
// mean brightness of the image area (near 0 = black picture), and saves a
// screenshot. Several runs because the worst viewer bugs were intermittent
// (a black image on about half of all loads, 2026-10-02).
//
// What the numbers usually mean -- see the memory note "upload bug playbook":
//   brightness ~0, parallelScale huge (thousands)  -> camera fitted to bad geometry
//   "Too many active WebGL contexts"                -> rendering engines leaking
//   pageerror "Invalid URL"                         -> API base URL relative in the build
//   brightness low but camera sane, VOI upper huge  -> saturated pixels, window too wide
// Playwright lives in frontend/node_modules; resolve it from this file's path.
const { chromium } = await import(
  new URL("../frontend/node_modules/playwright/index.mjs", import.meta.url).href
);

const [base, study, room, outDir = ".", runsArg = "3"] = process.argv.slice(2);
if (!base || !study || !room) {
  console.error("usage: diagnose_viewer.mjs <BASE_URL> <STUDY_ID> <ROOM_ID> [OUT_DIR] [RUNS]");
  process.exit(1);
}
const browser = await chromium.launch({
  args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
for (let run = 0; run < Number(runsArg); run++) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  const notes = [];
  page.on("pageerror", (e) => notes.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on("console", (m) => {
    const t = m.text();
    if (/WebGL contexts|error/i.test(t) && !/404|GL Driver/.test(t)) notes.push(`${m.type()}: ${t.slice(0, 200)}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 500 || (r.status() === 404 && /display\.nii/.test(r.url()))) notes.push(`HTTP ${r.status()} ${r.url()}`);
  });
  await page.goto(base + "/");
  await page.evaluate((id) => localStorage.setItem("spine.room", JSON.stringify({ id: Number(id), name: "diag" })), room);
  await page.goto(`${base}/viewer/${study}`);
  await page.waitForTimeout(12000);
  const state = await page.evaluate(() => {
    const h = window.__spineViewer;
    if (!h) return { viewer: "not mounted" };
    const v = h.viewport;
    const cam = v.getCamera();
    const r = (a) => a && Array.from(a).map((x) => Math.round(x * 100) / 100);
    return {
      slice: `${v.getCurrentImageIdIndex() + 1}/${h.imageIds.length}`,
      voi: v.getProperties().voiRange,
      parallelScale: Math.round(cam.parallelScale ?? -1),
      focal: r(cam.focalPoint),
      normal: r(cam.viewPlaneNormal),
      imageIds: h.imageIds[0]?.slice(-60),
    };
  });
  const file = `${outDir}/diag_${study}_${run}.png`;
  const clip = { x: 110, y: 330, width: 780, height: 450 };
  const png = await page.screenshot({ path: file, clip });
  // Mean of the PNG's raw bytes is a crude but sufficient black-image detector
  // once decoded; decode via a canvas in the page to stay dependency-free.
  const brightness = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width;
    c.height = img.height;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let s = 0;
    for (let i = 0; i < d.length; i += 4) s += (d[i] + d[i + 1] + d[i + 2]) / 3;
    return Math.round((s / (d.length / 4)) * 10) / 10;
  }, png.toString("base64"));
  console.log(`run ${run}: brightness=${brightness}`, JSON.stringify(state));
  for (const n of notes) console.log("   ", n);
  console.log("   screenshot:", file);
  await page.close();
}
await browser.close();
