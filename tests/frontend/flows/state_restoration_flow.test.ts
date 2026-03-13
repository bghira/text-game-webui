import {
  populateTurnStreamFromHistory,
  resolveRestoredSelection,
  type HistoryTurn,
  type Campaign,
  type Session,
} from "../src/flow_helpers";

describe("state restoration flow", () => {
  const campaigns: Campaign[] = [
    { id: "camp-1", name: "Dragon Quest", actor_id: "dale" },
    { id: "camp-2", name: "Space Odyssey", actor_id: "ripley" },
  ];
  const sessions: Session[] = [
    { id: "sess-A", surface_key: "webui:camp-1:shared" },
    { id: "sess-B", surface_key: "webui:camp-1:private" },
  ];

  describe("resolveRestoredSelection", () => {
    it("restores campaign and session when both are valid", () => {
      const result = resolveRestoredSelection("camp-1", "sess-A", campaigns, sessions);
      expect(result).toEqual({ campaignId: "camp-1", sessionId: "sess-A" });
    });

    it("restores campaign but not session when session id is invalid", () => {
      const result = resolveRestoredSelection("camp-1", "sess-GONE", campaigns, sessions);
      expect(result).toEqual({ campaignId: "camp-1", sessionId: null });
    });

    it("restores campaign but not session when session id is null", () => {
      const result = resolveRestoredSelection("camp-1", null, campaigns, sessions);
      expect(result).toEqual({ campaignId: "camp-1", sessionId: null });
    });

    it("returns null for both when campaign id is invalid", () => {
      const result = resolveRestoredSelection("camp-GONE", "sess-A", campaigns, sessions);
      expect(result).toEqual({ campaignId: null, sessionId: null });
    });

    it("returns null for both when campaign id is null", () => {
      const result = resolveRestoredSelection(null, null, campaigns, sessions);
      expect(result).toEqual({ campaignId: null, sessionId: null });
    });

    it("returns null for both when campaigns list is empty", () => {
      const result = resolveRestoredSelection("camp-1", "sess-A", [], sessions);
      expect(result).toEqual({ campaignId: null, sessionId: null });
    });
  });

  describe("populateTurnStreamFromHistory", () => {
    const turns: HistoryTurn[] = [
      { kind: "narration", content: "You enter the cave.", session_id: "sess-A", created_at: "2026-03-10T14:00:00Z" },
      { kind: "action_response", content: "The torch flickers.", session_id: "sess-A", created_at: "2026-03-10T14:01:00Z" },
      { kind: "system", content: "System event", session_id: "sess-A", created_at: "2026-03-10T14:02:00Z" },
      { kind: "narration", content: "Private whisper.", session_id: "sess-B", created_at: "2026-03-10T14:03:00Z" },
      { kind: "narration", content: "Another cave turn.", session_id: "sess-A", created_at: "2026-03-10T14:04:00Z", meta: { game_time: { day: 2, hour: 14, minute: 0 } } },
    ];

    it("hydrates only narration and action_response turns", () => {
      const result = populateTurnStreamFromHistory(turns, "");
      expect(result.entries).toHaveLength(4);
      expect(result.entries.every(e => e.type === "narrator")).toBe(true);
      expect(result.turnCounter).toBe(4);
    });

    it("filters turns by selectedSessionId when set", () => {
      const result = populateTurnStreamFromHistory(turns, "sess-A");
      expect(result.entries).toHaveLength(3);
      expect(result.entries.map(e => e.text)).toEqual([
        "You enter the cave.",
        "The torch flickers.",
        "Another cave turn.",
      ]);
      expect(result.turnCounter).toBe(3);
    });

    it("excludes turns from other sessions", () => {
      const result = populateTurnStreamFromHistory(turns, "sess-B");
      expect(result.entries).toHaveLength(1);
      expect(result.entries[0].text).toBe("Private whisper.");
    });

    it("extracts game_time from meta", () => {
      const result = populateTurnStreamFromHistory(turns, "sess-A");
      const lastEntry = result.entries[result.entries.length - 1];
      expect(lastEntry.meta._game_time).toEqual({ day: 2, hour: 14, minute: 0 });
      expect(result.gameTime).toEqual({ day: 2, hour: 14, minute: 0 });
    });

    it("returns empty entries for empty recentTurns", () => {
      const result = populateTurnStreamFromHistory([], "sess-A");
      expect(result.entries).toHaveLength(0);
      expect(result.turnCounter).toBe(0);
    });

    it("shows [No content] for turns with empty content", () => {
      const emptyTurns: HistoryTurn[] = [
        { kind: "narration", content: "", session_id: "sess-A" },
      ];
      const result = populateTurnStreamFromHistory(emptyTurns, "");
      expect(result.entries[0].text).toBe("[No content]");
    });

    it("includes turns without session_id regardless of filter", () => {
      const turnsNoSession: HistoryTurn[] = [
        { kind: "narration", content: "No session turn." },
        { kind: "narration", content: "Session turn.", session_id: "sess-A" },
      ];
      const result = populateTurnStreamFromHistory(turnsNoSession, "sess-A");
      expect(result.entries).toHaveLength(2);
    });
  });
});
