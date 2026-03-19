import {
  rewindFromStreamFlow,
  populateTurnStreamFromHistory,
  HistoryTurn,
} from "../src/flow_helpers";

describe("rewind from turn stream flow", () => {
  it("entries include _backendTurnId from history", () => {
    const turns: HistoryTurn[] = [
      { id: 10, kind: "narration", content: "You look around.", created_at: "2026-01-01T00:00:00Z" },
      { id: 11, kind: "action_response", content: "Nothing happens.", created_at: "2026-01-01T00:01:00Z" },
    ];
    const result = populateTurnStreamFromHistory(turns, "");
    expect(result.entries).toHaveLength(2);
    expect(result.entries[0]._backendTurnId).toBe(10);
    expect(result.entries[1]._backendTurnId).toBe(11);
  });

  it("_backendTurnId is null when turn has no id", () => {
    const turns: HistoryTurn[] = [
      { kind: "narration", content: "Mystery turn." },
    ];
    const result = populateTurnStreamFromHistory(turns, "");
    expect(result.entries[0]._backendTurnId).toBeNull();
  });

  it("rewindFromStreamFlow POSTs to rewind endpoint and returns success", async () => {
    const calls: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      calls.push(url);
      return { ok: true };
    });

    const result = await rewindFromStreamFlow(fetcher, "campaign-1", 5);
    expect(result.calls).toEqual(["/api/campaigns/campaign-1/rewind?target_turn_id=5"]);
    expect(result.rewindOk).toBe(true);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/campaigns/campaign-1/rewind?target_turn_id=5",
      { method: "POST" },
    );
  });

  it("rewindFromStreamFlow rejects invalid turn IDs without calling API", async () => {
    const fetcher = jest.fn(async () => ({}));

    const zero = await rewindFromStreamFlow(fetcher, "campaign-1", 0);
    expect(zero.calls).toEqual([]);
    expect(zero.rewindOk).toBe(false);

    const negative = await rewindFromStreamFlow(fetcher, "campaign-1", -3);
    expect(negative.calls).toEqual([]);
    expect(negative.rewindOk).toBe(false);

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rewindFromStreamFlow reports failure when backend returns ok: false", async () => {
    const fetcher = jest.fn(async () => ({ ok: false, note: "Rewind not supported." }));

    const result = await rewindFromStreamFlow(fetcher, "campaign-1", 3);
    expect(result.rewindOk).toBe(false);
  });
});
