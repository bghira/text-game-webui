import {
  smsDeleteThreadFlow,
  smsDeleteMessageFlow,
  smsEditMessageFlow,
  SmsDeleteThreadResult,
  SmsDeleteMessageResult,
  SmsEditMessageResult,
} from "../src/flow_helpers";

const CAMPAIGN = "camp-sms-edit-1";

describe("SMS edit and delete flows", () => {
  test("delete an entire thread", async () => {
    const response: SmsDeleteThreadResult = { ok: true, reason: "deleted" };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await smsDeleteThreadFlow(
      fetcher,
      CAMPAIGN,
      "merchant-guild",
    );
    expect(calls).toEqual([
      `/api/campaigns/${CAMPAIGN}/sms/delete-thread`,
    ]);
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.thread).toBe("merchant-guild");
    expect(result.ok).toBe(true);
  });

  test("delete thread not found", async () => {
    const response: SmsDeleteThreadResult = {
      ok: false,
      reason: "thread_not_found",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await smsDeleteThreadFlow(
      fetcher,
      CAMPAIGN,
      "nonexistent",
    );
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("thread_not_found");
  });

  test("delete a single message by index", async () => {
    const response: SmsDeleteMessageResult = { ok: true, reason: "deleted" };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await smsDeleteMessageFlow(
      fetcher,
      CAMPAIGN,
      "tavern-keeper",
      2,
    );
    expect(calls).toEqual([
      `/api/campaigns/${CAMPAIGN}/sms/delete-message`,
    ]);
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.thread).toBe("tavern-keeper");
    expect(body.message_index).toBe(2);
    expect(result.ok).toBe(true);
  });

  test("delete message not found", async () => {
    const response: SmsDeleteMessageResult = {
      ok: false,
      reason: "message_not_found",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await smsDeleteMessageFlow(
      fetcher,
      CAMPAIGN,
      "tavern-keeper",
      999,
    );
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("message_not_found");
  });

  test("edit a message", async () => {
    const response: SmsEditMessageResult = { ok: true, reason: "updated" };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await smsEditMessageFlow(
      fetcher,
      CAMPAIGN,
      "blacksmith",
      1,
      "The sword is ready for pickup tomorrow.",
    );
    expect(calls).toEqual([
      `/api/campaigns/${CAMPAIGN}/sms/edit-message`,
    ]);
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.thread).toBe("blacksmith");
    expect(body.message_index).toBe(1);
    expect(body.new_text).toBe("The sword is ready for pickup tomorrow.");
    expect(result.ok).toBe(true);
  });

  test("edit message not found", async () => {
    const response: SmsEditMessageResult = {
      ok: false,
      reason: "message_not_found",
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await smsEditMessageFlow(
      fetcher,
      CAMPAIGN,
      "blacksmith",
      999,
      "new text",
    );
    expect(result.ok).toBe(false);
  });

  test("full lifecycle: write → edit → delete message → delete thread", async () => {
    // Step 1: Delete a specific message (index 0)
    const deleteMsgResponse: SmsDeleteMessageResult = {
      ok: true,
      reason: "deleted",
    };
    const deleteMsgFetcher = jest.fn().mockResolvedValue(deleteMsgResponse);
    const step1 = await smsDeleteMessageFlow(
      deleteMsgFetcher,
      CAMPAIGN,
      "guard-captain",
      0,
    );
    expect(step1.result.ok).toBe(true);

    // Step 2: Edit message at new index 0
    const editResponse: SmsEditMessageResult = {
      ok: true,
      reason: "updated",
    };
    const editFetcher = jest.fn().mockResolvedValue(editResponse);
    const step2 = await smsEditMessageFlow(
      editFetcher,
      CAMPAIGN,
      "guard-captain",
      0,
      "Revised patrol orders.",
    );
    expect(step2.result.ok).toBe(true);

    // Step 3: Delete the entire thread
    const deleteThreadResponse: SmsDeleteThreadResult = {
      ok: true,
      reason: "deleted",
    };
    const deleteThreadFetcher = jest
      .fn()
      .mockResolvedValue(deleteThreadResponse);
    const step3 = await smsDeleteThreadFlow(
      deleteThreadFetcher,
      CAMPAIGN,
      "guard-captain",
    );
    expect(step3.result.ok).toBe(true);
  });
});
