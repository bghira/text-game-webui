import { buildTurnPayload, requireNonEmptyAction } from "../src/flow_helpers";

describe("turn submit flow", () => {
  it("builds normalized payload and blocks empty action", () => {
    const payload = buildTurnPayload(" actor-1 ", " look ");
    expect(payload).toEqual({ actor_id: "actor-1", action: "look" });
    expect(requireNonEmptyAction(payload)).toBe(true);
    expect(requireNonEmptyAction(buildTurnPayload("actor-1", "   "))).toBe(false);
  });
});
