import { campaignRulesFlow } from "../src/flow_helpers";

describe("campaign rules flow", () => {
  test("creates a rule and lists all rules", async () => {
    const fetcher = jest.fn(async (url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === "POST") {
        return { ok: true, key: "combat-style", created: true, old_value: "", new_value: "Always describe consequences." };
      }
      return {
        document_key: "campaign-rulebook",
        rules: [{ key: "combat-style", value: "Always describe consequences." }],
      };
    });

    const result = await campaignRulesFlow(fetcher, "camp-1", {
      key: "combat-style",
      value: "Always describe consequences.",
    });

    expect(result.calls).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(2);

    // Verify create payload
    const createCall = fetcher.mock.calls[0] as unknown as [string, { body: string }];
    const createBody = JSON.parse(createCall[1].body);
    expect(createBody.key).toBe("combat-style");
    expect(createBody.value).toBe("Always describe consequences.");

    // Verify list response
    const listResult = result.listResult as { rules: Array<{ key: string; value: string }> };
    expect(listResult.rules).toHaveLength(1);
    expect(listResult.rules[0].key).toBe("combat-style");
  });

  test("create result includes created flag", async () => {
    const fetcher = jest.fn(async () => ({
      ok: true,
      key: "tone",
      created: true,
      old_value: "",
      new_value: "dark",
    }));

    const result = await campaignRulesFlow(fetcher, "camp-1", {
      key: "tone",
      value: "dark",
    });

    const createResult = result.createResult as { ok: boolean; created: boolean };
    expect(createResult.ok).toBe(true);
    expect(createResult.created).toBe(true);
  });
});
