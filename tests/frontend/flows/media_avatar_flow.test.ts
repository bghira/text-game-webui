import { mediaAvatarActionsFlow } from "../src/flow_helpers";

describe("media avatar actions flow", () => {
  it("calls expected surfaces for accept/decline avatar actions", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const result = await mediaAvatarActionsFlow(fetcher, "campaign-1", "dale-denton");
    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/media/avatar/accept",
      "/api/campaigns/campaign-1/media",
      "/api/campaigns/campaign-1/player-state",
      "/api/campaigns/campaign-1/media/avatar/decline",
      "/api/campaigns/campaign-1/media",
      "/api/campaigns/campaign-1/player-state",
    ]);
    expect(seen).toEqual([
      "/api/campaigns/campaign-1/media/avatar/accept",
      "/api/campaigns/campaign-1/media?actor_id=dale-denton",
      "/api/campaigns/campaign-1/player-state?actor_id=dale-denton",
      "/api/campaigns/campaign-1/media/avatar/decline",
      "/api/campaigns/campaign-1/media?actor_id=dale-denton",
      "/api/campaigns/campaign-1/player-state?actor_id=dale-denton",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(6);
  });
});
