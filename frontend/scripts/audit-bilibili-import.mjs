import { chromium } from "@playwright/test";

const expectedId = process.argv[2];
if (!expectedId) throw new Error("请传入视频 ID");

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.locator(".header-video-tools select").selectOption(expectedId);
await page.waitForSelector("video");
await page.waitForSelector(".timeline-clip-wide");
await page.waitForFunction(() => {
  const media = document.querySelector("video");
  return media instanceof HTMLVideoElement && media.readyState >= 1 && media.duration > 0;
});

const mediaState = await page.locator("video").evaluate(async (media) => {
  media.currentTime = 3;
  await media.play();
  await new Promise((resolve) => setTimeout(resolve, 800));
  media.pause();
  return {
    duration: media.duration,
    currentTime: media.currentTime,
    readyState: media.readyState,
    videoWidth: media.videoWidth,
    videoHeight: media.videoHeight,
    error: media.error?.message ?? null,
  };
});
const uiState = await page.evaluate(() => ({
  title: document.querySelector(".stage-title strong")?.textContent,
  pendingVisible: Boolean(document.querySelector(".media-pending")),
  timelineItems: document.querySelectorAll(".timeline-clip-wide").length,
  processingVisible: Boolean(document.querySelector(".processing-status")),
}));
await page.screenshot({ path: "bilibili-import-final.png", fullPage: true });
console.log(JSON.stringify({ mediaState, uiState }, null, 2));
await browser.close();
