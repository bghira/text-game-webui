import { campaignExportFlow, loadLLMSettingsFlow, cancelTimerFlow, recordPortraitFlow } from "../src/flow_helpers";

describe("campaign export flow", () => {
  test("fetches campaign export data", async () => {
    const fetcher = jest.fn(async () => ({
      turns: [{ id: 1, content: "TURN 1" }],
      sessions: [],
      campaign_id: "camp-1",
    }));

    const result = await campaignExportFlow(fetcher, "camp-1");

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/campaigns/camp-1/export");

    const data = result.result as { turns: Array<{ id: number }> };
    expect(data.turns).toHaveLength(1);
    expect(data.turns[0].id).toBe(1);
  });
});

describe("LLM settings flow", () => {
  test("loads settings with correct defaults", async () => {
    const fetcher = jest.fn(async () => ({
      completion_mode: "ollama",
      base_url: "http://localhost:11434/v1",
      model: "llama3.2:latest",
      temperature: 0.9,
      max_tokens: 4096,
      timeout_seconds: 180,
      keep_alive: "10m",
      gateway_backend: "tge",
    }));

    const result = await loadLLMSettingsFlow(fetcher);

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/settings");

    expect(result.settings.completion_mode).toBe("ollama");
    expect(result.settings.model).toBe("llama3.2:latest");
    expect(result.settings.temperature).toBe(0.9);
    expect(result.settings.gateway_backend).toBe("tge");
  });

  test("handles missing fields with defaults", async () => {
    const fetcher = jest.fn(async () => ({}));

    const result = await loadLLMSettingsFlow(fetcher);

    expect(result.settings.completion_mode).toBe("deterministic");
    expect(result.settings.base_url).toBe("");
    expect(result.settings.model).toBe("");
    expect(result.settings.temperature).toBe(0.7);
    expect(result.settings.max_tokens).toBe(2048);
    expect(result.settings.timeout_seconds).toBe(120);
    expect(result.settings.keep_alive).toBe("5m");
    expect(result.settings.gateway_backend).toBe("inmemory");
  });
});

describe("cancel timer flow", () => {
  test("sends cancel request", async () => {
    const fetcher = jest.fn(async () => ({ ok: true }));

    const result = await cancelTimerFlow(fetcher, "camp-1");

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/campaigns/camp-1/timers/cancel");

    const res = result.result as { ok: boolean };
    expect(res.ok).toBe(true);
  });
});

describe("character portrait flow", () => {
  test("records portrait with correct payload", async () => {
    const fetcher = jest.fn(async () => ({ ok: true }));

    const result = await recordPortraitFlow(
      fetcher,
      "camp-1",
      "arsipea-denton",
      "https://example.com/portrait.png",
    );

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/campaigns/camp-1/roster/portrait");

    const call = fetcher.mock.calls[0] as unknown as [string, { body: string }];
    const body = JSON.parse(call[1].body);
    expect(body.character_slug).toBe("arsipea-denton");
    expect(body.image_url).toBe("https://example.com/portrait.png");
  });
});
