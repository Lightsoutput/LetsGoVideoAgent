import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { expect, test } from "@playwright/test";

test("loads timeline, asks about a frame and renders evidence", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("LetsGoVideoAgent", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "和视频对话" })).toBeVisible();
  const demoVideo = page
    .getByRole("main")
    .getByText("合成演示：塔防游戏新手关卡讲解");
  if ((await demoVideo.count()) === 0) {
    test.skip(true, "当前后端未启用合成演示夹具");
  }
  await expect(demoVideo).toBeVisible();

  await page.getByRole("button", { name: /编队界面/ }).click();
  await page.getByRole("button", { name: "当前帧" }).click();
  await page
    .getByRole("button", { name: "当前画面中能看到哪些信息？" })
    .click();
  await page.getByRole("button", { name: /发送/ }).click();

  // 用户消息采用乐观更新：无需等待 Agent 完成即可在对话区看到已发送的问题。
  await expect(page.locator(".user-message").last()).toHaveText(
    "当前画面中能看到哪些信息？",
  );
  await expect(page.getByText("证据验证通过")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/可回放证据/)).toBeVisible();
  const evidenceImage = page.locator(".evidence-image img").first();
  await expect(evidenceImage).toBeVisible();
  await expect
    .poll(() =>
      evidenceImage.evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBeGreaterThan(0);

  const screenshotPath = resolve(
    process.cwd(),
    "..",
    "docs",
    "assets",
    "screenshots",
    "p0-workbench.png",
  );
  await mkdir(dirname(screenshotPath), { recursive: true });
  await page.screenshot({ fullPage: true, path: screenshotPath });
});

test("shows the sent question while the Agent is still thinking", async ({ page }) => {
  await page.route("**/api/v1/videos/*/questions", async (route) => {
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 1_200));
    await route.fulfill({
      contentType: "application/json",
      json: {
        id: "22222222-2222-4222-8222-222222222222",
        question_id: "33333333-3333-4333-8333-333333333333",
        status: "answered",
        text: "这是延迟返回的测试回答。",
        citations: [],
        evidence: [],
        confidence: 0.9,
        limitations: [],
        trace_id: "44444444-4444-4444-8444-444444444444",
        usage: {
          model_calls: 1,
          tool_calls: 1,
          input_tokens: 10,
          output_tokens: 10,
          estimated_cost_usd: "0",
          elapsed_ms: 1_200,
        },
        created_at: new Date().toISOString(),
      },
    });
  });

  await page.goto("/");
  const composer = page.getByPlaceholder("针对视频提问，Enter 发送…");
  await expect(composer).toBeEnabled();
  await composer.fill("这条问题应该立即显示");
  await composer.press("Enter");

  await expect(page.locator(".user-message").last()).toHaveText(
    "这条问题应该立即显示",
  );
  await expect(page.getByText("已收到问题，正在检索全片证据并组织回答…")).toBeVisible();
  await expect(page.getByText("这是延迟返回的测试回答。")).toBeVisible();
});
