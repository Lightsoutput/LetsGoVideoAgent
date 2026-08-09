import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const failedRequests = [];
const artifactDirectory = resolve("../artifacts/ui");
await mkdir(artifactDirectory, { recursive: true });
page.on("requestfailed", (request) => failedRequests.push(request.url()));

try {
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle", timeout: 15_000 });
  await page.getByRole("button", { name: "运行观测" }).click();
  await page.locator(".ops-panel").waitFor({ timeout: 5_000 });
  await page.waitForFunction(
    () => !document.querySelector(".service-status")?.textContent?.includes("检查中"),
    undefined,
    { timeout: 10_000 },
  );

  const report = await page.evaluate(() => {
  const panel = document.querySelector(".ops-panel");
  const video = document.querySelector(".video-stage");
  const trace = document.querySelectorAll(".trace-event");
  const panelStyle = panel ? getComputedStyle(panel) : null;
  return {
    panelVisible: Boolean(panel),
    videoVisible: Boolean(video && video.getBoundingClientRect().width > 0),
    panelPosition: panelStyle?.position,
    hasBackdrop: Boolean(document.querySelector(".ops-backdrop")),
    traceEvents: trace.length,
    workflowArea: document.querySelector(".side-workspace")?.getBoundingClientRect().toJSON(),
  };
  });

  const mcpText = await page.locator(".service-status").textContent();
  const policyItems = await page.locator(".policy-grid > span").count();
  await page.screenshot({ path: resolve(artifactDirectory, "observability-v1-p1.png"), fullPage: true });

  console.log(JSON.stringify({ ...report, mcpText, policyItems, failedRequests }, null, 2));
} finally {
  await browser.close();
}
