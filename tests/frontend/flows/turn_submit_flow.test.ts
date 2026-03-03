import { buildTurnPayload, requireNonEmptyAction, submitTurnFlow } from "../src/flow_helpers";

describe("turn submit flow", () => {
  it("builds normalized payload and blocks empty action", () => {
    const payload = buildTurnPayload(" actor-1 ", " look ");
    expect(payload).toEqual({ actor_id: "actor-1", action: "look" });
    expect(requireNonEmptyAction(payload)).toBe(true);
    expect(requireNonEmptyAction(buildTurnPayload("actor-1", "   "))).toBe(false);
  });

  it("calls expected network surfaces after turn submit", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const payload = buildTurnPayload(" dale-denton ", " look ");
    const result = await submitTurnFlow(fetcher, "campaign-1", payload);

    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/turns",
      "/api/campaigns/campaign-1/map",
      "/api/campaigns/campaign-1/timers",
      "/api/campaigns/campaign-1/calendar",
      "/api/campaigns/campaign-1/roster",
      "/api/campaigns/campaign-1/player-state",
      "/api/campaigns/campaign-1/media",
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/debug/snapshot",
    ]);

    expect(seen).toEqual([
      "/api/campaigns/campaign-1/turns",
      "/api/campaigns/campaign-1/map?actor_id=dale-denton",
      "/api/campaigns/campaign-1/timers",
      "/api/campaigns/campaign-1/calendar",
      "/api/campaigns/campaign-1/roster",
      "/api/campaigns/campaign-1/player-state?actor_id=dale-denton",
      "/api/campaigns/campaign-1/media?actor_id=dale-denton",
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/debug/snapshot",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(9);
  });
});
