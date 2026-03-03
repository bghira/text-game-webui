import {
  applyApiError,
  applyApiSuccess,
  applyWsClosed,
  applyWsConnected,
  buildRuntimeChecksPath,
  buildClientDiagnosticsBundle,
  initDiagnosticsState,
  mergeDiagnosticsBundle,
  submitTurnFlow,
} from "../src/flow_helpers";

describe("runtime bootstrap flow", () => {
  it("requests runtime and health during startup", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    await fetcher("/api/runtime");
    await fetcher("/api/health");
    await fetcher("/api/runtime/checks");

    expect(seen).toEqual(["/api/runtime", "/api/health", "/api/runtime/checks"]);
  });

  it("builds runtime check path with optional llm probe override", () => {
    expect(buildRuntimeChecksPath(false)).toBe("/api/runtime/checks");
    expect(buildRuntimeChecksPath(true)).toBe("/api/runtime/checks?probe_llm=true");
  });

  it("retains turn refresh flow contract", async () => {
    const fetcher = jest.fn(async () => ({ ok: true }));
    const result = await submitTurnFlow(fetcher, "campaign-1", { actor_id: "actor-1", action: "look" });
    expect(result.calls).toContain("/api/campaigns/campaign-1/debug/snapshot");
  });

  it("tracks diagnostics transitions for api and websocket", () => {
    let state = initDiagnosticsState();
    state = applyApiSuccess(state, "2026-03-03T20:00:00Z");
    expect(state.api_last_success_at).toBe("2026-03-03T20:00:00Z");

    state = applyApiError(state, "2026-03-03T20:00:02Z", "boom");
    expect(state.api_last_error_message).toBe("boom");

    state = applyWsConnected(state, "2026-03-03T20:00:03Z");
    expect(state.ws_state).toBe("connected");
    expect(state.ws_reconnect_attempts).toBe(0);

    state = applyWsClosed(state, true, 2);
    expect(state.ws_reconnect_attempts).toBe(1);

    state = applyWsClosed(state, true, 2);
    expect(state.ws_reconnect_attempts).toBe(2);

    state = applyWsClosed(state, true, 2);
    expect(state.ws_last_error).toBe("WebSocket reconnect limit reached.");
  });

  it("builds merged diagnostics bundle payload with runtime and snapshot context", () => {
    const diagnostics = applyApiSuccess(initDiagnosticsState(), "2026-03-03T20:00:00Z");
    const clientBundle = buildClientDiagnosticsBundle(
      "2026-03-03T20:05:00Z",
      "0.2.0",
      "campaign-9",
      {
        gateway_backend: "tge",
        tge_completion_mode: "openai",
        tge_llm_model: "qwen-local",
        tge_llm_base_url: "http://127.0.0.1:1234/v1",
        tge_runtime_probe_llm_default: true,
        health_ok: true,
      },
      {
        backend: "tge",
        completion_mode: "openai",
        database: { ok: true, detail: "Connected." },
        engine: { ok: true, detail: "ZorkEmulator initialized." },
        llm: { configured: true, probe_attempted: true, ok: true, detail: "Completion endpoint responded." },
      },
      { generated_at: "2026-03-03T20:05:01Z", probe_llm: true },
      diagnostics,
      "dale-denton",
      { campaign: { id: "campaign-9" } },
    );
    const merged = mergeDiagnosticsBundle(
      {
        generated_at: "2026-03-03T20:05:01Z",
        runtime: { gateway_backend: "tge" },
        features: ["campaigns", "turns"],
        campaign_id: "campaign-9",
        campaign_debug_snapshot: { turns: [] },
      },
      clientBundle,
    );
    const mergedClient = merged.client_bundle as Record<string, unknown>;
    expect(merged.campaign_id).toBe("campaign-9");
    expect(mergedClient.selected_campaign_id).toBe("campaign-9");
    expect((mergedClient.runtime_cache as Record<string, unknown>).gateway_backend).toBe("tge");
    expect((mergedClient.runtime_cache as Record<string, unknown>).tge_completion_mode).toBe("openai");
    expect((mergedClient.runtime_cache as Record<string, unknown>).tge_runtime_probe_llm_default).toBe(true);
    expect(((mergedClient.runtime_checks_cache as Record<string, unknown>).llm as Record<string, unknown>).ok).toBe(
      true,
    );
    expect((mergedClient.runtime_checks_meta as Record<string, unknown>).probe_llm).toBe(true);
    expect((mergedClient.diagnostics as Record<string, unknown>).api_last_success_at).toBe("2026-03-03T20:00:00Z");
    expect(mergedClient.selected_actor).toBe("dale-denton");
  });
});
