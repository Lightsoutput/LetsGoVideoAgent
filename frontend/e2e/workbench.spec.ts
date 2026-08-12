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
  await expect(
    page.getByText("问答 Agent 正在并行检查视频证据、当前画面与联网资料…"),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "实时查看 Agent" })).toBeVisible();
  await expect(page.getByText("这是延迟返回的测试回答。")).toBeVisible();
});

test("switches video, Skill Studio and observability as exclusive workspaces", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".workspace-main")).toBeVisible();

  await page.getByRole("button", { name: "Skill Studio" }).click();
  await expect(page.getByLabel("Skill Studio")).toBeVisible();
  await expect(page.locator(".workspace-main")).toHaveCount(0);
  await expect(page.getByLabel("Agent 运行观测")).toHaveCount(0);
  await page.getByRole("button", { name: "Agent 运行观测" }).click();
  await expect(page.getByLabel("Agent 运行观测")).toBeVisible();
  await expect(page.getByLabel("Skill Studio")).toHaveCount(0);
  await expect(page.locator(".workspace-main")).toHaveCount(0);

  await page.getByRole("button", { name: "Agent 运行观测" }).click();
  await expect(page.locator(".workspace-main")).toBeVisible();
  await expect(page.getByLabel("Agent 运行观测")).toHaveCount(0);
  await expect(page.getByLabel("Skill Studio")).toHaveCount(0);
});

test("renders live Agent and runtime state machines", async ({ page }) => {
  test.setTimeout(30_000);
  const traceId = "55555555-5555-4555-8555-555555555555";
  const now = new Date().toISOString();
  const traceEvents = [
    ["workflow.started", "video_processing_graph", "running", "视频处理工作流已启动", "video_processing_graph"],
    ["agent.started", "ingestion_agent", "running", "正在读取媒体元数据", "ingestion_agent"],
    ["agent.completed", "ingestion_agent", "completed", "媒体接入与探测完成", "ingestion_agent"],
    ["agent.started", "perception_coordinator", "running", "音频与视觉分支并行启动", "perception_coordinator"],
    ["agent.completed", "audio_perception_agent", "completed", "语音转写已完成", "audio_perception_agent"],
    ["agent.completed", "visual_sampling_agent", "completed", "候选画面抽取完成", "visual_sampling_agent"],
    ["agent.completed", "ocr_perception_agent", "completed", "OCR 文字证据已生成", "ocr_perception_agent"],
    ["agent.started", "vlm_understanding_agent", "running", "正在理解人物、动作和界面含义", "vlm_understanding_agent"],
    ["tool.returned", "search_timeline", "completed", "视频记忆返回 8 条候选证据", "search_timeline"],
    ["model.requested", "Qwen3-VL", "running", "视觉模型正在分析采样帧", "Qwen3-VL"],
    ["mcp.called", "search_web", "running", "Search MCP 正在补充专业名词", "web_research_agent"],
  ].map(([eventType, name, status, summary, nodeId], index) => ({
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    trace_id: traceId,
    sequence: index + 1,
    event_type: eventType,
    name,
    status,
    summary,
    video_id: "11111111-1111-4111-8111-111111111111",
    task_id: null,
    agent_id: null,
    parent_event_id: null,
    attributes: { phase: "并行理解", node_id: nodeId },
    occurred_at: now,
  }));
  const videoFixture = {
    id: "11111111-1111-4111-8111-111111111111",
    title: "合成演示：塔防游戏新手关卡讲解",
    source: { kind: "synthetic", fixture_name: "tower-defense-tutorial-v1" },
    status: "processing",
    duration_ms: 300_000,
    width: 1_920,
    height: 1_080,
    fps: 30,
    source_object_key: null,
    progress: 0.68,
    current_stage: "visual_understanding",
    error_code: null,
    error_message: null,
    metadata: { fixture: true },
    version: 1,
    created_at: now,
    updated_at: now,
  };

  await page.route("**/api/v1/videos", (route) =>
    route.fulfill({ contentType: "application/json", json: { items: [videoFixture] } }),
  );
  await page.route("**/api/v1/videos/11111111-1111-4111-8111-111111111111", (route) =>
    route.fulfill({ contentType: "application/json", json: videoFixture }),
  );
  await page.route("**/api/v1/videos/*/processing", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        id: "66666666-6666-4666-8666-666666666666",
        video_id: "11111111-1111-4111-8111-111111111111",
        trace_id: traceId,
        status: "running",
        stage: "visual_understanding",
        stage_label: "视觉语义理解",
        progress: 0.68,
        elapsed_seconds: 86,
        eta_seconds: 41,
        message: "Qwen3-VL 正在理解画面语义",
        error: null,
        attempt_count: 1,
      },
    }),
  );
  await page.route("**/api/v1/traces/*", (route) =>
    route.fulfill({ contentType: "application/json", json: { items: traceEvents } }),
  );
  await page.route(`**/api/v1/agent-runs/${traceId}`, (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: "{}" }),
  );

  await page.goto("/");
  await expect.poll(async () => page.getByRole("button", { name: "运行观测" }).count()).toBe(1);
  await page.getByRole("button", { name: "运行观测" }).click();
  const outputDirectory = resolve(process.cwd(), "..", "artifacts", "ui");
  await mkdir(outputDirectory, { recursive: true });
  await page.getByRole("button", { name: "系统与 Harness" }).click();
  const searxHealth = page.locator(".runtime-health.status-ready").filter({
    has: page.getByText("SearXNG", { exact: true }),
  });
  const mcpHealth = page.locator(".runtime-health.status-ready").filter({
    has: page.getByText("Search MCP", { exact: true }),
  });
  await expect(searxHealth).toBeVisible({ timeout: 20_000 });
  await expect(mcpHealth).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: resolve(outputDirectory, "mcp-health-ready.png"), fullPage: true });

  await page.getByRole("button", { name: /状态机与 Trace/ }).click();
  await expect(page.getByText("多 Agent 视频处理状态机")).toBeVisible();
  await expect.poll(() => page.locator(".machine-node-running").count()).toBeGreaterThan(0);
  await page.waitForTimeout(650); // 等待 React Flow 的聚焦动画结束后再做视觉快照。

  await page.screenshot({ path: resolve(outputDirectory, "agent-state-machine.png"), fullPage: true });

  await page.getByRole("tab", { name: "Harness · 记忆 · MCP" }).click();
  await expect(page.getByText("Agent 运行时状态机")).toBeVisible();
  await expect(page.getByText("Search MCP", { exact: true }).last()).toBeVisible();
  await page.waitForTimeout(650);
  await page.screenshot({ path: resolve(outputDirectory, "runtime-state-machine.png"), fullPage: true });
});
