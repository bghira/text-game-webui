import {
  initCampaignFlagsState,
  loadCampaignFlagsFlow,
  setCampaignFlagFlow,
  CampaignFlagsState,
  FetchLike,
} from "../src/flow_helpers";

function makeFetcher(responses: Record<string, unknown>): { fetcher: FetchLike; calls: { url: string; init?: { method?: string; body?: string } }[] } {
  const calls: { url: string; init?: { method?: string; body?: string } }[] = [];
  const fetcher: FetchLike = async (url, init) => {
    calls.push({ url, init });
    return responses[url] ?? {};
  };
  return { fetcher, calls };
}

describe("campaign flags with clock_start_day_of_week and clock_type", () => {
  const campaignId = "camp-xyz";

  test("initCampaignFlagsState includes clock_start_day_of_week and clock_type defaults", () => {
    const state = initCampaignFlagsState();
    expect(state.clock_start_day_of_week).toBe("monday");
    expect(state.clock_type).toBe("consequential-calendar");
    expect(state.guardrails).toBe(true);
    expect(state.difficulty).toBe("normal");
  });

  test("loadCampaignFlagsFlow parses clock_start_day_of_week from API", async () => {
    const { fetcher } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: {
        guardrails: true,
        on_rails: false,
        timed_events: true,
        difficulty: "hard",
        speed_multiplier: 2.0,
        clock_start_day_of_week: "friday",
      },
    });

    const result = await loadCampaignFlagsFlow(fetcher, campaignId);
    expect(result.flags.clock_start_day_of_week).toBe("friday");
    expect(result.flags.difficulty).toBe("hard");
    expect(result.flags.speed_multiplier).toBe(2.0);
    expect(result.calls).toEqual([`/api/campaigns/${campaignId}/flags`]);
  });

  test("loadCampaignFlagsFlow defaults clock_start_day_of_week when missing", async () => {
    const { fetcher } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: {
        guardrails: true,
        on_rails: false,
        timed_events: false,
        difficulty: "normal",
        speed_multiplier: 1.0,
      },
    });

    const result = await loadCampaignFlagsFlow(fetcher, campaignId);
    expect(result.flags.clock_start_day_of_week).toBe("monday");
  });

  test("setCampaignFlagFlow sends correct payload for clock_start_day_of_week", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: { ok: true, changed: ["clock_start_day_of_week"] },
    });

    const result = await setCampaignFlagFlow(fetcher, campaignId, "clock_start_day_of_week", "wednesday");
    expect(result.calls).toEqual([`/api/campaigns/${campaignId}/flags`]);
    expect(calls[0].init?.method).toBe("POST");
    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.clock_start_day_of_week).toBe("wednesday");
  });

  test("setCampaignFlagFlow works for other flags too", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: { ok: true, changed: ["difficulty"] },
    });

    await setCampaignFlagFlow(fetcher, campaignId, "difficulty", "impossible");
    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.difficulty).toBe("impossible");
  });

  test("loadCampaignFlagsFlow parses clock_type from API", async () => {
    const { fetcher } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: {
        guardrails: true,
        on_rails: false,
        timed_events: false,
        difficulty: "normal",
        speed_multiplier: 1.0,
        clock_start_day_of_week: "monday",
        clock_type: "individual-calendars",
      },
    });

    const result = await loadCampaignFlagsFlow(fetcher, campaignId);
    expect(result.flags.clock_type).toBe("individual-calendars");
  });

  test("loadCampaignFlagsFlow defaults clock_type when missing", async () => {
    const { fetcher } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: {
        guardrails: true,
        on_rails: false,
        timed_events: false,
        difficulty: "normal",
        speed_multiplier: 1.0,
      },
    });

    const result = await loadCampaignFlagsFlow(fetcher, campaignId);
    expect(result.flags.clock_type).toBe("consequential-calendar");
  });

  test("setCampaignFlagFlow sends correct payload for clock_type", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/flags`]: { ok: true, changed: ["clock_type"] },
    });

    await setCampaignFlagFlow(fetcher, campaignId, "clock_type", "loose-calendar");
    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.clock_type).toBe("loose-calendar");
  });
});
