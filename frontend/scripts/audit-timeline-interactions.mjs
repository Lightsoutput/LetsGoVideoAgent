import { chromium } from "@playwright/test";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForSelector(".timeline-clip-wide.tone-speech");

const speechClip = page.locator(".timeline-clip-wide.tone-speech").first();
const beforeHover = await speechClip.boundingBox();
await speechClip.hover();
await page.waitForTimeout(250);
const afterHover = await speechClip.boundingBox();
const focusState = await page.evaluate(() => ({
  focusedRows: document.querySelectorAll(".timeline-row-wide.is-focused").length,
  dimmedOpacity: getComputedStyle(
    document.querySelector(".timeline-row-wide:not(.is-focused)"),
  ).opacity,
  visibleTracks: document.querySelectorAll(".timeline-row-wide").length,
}));

await page.getByRole("button", { name: "适应窗口" }).click();
await page.waitForTimeout(350);
const fitState = await page.evaluate(() => {
  const scroller = document.querySelector(".timeline-scroll");
  const zoom = document.querySelector('input[aria-label="时间轴缩放"]');
  return {
    zoomValue: zoom?.value,
    horizontalOverflow: scroller ? scroller.scrollWidth - scroller.clientWidth : null,
    speechLaneCount: new Set(
      [...document.querySelectorAll(".timeline-clip-wide.tone-speech")].map(
        (element) => getComputedStyle(element).top,
      ),
    ).size,
    chapterLaneCount: new Set(
      [...document.querySelectorAll(".timeline-clip-wide.tone-chapter")].map(
        (element) => getComputedStyle(element).top,
      ),
    ).size,
    hiddenNativeHorizontalBar:
      getComputedStyle(scroller, "::-webkit-scrollbar:horizontal").height === "0px",
  };
});

// 缩放会重排所有片段，重新定位后从 DOM 触发点击，避免 Playwright 等待 2px 全局片段稳定。
await page
  .locator(".timeline-clip-wide.tone-speech")
  .first()
  .evaluate((element) => element.click());
await page.waitForSelector(".timeline-inspector");
const detailState = await page.evaluate(() => {
  const inspector = document.querySelector(".timeline-inspector");
  return inspector
    ? {
        position: getComputedStyle(inspector).position,
        textLength: inspector.textContent?.trim().length ?? 0,
      }
    : null;
});

await page.screenshot({ path: "timeline-interactions.png", fullPage: true });
console.log(JSON.stringify({ beforeHover, afterHover, focusState, fitState, detailState }, null, 2));
await browser.close();
