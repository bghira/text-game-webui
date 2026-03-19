import {
  initPaginationState,
  resetPagination,
  loadOlderTurnsFlow,
  HistoryTurn,
  PaginationState,
} from "../src/flow_helpers";

describe("infinite scroll pagination flow", () => {
  it("initPaginationState returns zeroed state", () => {
    const state = initPaginationState();
    expect(state).toEqual({ offset: 0, hasMore: false, loading: false });
  });

  it("resetPagination clears all fields", () => {
    const state = resetPagination();
    expect(state).toEqual({ offset: 0, hasMore: false, loading: false });
  });

  it("loadOlderTurnsFlow fetches and prepends older turns", async () => {
    const currentTurns: HistoryTurn[] = [
      { id: 4, kind: "narration", content: "Turn 4" },
      { id: 5, kind: "narration", content: "Turn 5" },
    ];
    const olderTurns: HistoryTurn[] = [
      { id: 2, kind: "narration", content: "Turn 2" },
      { id: 3, kind: "narration", content: "Turn 3" },
    ];
    const fetcher = jest.fn(async () => ({
      turns: olderTurns,
      has_more: true,
    }));
    // offset=2 means we already loaded the 2 newest turns
    const pagination: PaginationState = { offset: 2, hasMore: true, loading: false };

    const result = await loadOlderTurnsFlow(fetcher, "campaign-1", currentTurns, pagination);

    expect(result.calls).toEqual(["/api/campaigns/campaign-1/recent-turns?limit=30&offset=2"]);
    expect(result.turns).toHaveLength(4);
    expect(result.turns[0].id).toBe(2);
    expect(result.turns[1].id).toBe(3);
    expect(result.turns[2].id).toBe(4);
    expect(result.turns[3].id).toBe(5);
    // offset grows by older.length (2)
    expect(result.pagination.offset).toBe(4);
    expect(result.pagination.hasMore).toBe(true);
  });

  it("loadOlderTurnsFlow does nothing when hasMore is false", async () => {
    const fetcher = jest.fn(async () => ({ turns: [] }));
    const pagination: PaginationState = { offset: 0, hasMore: false, loading: false };

    const result = await loadOlderTurnsFlow(fetcher, "campaign-1", [], pagination);
    expect(result.calls).toEqual([]);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("loadOlderTurnsFlow does nothing when already loading", async () => {
    const fetcher = jest.fn(async () => ({ turns: [] }));
    const pagination: PaginationState = { offset: 0, hasMore: true, loading: true };

    const result = await loadOlderTurnsFlow(fetcher, "campaign-1", [], pagination);
    expect(result.calls).toEqual([]);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("loadOlderTurnsFlow sets hasMore to false when no turns returned", async () => {
    const fetcher = jest.fn(async () => ({ turns: [], has_more: false }));
    const currentTurns: HistoryTurn[] = [
      { id: 1, kind: "narration", content: "Turn 1" },
    ];
    const pagination: PaginationState = { offset: 1, hasMore: true, loading: false };

    const result = await loadOlderTurnsFlow(fetcher, "campaign-1", currentTurns, pagination);
    expect(result.pagination.hasMore).toBe(false);
    expect(result.turns).toEqual(currentTurns);
  });

  it("loadOlderTurnsFlow chains multiple pages correctly", async () => {
    const page1Turns: HistoryTurn[] = [
      { id: 3, kind: "narration", content: "Turn 3" },
    ];
    const page2Turns: HistoryTurn[] = [
      { id: 1, kind: "narration", content: "Turn 1" },
      { id: 2, kind: "narration", content: "Turn 2" },
    ];

    // Initial load fetched 2 turns (4 & 5), so offset starts at 2
    let currentTurns: HistoryTurn[] = [
      { id: 4, kind: "narration", content: "Turn 4" },
      { id: 5, kind: "narration", content: "Turn 5" },
    ];
    let pagination: PaginationState = { offset: 2, hasMore: true, loading: false };

    // First page load — requests offset=2, gets 1 turn
    const fetcher1 = jest.fn(async () => ({ turns: page1Turns, has_more: true }));
    const result1 = await loadOlderTurnsFlow(fetcher1, "c1", currentTurns, pagination);
    currentTurns = result1.turns;
    pagination = result1.pagination;
    expect(currentTurns).toHaveLength(3);
    expect(pagination.offset).toBe(3);
    expect(result1.calls).toEqual(["/api/campaigns/c1/recent-turns?limit=30&offset=2"]);

    // Second page load — requests offset=3, gets 2 turns
    const fetcher2 = jest.fn(async () => ({ turns: page2Turns, has_more: false }));
    const result2 = await loadOlderTurnsFlow(fetcher2, "c1", currentTurns, pagination);
    expect(result2.turns).toHaveLength(5);
    expect(result2.turns.map(t => t.id)).toEqual([1, 2, 3, 4, 5]);
    expect(result2.pagination.hasMore).toBe(false);
    expect(result2.pagination.offset).toBe(5);
    expect(result2.calls).toEqual(["/api/campaigns/c1/recent-turns?limit=30&offset=3"]);
  });
});
