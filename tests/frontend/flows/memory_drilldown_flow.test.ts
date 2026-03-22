import {
  memorySearchDrilldownFlow,
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

describe("memory search drill-down flow", () => {
  const campaignId = "camp-abc";

  test("basic search without turn IDs sends no search_within_turn_ids", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/memory/search`]: { hits: [] },
    });

    const result = await memorySearchDrilldownFlow(fetcher, campaignId, {
      queries: ["dragon"],
      category: null,
    });

    expect(result.calls).toEqual([`/api/campaigns/${campaignId}/memory/search`]);
    expect(calls).toHaveLength(1);
    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.queries).toEqual(["dragon"]);
    expect(parsed.category).toBeNull();
    expect(parsed.search_within_turn_ids).toBeUndefined();
  });

  test("search with turn IDs includes search_within_turn_ids in payload", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/memory/search`]: {
        hits: [{ source: "curated", term: "dragon", memory: "A large dragon", score: 0.9 }],
        turn_hits: [{ id: 5, kind: "narrator", content: "The dragon roars" }],
      },
    });

    const result = await memorySearchDrilldownFlow(fetcher, campaignId, {
      queries: ["dragon"],
      category: "creature",
      search_within_turn_ids: [5, 10, 15],
    });

    expect(result.calls).toEqual([`/api/campaigns/${campaignId}/memory/search`]);
    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.queries).toEqual(["dragon"]);
    expect(parsed.category).toBe("creature");
    expect(parsed.search_within_turn_ids).toEqual([5, 10, 15]);
  });

  test("empty turn IDs array is omitted from payload", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/memory/search`]: { hits: [] },
    });

    await memorySearchDrilldownFlow(fetcher, campaignId, {
      queries: ["test"],
      search_within_turn_ids: [],
    });

    const parsed = JSON.parse(calls[0].init?.body ?? "{}");
    expect(parsed.search_within_turn_ids).toBeUndefined();
  });

  test("POST method is used", async () => {
    const { fetcher, calls } = makeFetcher({
      [`/api/campaigns/${campaignId}/memory/search`]: { hits: [] },
    });

    await memorySearchDrilldownFlow(fetcher, campaignId, {
      queries: ["test"],
    });

    expect(calls[0].init?.method).toBe("POST");
  });
});
