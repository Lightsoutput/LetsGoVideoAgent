import { chromium } from "@playwright/test";

const viewports = [
  { name: "desktop-1080p", width: 1920, height: 1080 },
  { name: "laptop-1440", width: 1440, height: 900 },
  { name: "laptop-1366", width: 1366, height: 768 },
  { name: "tablet-1024", width: 1024, height: 768 },
  { name: "narrow-760", width: 760, height: 900 },
];

const browser = await chromium.launch({ channel: "msedge", headless: true });
const reports = [];

for (const viewport of viewports) {
  const page = await browser.newPage({ viewport });
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.waitForSelector(".video-stage");
  await page.waitForTimeout(1200);

  const report = await page.evaluate(() => {
    function rect(selector) {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        top: Math.round(bounds.top),
        bottom: Math.round(bounds.bottom),
        height: Math.round(bounds.height),
        width: Math.round(bounds.width),
        display: style.display,
        overflowY: style.overflowY,
      };
    }

    const stage = rect(".video-stage");
    const controls = rect(".player-controls");
    const timeline = rect(".timeline-panel");
    const timelinePan = rect(".timeline-pan-control");
    const media = document.querySelector("video");
    return {
      stage,
      canvas: rect(".player-canvas"),
      controls,
      timeline,
      timelineScroll: rect(".timeline-scroll"),
      timelinePan,
      workspace: rect(".workspace-main"),
      playerControlsInsideCard: Boolean(stage && controls && controls.bottom <= stage.bottom + 1),
      timelineControlInsideCard: Boolean(
        timeline && timelinePan && timelinePan.bottom <= timeline.bottom + 1,
      ),
      videoObjectFit: media ? getComputedStyle(media).objectFit : null,
    };
  });

  reports.push({ viewport, ...report });
  await page.screenshot({ path: `responsive-${viewport.name}.png`, fullPage: true });
  await page.close();
}

console.log(JSON.stringify(reports, null, 2));
await browser.close();
