import { personaFlow } from "../src/flow_helpers";

describe("persona flow", () => {
  test("gets and sets campaign persona", async () => {
    const fetcher = jest.fn(async (_url: string, init?: { method?: string; body?: string }) => {
      if (!init?.method || init.method === "GET") {
        return { persona: "A wry narrator.", source: "default" };
      }
      return { ok: true };
    });

    const result = await personaFlow(fetcher, "camp-1", "A sardonic AI overlord.");

    expect(result.calls).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(2);

    // Verify GET
    const getResult = result.getResult as { persona: string; source: string };
    expect(getResult.persona).toBe("A wry narrator.");
    expect(getResult.source).toBe("default");

    // Verify SET payload
    const setCall = fetcher.mock.calls[1] as unknown as [string, { body: string }];
    const setBody = JSON.parse(setCall[1].body);
    expect(setBody.persona).toBe("A sardonic AI overlord.");

    // Verify SET result
    const setResult = result.setResult as { ok: boolean };
    expect(setResult.ok).toBe(true);
  });

  test("calls correct URLs for campaign", async () => {
    const urls: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      urls.push(url);
      return { persona: "test", ok: true };
    });

    await personaFlow(fetcher, "my-campaign", "New persona");

    expect(urls[0]).toBe("/api/campaigns/my-campaign/persona");
    expect(urls[1]).toBe("/api/campaigns/my-campaign/persona");
  });
});
