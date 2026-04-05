import { sourceMaterialsFlow } from "../src/flow_helpers";

describe("source materials flow", () => {
  test("lists, ingests, searches, browses, and digests source materials", async () => {
    const seen: { url: string; method?: string }[] = [];
    const fetcher = jest.fn(async (url: string, init?: { method?: string; body?: string }) => {
      seen.push({ url, method: init?.method });
      if (url.endsWith("/source-materials") && !init?.method) {
        return { documents: [] };
      }
      if (url.endsWith("/source-materials") && init?.method === "POST") {
        return { ok: true };
      }
      if (url.includes("/source-materials/search")) {
        return { results: [], query: "lore" };
      }
      if (url.includes("/source-materials/browse")) {
        return { keys: [] };
      }
      if (url.includes("/source-materials/digest")) {
        return { ok: true, chunks_stored: 3, document_key: "backstory" };
      }
      return {};
    });

    const result = await sourceMaterialsFlow(fetcher, "camp-1", {
      ingestText: "The kingdom was vast.",
      ingestLabel: "lore",
      searchQuery: "lore",
    });

    expect(result.calls).toHaveLength(5);
    expect(fetcher).toHaveBeenCalledTimes(5);

    // Verify correct endpoints hit
    expect(seen[0]).toEqual({ url: "/api/campaigns/camp-1/source-materials", method: undefined });
    expect(seen[1]).toEqual({ url: "/api/campaigns/camp-1/source-materials", method: "POST" });
    expect(seen[2]).toEqual({ url: "/api/campaigns/camp-1/source-materials/search", method: "POST" });
    expect(seen[3]).toEqual({ url: "/api/campaigns/camp-1/source-materials/browse", method: undefined });
    expect(seen[4]).toEqual({ url: "/api/campaigns/camp-1/source-materials/digest", method: "POST" });
  });

  test("ingest passes correct payload", async () => {
    const bodies: string[] = [];
    const fetcher = jest.fn(async (_url: string, init?: { method?: string; body?: string }) => {
      if (init?.body) bodies.push(init.body);
      return { ok: true, documents: [], results: [], keys: [] };
    });

    await sourceMaterialsFlow(fetcher, "camp-1", {
      ingestText: "Forest of Shadows",
      ingestLabel: "world-doc",
      searchQuery: "shadow",
    });

    // Check ingest payload
    const ingestBody = JSON.parse(bodies[0]);
    expect(ingestBody.text).toBe("Forest of Shadows");
    expect(ingestBody.document_label).toBe("world-doc");

    // Check search payload
    const searchBody = JSON.parse(bodies[1]);
    expect(searchBody.query).toBe("shadow");
    expect(searchBody.top_k).toBe(5);

    // Check digest payload
    const digestBody = JSON.parse(bodies[2]);
    expect(digestBody.text).toBe("Forest of Shadows");
    expect(digestBody.replace_document).toBe(true);
  });
});
