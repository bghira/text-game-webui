import {
  sessionHasUnseen,
  parseSessionLastSeen,
  type RecentTurn,
} from "../src/flow_helpers";

describe("unseen activity helpers", () => {
  describe("sessionHasUnseen", () => {
    const turns: RecentTurn[] = [
      { session_id: "sess-A", created_at: "2026-03-10T14:00:00Z" },
      { session_id: "sess-A", created_at: "2026-03-10T15:00:00Z" },
      { session_id: "sess-B", created_at: "2026-03-10T14:30:00Z" },
    ];

    it("returns false for the currently selected session", () => {
      expect(sessionHasUnseen("sess-A", "sess-A", undefined, turns)).toBe(false);
    });

    it("returns false for empty sessionId", () => {
      expect(sessionHasUnseen("", "sess-A", undefined, turns)).toBe(false);
    });

    it("returns true for never-visited session that has turns", () => {
      expect(sessionHasUnseen("sess-B", "sess-A", undefined, turns)).toBe(true);
    });

    it("returns false for never-visited session with no turns", () => {
      expect(sessionHasUnseen("sess-C", "sess-A", undefined, turns)).toBe(false);
    });

    it("returns true when a turn is newer than lastSeen", () => {
      expect(
        sessionHasUnseen("sess-A", "sess-B", "2026-03-10T13:00:00Z", turns),
      ).toBe(true);
    });

    it("returns false when all turns are older than lastSeen", () => {
      expect(
        sessionHasUnseen("sess-A", "sess-B", "2026-03-10T16:00:00Z", turns),
      ).toBe(false);
    });

    it("returns false when lastSeen equals the newest turn timestamp", () => {
      expect(
        sessionHasUnseen("sess-A", "sess-B", "2026-03-10T15:00:00Z", turns),
      ).toBe(false);
    });

    it("handles +00:00 suffix from Python datetime.isoformat()", () => {
      // Backend sends +00:00, client stores Z — both should parse correctly
      const pythonTurns: RecentTurn[] = [
        { session_id: "sess-X", created_at: "2026-03-10T14:30:00+00:00" },
      ];
      // lastSeen is JS-style Z, turn is Python-style +00:00, turn is newer
      expect(
        sessionHasUnseen("sess-X", "sess-Y", "2026-03-10T14:00:00Z", pythonTurns),
      ).toBe(true);
      // Same instant in both formats — should NOT be unseen
      expect(
        sessionHasUnseen("sess-X", "sess-Y", "2026-03-10T14:30:00Z", pythonTurns),
      ).toBe(false);
    });

    it("skips turns without created_at", () => {
      const noDateTurns: RecentTurn[] = [
        { session_id: "sess-A" },
      ];
      expect(
        sessionHasUnseen("sess-A", "sess-B", "2026-03-10T13:00:00Z", noDateTurns),
      ).toBe(false);
    });

    it("returns false for empty recentTurns", () => {
      expect(sessionHasUnseen("sess-A", "sess-B", "2026-03-10T13:00:00Z", [])).toBe(false);
    });
  });

  describe("parseSessionLastSeen", () => {
    it("returns parsed object for valid JSON object", () => {
      const raw = JSON.stringify({ "sess-A": "2026-03-10T14:00:00Z" });
      expect(parseSessionLastSeen(raw)).toEqual({ "sess-A": "2026-03-10T14:00:00Z" });
    });

    it("returns {} for null input", () => {
      expect(parseSessionLastSeen(null)).toEqual({});
    });

    it("returns {} for empty string", () => {
      expect(parseSessionLastSeen("")).toEqual({});
    });

    it("returns {} for JSON null", () => {
      expect(parseSessionLastSeen("null")).toEqual({});
    });

    it("returns {} for JSON array", () => {
      expect(parseSessionLastSeen("[1,2,3]")).toEqual({});
    });

    it("returns {} for JSON string", () => {
      expect(parseSessionLastSeen('"hello"')).toEqual({});
    });

    it("returns {} for invalid JSON", () => {
      expect(parseSessionLastSeen("{bad json")).toEqual({});
    });

    it("returns {} for JSON number", () => {
      expect(parseSessionLastSeen("42")).toEqual({});
    });
  });
});
