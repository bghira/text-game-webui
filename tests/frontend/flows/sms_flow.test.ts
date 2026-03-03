import { smsToolsFlow } from "../src/flow_helpers";

describe("sms tools flow", () => {
  it("calls expected surfaces for list/read/write", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return { ok: true };
    });

    const result = await smsToolsFlow(fetcher, "campaign-1", {
      wildcard: "*",
      thread: "saul",
      limit: 20,
      sender: "dale-denton",
      recipient: "saul-silver",
      message: "Need pickup now.",
    });

    expect(result.calls).toEqual([
      "/api/campaigns/campaign-1/sms/list",
      "/api/campaigns/campaign-1/sms/read",
      "/api/campaigns/campaign-1/sms/write",
    ]);
    expect(seen).toEqual([
      "/api/campaigns/campaign-1/sms/list",
      "/api/campaigns/campaign-1/sms/read",
      "/api/campaigns/campaign-1/sms/write",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
});
