import { memoryToolsFlow } from "../src/flow_helpers";

describe("memory tools flow", () => {
  it("calls expected surfaces for search/terms/turn/store", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const result = await memoryToolsFlow(fetcher, "campaign-1", {
      queries: ["room 420"],
      category: "char:dale-denton",
      wildcard: "char:*",
      turn_id: 42,
      store: {
        category: "char:dale-denton",
        term: "belmond",
        memory: "Booked room 420.",
      },
    });

    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/memory/search",
      "/api/campaigns/campaign-1/memory/terms",
      "/api/campaigns/campaign-1/memory/turn",
      "/api/campaigns/campaign-1/memory/store",
    ]);
    expect(seen).toEqual([
      "/api/campaigns/campaign-1/memory/search",
      "/api/campaigns/campaign-1/memory/terms",
      "/api/campaigns/campaign-1/memory/turn",
      "/api/campaigns/campaign-1/memory/store",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});
