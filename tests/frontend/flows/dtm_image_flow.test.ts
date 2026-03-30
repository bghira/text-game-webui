import {
  dtmImageGenerateFlow,
  dtmImageStatusFlow,
  dtmMediaDeliverFlow,
  DtmImageGenerateResult,
  DtmImageStatusResult,
  DtmMediaDeliverResult,
} from "../src/flow_helpers";

const CAMPAIGN = "camp-dtm-img-1";

describe("DTM image generation flow", () => {
  test("generate returns pending job with dtm backend", async () => {
    const response: DtmImageGenerateResult = {
      job_id: "dtm-job-abc",
      status: "pending",
      backend: "dtm",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await dtmImageGenerateFlow(
      fetcher,
      "A dark forest at twilight",
    );
    expect(calls).toEqual(["/api/image/generate"]);
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.prompt).toBe("A dark forest at twilight");
    expect(result.backend).toBe("dtm");
    expect(result.status).toBe("pending");
    expect(result.job_id).toBe("dtm-job-abc");
  });

  test("status poll returns pending then completed", async () => {
    const pending: DtmImageStatusResult = { status: "pending" };
    const completed: DtmImageStatusResult = {
      status: "completed",
      image_url: "/generated/abc123.png",
      image_id: "abc123",
    };
    const fetcher = jest
      .fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(completed);

    const poll1 = await dtmImageStatusFlow(fetcher, "dtm-job-abc");
    expect(poll1.result.status).toBe("pending");
    expect(poll1.calls[0]).toContain("/api/image/status/dtm-job-abc");

    const poll2 = await dtmImageStatusFlow(fetcher, "dtm-job-abc");
    expect(poll2.result.status).toBe("completed");
    expect(poll2.result.image_url).toBe("/generated/abc123.png");
  });

  test("media deliver callback stores image and returns local URL", async () => {
    const response: DtmMediaDeliverResult = {
      ok: true,
      image_url: "/generated/deadbeef.png",
      image_id: "deadbeef",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await dtmMediaDeliverFlow(fetcher, CAMPAIGN, {
      image_url: "https://dtm-host/images/scene123.png",
      prompt: "A dark forest at twilight",
      ref_type: "scene",
      actor_id: "12345",
      room_key: "dark-forest",
      job_id: "dtm-job-abc",
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain(`/campaigns/${CAMPAIGN}/media/deliver`);
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.image_url).toBe("https://dtm-host/images/scene123.png");
    expect(body.ref_type).toBe("scene");
    expect(body.job_id).toBe("dtm-job-abc");
    expect(result.ok).toBe(true);
    expect(result.image_url).toBe("/generated/deadbeef.png");
  });

  test("media deliver with base64 image data", async () => {
    const response: DtmMediaDeliverResult = {
      ok: true,
      image_url: "/generated/b64img.png",
      image_id: "b64img",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await dtmMediaDeliverFlow(fetcher, CAMPAIGN, {
      image_base64: "iVBORw0KGgo=",
      prompt: "An avatar portrait",
      ref_type: "avatar",
      actor_id: "67890",
    });

    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.image_base64).toBe("iVBORw0KGgo=");
    expect(body.ref_type).toBe("avatar");
    expect(result.ok).toBe(true);
  });

  test("full round-trip: generate → poll pending → deliver callback → poll completed", async () => {
    // Step 1: Submit generation
    const genResponse: DtmImageGenerateResult = {
      job_id: "roundtrip-001",
      status: "pending",
      backend: "dtm",
    };
    const genFetcher = jest.fn().mockResolvedValue(genResponse);
    const gen = await dtmImageGenerateFlow(genFetcher, "Castle at dawn");
    expect(gen.result.job_id).toBe("roundtrip-001");

    // Step 2: Poll — still pending
    const pendingFetcher = jest
      .fn()
      .mockResolvedValue({ status: "pending" } as DtmImageStatusResult);
    const poll1 = await dtmImageStatusFlow(pendingFetcher, "roundtrip-001");
    expect(poll1.result.status).toBe("pending");

    // Step 3: DTM delivers the image via callback
    const deliverResponse: DtmMediaDeliverResult = {
      ok: true,
      image_url: "/generated/castle.png",
      image_id: "castle",
    };
    const deliverFetcher = jest.fn().mockResolvedValue(deliverResponse);
    const deliver = await dtmMediaDeliverFlow(deliverFetcher, CAMPAIGN, {
      image_url: "https://gpu-worker/castle.png",
      prompt: "Castle at dawn",
      ref_type: "scene",
      room_key: "castle-entrance",
      job_id: "roundtrip-001",
    });
    expect(deliver.result.ok).toBe(true);

    // Step 4: Poll — now completed
    const completedFetcher = jest.fn().mockResolvedValue({
      status: "completed",
      image_url: "/generated/castle.png",
      image_id: "castle",
    } as DtmImageStatusResult);
    const poll2 = await dtmImageStatusFlow(completedFetcher, "roundtrip-001");
    expect(poll2.result.status).toBe("completed");
    expect(poll2.result.image_url).toBe("/generated/castle.png");
  });
});
