import {
  formatSceneSpeakerName,
  renderSceneBeatsAsText,
  populateTurnStreamFromHistory,
  type SceneOutput,
  type HistoryTurn,
} from "../src/flow_helpers";

describe("speaker format flow", () => {
  describe("formatSceneSpeakerName", () => {
    it("returns 'narrator' for empty input", () => {
      expect(formatSceneSpeakerName("")).toBe("narrator");
      expect(formatSceneSpeakerName(null)).toBe("narrator");
      expect(formatSceneSpeakerName(undefined)).toBe("narrator");
    });

    it("returns 'narrator' for literal narrator", () => {
      expect(formatSceneSpeakerName("narrator")).toBe("narrator");
      expect(formatSceneSpeakerName("Narrator")).toBe("narrator");
      expect(formatSceneSpeakerName("NARRATOR")).toBe("narrator");
    });

    it("converts slug-case to Title Case", () => {
      expect(formatSceneSpeakerName("dale-denton")).toBe("Dale Denton");
      expect(formatSceneSpeakerName("main-character")).toBe("Main Character");
      expect(formatSceneSpeakerName("a-b-c")).toBe("A B C");
    });

    it("preserves already-formatted names", () => {
      expect(formatSceneSpeakerName("Sasha")).toBe("Sasha");
      expect(formatSceneSpeakerName("Dr. Smith")).toBe("Dr. Smith");
    });

    it("does not convert mixed-case slugs", () => {
      expect(formatSceneSpeakerName("Dale-Denton")).toBe("Dale-Denton");
    });
  });

  describe("renderSceneBeatsAsText", () => {
    it("returns null for missing scene_output", () => {
      expect(renderSceneBeatsAsText(null, "fallback")).toBeNull();
      expect(renderSceneBeatsAsText(undefined, "fallback")).toBeNull();
    });

    it("returns null for empty beats array", () => {
      expect(renderSceneBeatsAsText({ beats: [] }, "fallback")).toBeNull();
    });

    it("returns null for beats with only empty text", () => {
      const scene: SceneOutput = {
        beats: [{ speaker: "narrator", text: "" }, { speaker: "narrator", text: "   " }],
      };
      expect(renderSceneBeatsAsText(scene, "fallback")).toBeNull();
    });

    it("extracts speaker and text from beats", () => {
      const scene: SceneOutput = {
        beats: [
          { speaker: "narrator", text: "The room is dark." },
          { speaker: "dale-denton", text: "\"Hello?\"" },
        ],
      };
      const result = renderSceneBeatsAsText(scene, "fallback");
      expect(result).not.toBeNull();
      expect(result!.parts).toHaveLength(2);
      expect(result!.parts[0]).toEqual({ speaker: "narrator", text: "The room is dark." });
      expect(result!.parts[1]).toEqual({ speaker: "Dale Denton", text: "\"Hello?\"" });
    });

    it("skips beats with no text", () => {
      const scene: SceneOutput = {
        beats: [
          { speaker: "narrator", text: "Visible." },
          { speaker: "ghost", text: "" },
          { speaker: "dale-denton", text: "Also visible." },
        ],
      };
      const result = renderSceneBeatsAsText(scene, "fallback");
      expect(result).not.toBeNull();
      expect(result!.parts).toHaveLength(2);
    });

    it("handles missing speaker field", () => {
      const scene: SceneOutput = {
        beats: [{ text: "Mysterious voice." }],
      };
      const result = renderSceneBeatsAsText(scene, "fallback");
      expect(result).not.toBeNull();
      expect(result!.parts[0].speaker).toBe("narrator");
    });
  });

  describe("populateTurnStreamFromHistory with scene_output", () => {
    it("passes scene_output from turn meta into entry meta", () => {
      const turns: HistoryTurn[] = [
        {
          kind: "narration",
          content: "The room is dark.",
          session_id: "sess-A",
          created_at: "2026-03-10T14:00:00Z",
          meta: {
            scene_output: {
              beats: [
                { speaker: "narrator", text: "The room is dark." },
                { speaker: "dale-denton", text: "\"Who's there?\"" },
              ],
            },
          },
        },
      ];
      const result = populateTurnStreamFromHistory(turns, "");
      expect(result.entries).toHaveLength(1);
      expect(result.entries[0].meta.scene_output).toBeDefined();
      const scene = result.entries[0].meta.scene_output as { beats: Array<{ speaker: string; text: string }> };
      expect(scene.beats).toHaveLength(2);
      expect(scene.beats[0].speaker).toBe("narrator");
      expect(scene.beats[1].speaker).toBe("dale-denton");
    });

    it("does not set scene_output when meta lacks beats", () => {
      const turns: HistoryTurn[] = [
        {
          kind: "narration",
          content: "Plain narration.",
          session_id: "sess-A",
          meta: {},
        },
      ];
      const result = populateTurnStreamFromHistory(turns, "");
      expect(result.entries[0].meta.scene_output).toBeUndefined();
    });

    it("does not set scene_output when beats is not an array", () => {
      const turns: HistoryTurn[] = [
        {
          kind: "narration",
          content: "Bad scene.",
          session_id: "sess-A",
          meta: { scene_output: { beats: "not-an-array" } },
        },
      ];
      const result = populateTurnStreamFromHistory(turns, "");
      expect(result.entries[0].meta.scene_output).toBeUndefined();
    });
  });
});
