import { setupWizardFlow } from "../src/flow_helpers";

describe("setup wizard flow", () => {
  test("checks status, starts setup, and sends message", async () => {
    const fetcher = jest.fn(async (url: string, init?: { method?: string; body?: string }) => {
      if (url.includes("/setup") && !url.includes("/start") && !url.includes("/message")) {
        return { in_setup: false, setup_phase: null };
      }
      if (url.includes("/setup/start")) {
        return { ok: true, message: "Setup wizard started." };
      }
      if (url.includes("/setup/message")) {
        return { ok: true, message: "Great choice! Building your world..." };
      }
      return {};
    });

    const result = await setupWizardFlow(fetcher, "camp-1", "dale-denton", "I want a sci-fi world.");

    expect(result.calls).toHaveLength(3);
    expect(fetcher).toHaveBeenCalledTimes(3);

    // Status check
    const status = result.status as { in_setup: boolean };
    expect(status.in_setup).toBe(false);

    // Start result
    const start = result.startResult as { ok: boolean };
    expect(start.ok).toBe(true);

    // Message result
    const msg = result.messageResult as { ok: boolean; message: string };
    expect(msg.ok).toBe(true);
    expect(msg.message).toContain("Building your world");
  });

  test("start payload includes actor_id and on_rails", async () => {
    const fetcher = jest.fn(async () => ({ in_setup: false, ok: true, message: "" }));

    await setupWizardFlow(fetcher, "camp-1", "dale", "hello");

    const startCall = fetcher.mock.calls[1] as unknown as [string, { body: string }];
    const body = JSON.parse(startCall[1].body);
    expect(body.actor_id).toBe("dale");
    expect(body.on_rails).toBe(false);
  });

  test("message payload includes actor_id and message", async () => {
    const fetcher = jest.fn(async () => ({ in_setup: false, ok: true, message: "" }));

    await setupWizardFlow(fetcher, "camp-1", "dale", "Make it dark.");

    const msgCall = fetcher.mock.calls[2] as unknown as [string, { body: string }];
    const body = JSON.parse(msgCall[1].body);
    expect(body.actor_id).toBe("dale");
    expect(body.message).toBe("Make it dark.");
  });
});
