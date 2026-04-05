import {
  playerProgressionFlow,
  renamePlayerFlow,
  levelUpFlow,
} from "../src/flow_helpers";

describe("player progression flow", () => {
  test("fetches statistics and attributes", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url.includes("/player-statistics")) {
        return {
          actor_id: "dale-denton",
          messages_sent: 42,
          timers_averted: 3,
          timers_missed: 1,
          attention_hours: 8.5,
        };
      }
      if (url.includes("/player-attributes")) {
        return {
          actor_id: "dale-denton",
          level: 3,
          attributes: { strength: 5, charisma: 7 },
          total_points: 20,
          points_spent: 12,
          xp_needed_for_next: 200,
        };
      }
      return {};
    });

    const result = await playerProgressionFlow(fetcher, "camp-1", "dale-denton");

    expect(result.calls).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(2);

    const stats = result.stats as { actor_id: string; messages_sent: number };
    expect(stats.actor_id).toBe("dale-denton");
    expect(stats.messages_sent).toBe(42);

    const attrs = result.attributes as { level: number; total_points: number };
    expect(attrs.level).toBe(3);
    expect(attrs.total_points).toBe(20);
  });

  test("stats URL includes encoded actor_id", async () => {
    const urls: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      urls.push(url);
      return {};
    });

    await playerProgressionFlow(fetcher, "camp-1", "actor with spaces");
    expect(urls[0]).toContain("actor_id=actor%20with%20spaces");
  });
});

describe("rename player flow", () => {
  test("sends rename request with correct payload", async () => {
    const fetcher = jest.fn(async () => ({
      ok: true,
      actor_id: "dale-denton",
      old_name: "dale-denton",
      name: "Dale the Brave",
    }));

    const result = await renamePlayerFlow(fetcher, "camp-1", "dale-denton", "Dale the Brave");

    expect(result.calls).toHaveLength(1);
    const call = fetcher.mock.calls[0] as unknown as [string, { body: string }];
    const body = JSON.parse(call[1].body);
    expect(body.actor_id).toBe("dale-denton");
    expect(body.name).toBe("Dale the Brave");

    const res = result.result as { ok: boolean; name: string };
    expect(res.ok).toBe(true);
    expect(res.name).toBe("Dale the Brave");
  });
});

describe("level up flow", () => {
  test("sends level-up request", async () => {
    const fetcher = jest.fn(async () => ({
      ok: true,
      new_level: 4,
    }));

    const result = await levelUpFlow(fetcher, "camp-1", "dale-denton");

    expect(result.calls).toHaveLength(1);
    const call = fetcher.mock.calls[0] as unknown as [string, { body: string }];
    const body = JSON.parse(call[1].body);
    expect(body.actor_id).toBe("dale-denton");
  });
});
