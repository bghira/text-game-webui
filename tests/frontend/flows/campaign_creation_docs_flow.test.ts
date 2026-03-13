import {
  campaignCreationWithDocsFlow,
  type FileEntry,
} from "../src/flow_helpers";

describe("campaign creation with documents flow", () => {
  it("creates campaign, ingests files, and starts setup wizard", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-1", name: "Dragon Quest" } };
      }
      return { ok: true };
    });

    const files: FileEntry[] = [
      { name: "lore.txt", text: "The ancient kingdom...", status: "ready" },
      { name: "characters.md", text: "Sir Galahad is...", status: "ready" },
    ];

    const result = await campaignCreationWithDocsFlow(
      fetcher, "Dragon Quest", "dale", files, false,
    );

    expect(result.calls).toEqual([
      "/api/campaigns",
      "/api/campaigns/new-camp-1/source-materials/digest",
      "/api/campaigns/new-camp-1/source-materials/digest",
      "/api/campaigns/new-camp-1/setup/start",
    ]);
    expect(result.campaignId).toBe("new-camp-1");
    expect(result.failedFiles).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(4);

    // Verify setup/start was called with combined text
    const setupCall = fetcher.mock.calls[3] as unknown as [string, { body: string }];
    const setupBody = JSON.parse(setupCall[1].body);
    expect(setupBody.actor_id).toBe("dale");
    expect(setupBody.on_rails).toBe(false);
    expect(setupBody.attachment_text).toContain("The ancient kingdom...");
    expect(setupBody.attachment_text).toContain("Sir Galahad is...");
    expect(setupBody.attachment_text).toContain("---");
  });

  it("skips setup wizard when no files are provided", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-2", name: "Solo Quest" } };
      }
      return { ok: true };
    });

    const result = await campaignCreationWithDocsFlow(
      fetcher, "Solo Quest", "ripley", [], true,
    );

    expect(result.calls).toEqual(["/api/campaigns"]);
    expect(result.campaignId).toBe("new-camp-2");
    expect(result.failedFiles).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("skips files with empty text", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-3", name: "Test" } };
      }
      return { ok: true };
    });

    const files: FileEntry[] = [
      { name: "empty.txt", text: "", status: "ready" },
      { name: "whitespace.txt", text: "   ", status: "ready" },
      { name: "valid.txt", text: "Real content", status: "ready" },
    ];

    const result = await campaignCreationWithDocsFlow(
      fetcher, "Test", "dale", files, false,
    );

    // Only the valid file should trigger digest + setup
    expect(result.calls).toEqual([
      "/api/campaigns",
      "/api/campaigns/new-camp-3/source-materials/digest",
      "/api/campaigns/new-camp-3/setup/start",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("tracks failed files and still starts setup with successful ones", async () => {
    let callCount = 0;
    const fetcher = jest.fn(async (url: string) => {
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-4", name: "Mixed" } };
      }
      if (url.includes("/source-materials/digest")) {
        callCount++;
        if (callCount === 2) {
          throw new Error("Digest failed");
        }
      }
      return { ok: true };
    });

    const files: FileEntry[] = [
      { name: "good.txt", text: "Good content", status: "ready" },
      { name: "bad.txt", text: "Bad content", status: "ready" },
      { name: "also-good.txt", text: "More content", status: "ready" },
    ];

    const result = await campaignCreationWithDocsFlow(
      fetcher, "Mixed", "dale", files, true,
    );

    expect(result.failedFiles).toEqual(["bad.txt"]);
    // Still calls setup with the two successful texts
    expect(result.calls).toContain("/api/campaigns/new-camp-4/setup/start");
    expect(fetcher).toHaveBeenCalledTimes(5); // create + 3 digest + 1 setup

    // Verify setup was called with on_rails: true
    const setupCall = fetcher.mock.calls.find(
      (c: unknown[]) => (c[0] as string).includes("/setup/start"),
    ) as unknown as [string, { body: string }];
    const setupBody = JSON.parse(setupCall[1].body);
    expect(setupBody.on_rails).toBe(true);
    // Combined text should NOT include the failed file's content
    expect(setupBody.attachment_text).toContain("Good content");
    expect(setupBody.attachment_text).toContain("More content");
    expect(setupBody.attachment_text).not.toContain("Bad content");
  });

  it("skips setup wizard when all file digests fail", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-5", name: "AllFail" } };
      }
      if (url.includes("/source-materials/digest")) {
        throw new Error("Digest failed");
      }
      return { ok: true };
    });

    const files: FileEntry[] = [
      { name: "fail1.txt", text: "Content 1", status: "ready" },
      { name: "fail2.txt", text: "Content 2", status: "ready" },
    ];

    const result = await campaignCreationWithDocsFlow(
      fetcher, "AllFail", "dale", files, false,
    );

    expect(result.failedFiles).toEqual(["fail1.txt", "fail2.txt"]);
    // No setup/start call since all digests failed
    expect(result.calls).toEqual([
      "/api/campaigns",
      "/api/campaigns/new-camp-5/source-materials/digest",
      "/api/campaigns/new-camp-5/source-materials/digest",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("strips file extension for document_label", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url === "/api/campaigns") {
        return { campaign: { id: "new-camp-6", name: "Labels" } };
      }
      return { ok: true };
    });

    const files: FileEntry[] = [
      { name: "world-lore.txt", text: "Lore text", status: "ready" },
      { name: "characters.notes.md", text: "Characters", status: "ready" },
    ];

    await campaignCreationWithDocsFlow(
      fetcher, "Labels", "dale", files, false,
    );

    // Check digest calls have correct document_label
    const digestCalls = fetcher.mock.calls.filter(
      (c: unknown[]) => (c[0] as string).includes("/source-materials/digest"),
    ) as unknown as Array<[string, { body: string }]>;
    expect(JSON.parse(digestCalls[0][1].body).document_label).toBe("world-lore");
    expect(JSON.parse(digestCalls[1][1].body).document_label).toBe("characters.notes");
  });
});
