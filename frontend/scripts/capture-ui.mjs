import { chromium } from "@playwright/test";

// 使用机器已有的 Edge，避免为了截图额外下载一套 Chromium。
const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.on("console", (message) => console.log(`browser:${message.type()}:${message.text()}`));
page.on("requestfailed", (request) =>
  console.log(`requestfailed:${request.url()}:${request.failure()?.errorText}`),
);
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForTimeout(5000);
const video = page.locator("video");
let videoState = null;
let timelineSync = null;
if ((await video.count()) > 0) {
  await video.evaluate(async (element) => {
    if (element.readyState === 0) {
      await new Promise((resolve) => element.addEventListener("loadedmetadata", resolve, { once: true }));
    }
    element.currentTime = Math.min(300, element.duration - 0.1);
    await new Promise((resolve) => element.addEventListener("seeked", resolve, { once: true }));
  });
  await page.waitForTimeout(800);
  const firstClip = page.locator(".timeline-clip-wide[data-start-ms]").first();
  if ((await firstClip.count()) > 0) {
    const expectedMs = Number(await firstClip.getAttribute("data-start-ms"));
    await firstClip.click();
    await page.waitForTimeout(500);
    const actualMs = (await video.evaluate((element) => element.currentTime)) * 1000;
    timelineSync = { expectedMs, actualMs, deltaMs: Math.abs(expectedMs - actualMs) };
  }
  await video.evaluate(async (element) => {
    element.currentTime = Math.min(300, element.duration - 0.1);
    await new Promise((resolve) => element.addEventListener("seeked", resolve, { once: true }));
  });
  await page.waitForTimeout(500);
  videoState = await video.evaluate((element) => ({
    currentTime: element.currentTime,
    duration: element.duration,
    readyState: element.readyState,
    videoWidth: element.videoWidth,
    videoHeight: element.videoHeight,
  }));
}
await page.screenshot({ path: "ui-testcourse.png", fullPage: true });
console.log(
  JSON.stringify({ title: await page.title(), url: page.url(), videoState, timelineSync, body: (await page.textContent("body"))?.slice(0, 500) }),
);
await browser.close();
