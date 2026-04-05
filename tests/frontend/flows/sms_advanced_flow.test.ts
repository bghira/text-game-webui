import { smsCancelFlow, smsScheduleFlow } from "../src/flow_helpers";

describe("SMS cancel flow", () => {
  test("sends cancel request and returns result", async () => {
    const fetcher = jest.fn(async () => ({ ok: true, cancelled: 3 }));

    const result = await smsCancelFlow(fetcher, "camp-1");

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/campaigns/camp-1/sms/cancel");

    const res = result.result as { ok: boolean; cancelled: number };
    expect(res.ok).toBe(true);
    expect(res.cancelled).toBe(3);
  });

  test("zero cancelled when no pending deliveries", async () => {
    const fetcher = jest.fn(async () => ({ ok: true, cancelled: 0 }));

    const result = await smsCancelFlow(fetcher, "camp-1");
    const res = result.result as { cancelled: number };
    expect(res.cancelled).toBe(0);
  });
});

describe("SMS schedule flow", () => {
  test("sends schedule request with correct payload", async () => {
    const fetcher = jest.fn(async () => ({ ok: true }));

    const result = await smsScheduleFlow(fetcher, "camp-1", {
      thread: "saul",
      sender: "dale-denton",
      recipient: "saul-silver",
      message: "Reminder: 5pm pickup.",
      delay_seconds: 300,
    });

    expect(result.calls).toHaveLength(1);
    expect(result.calls[0]).toBe("/api/campaigns/camp-1/sms/schedule");

    const call = fetcher.mock.calls[0] as unknown as [string, { body: string }];
    const body = JSON.parse(call[1].body);
    expect(body.thread).toBe("saul");
    expect(body.sender).toBe("dale-denton");
    expect(body.recipient).toBe("saul-silver");
    expect(body.message).toBe("Reminder: 5pm pickup.");
    expect(body.delay_seconds).toBe(300);
  });
});
