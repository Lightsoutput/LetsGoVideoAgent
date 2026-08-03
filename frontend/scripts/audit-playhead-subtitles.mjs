import { chromium } from "@playwright/test";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForSelector(".timeline-playhead-wide");

const video = page.locator("video");
const playhead = page.locator(".timeline-playhead-wide");
await playhead.scrollIntoViewIfNeeded();
const before = await video.evaluate((element) => element.currentTime);
const box = await playhead.boundingBox();
if (!box) throw new Error("播放头没有可用边界");
await page.mouse.move(box.x + box.width / 2, box.y + Math.min(45, box.height / 2));
await page.mouse.down();
await page.mouse.move(box.x + 160, box.y + Math.min(45, box.height / 2), { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(300);
const afterDrag = await video.evaluate((element) => element.currentTime);

await playhead.focus();
await page.keyboard.press("ArrowRight");
await page.waitForTimeout(150);
const afterKeyboard = await video.evaluate((element) => element.currentTime);

const visualTitles = await page
  .locator(".timeline-clip-wide.tone-visual")
  .evaluateAll((elements) => elements.map((element) => element.textContent?.trim()));
await page.locator(".timeline-clip-wide.tone-visual").first().hover();
await page.waitForTimeout(250);

// 跳到首条字幕，验证字幕在视频画面内渲染。
await page.locator(".timeline-clip-wide.tone-speech").first().click();
await page.waitForTimeout(300);
const subtitleVisible = await page.locator(".video-subtitle-overlay").isVisible();
const subtitleText = subtitleVisible
  ? await page.locator(".video-subtitle-overlay").innerText()
  : "";
await page.getByRole("button", { name: "字幕与说话人设置" }).click();
const settingsVisible = await page.locator(".subtitle-settings").isVisible();
const settingsText = settingsVisible ? await page.locator(".subtitle-settings").innerText() : "";

const removedButtonCount = await page.getByRole("button", { name: "定位播放头" }).count();
await page.screenshot({ path: "playhead-subtitles-final.png", fullPage: true });

console.log(JSON.stringify({
  before,
  afterDrag,
  afterKeyboard,
  dragChangedTime: Math.abs(afterDrag - before) > 0.1,
  keyboardAdvancedAboutOneSecond: afterKeyboard - afterDrag > 0.8,
  visualCardCount: visualTitles.length,
  visualTitles,
  subtitleVisible,
  subtitleText,
  settingsVisible,
  settingsText,
  removedButtonCount,
}, null, 2));
await browser.close();
