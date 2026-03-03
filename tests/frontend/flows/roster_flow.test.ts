import { rosterManagementFlow } from "../src/flow_helpers";

describe("roster management flow", () => {
  it("calls expected surfaces for upsert/remove roster actions", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const result = await rosterManagementFlow(fetcher, "campaign-1", {
      slug: "arsipea-denton",
      name: "Arsipea Denton",
      location: "visitor-room-b",
      status: "active",
      player: false,
      fields: { appearance: "gray jumpsuit" },
    });

    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/roster/upsert",
      "/api/campaigns/campaign-1/roster",
      "/api/campaigns/campaign-1/roster/remove",
      "/api/campaigns/campaign-1/roster",
    ]);
    expect(seen).toEqual([
      "/api/campaigns/campaign-1/roster/upsert",
      "/api/campaigns/campaign-1/roster",
      "/api/campaigns/campaign-1/roster/remove",
      "/api/campaigns/campaign-1/roster",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});
