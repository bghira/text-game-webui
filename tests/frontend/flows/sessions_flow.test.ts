import { sessionManagementFlow } from "../src/flow_helpers";

describe("session management flow", () => {
  it("calls expected network surfaces for create/list/patch/list", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const result = await sessionManagementFlow(
      fetcher,
      "campaign-1",
      {
        surface: "discord_thread",
        surface_key: "discord:guild-1:thread-9",
        surface_guild_id: "guild-1",
        surface_channel_id: "channel-2",
        surface_thread_id: "thread-9",
        enabled: true,
        metadata: { active_campaign_id: "campaign-1" },
      },
      {
        session_id: "session-abc",
        enabled: false,
        metadata: { note: "disabled for maintenance" },
      },
    );

    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/sessions/session-abc",
      "/api/campaigns/campaign-1/sessions",
    ]);
    expect(seen).toEqual([
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/sessions",
      "/api/campaigns/campaign-1/sessions/session-abc",
      "/api/campaigns/campaign-1/sessions",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});
