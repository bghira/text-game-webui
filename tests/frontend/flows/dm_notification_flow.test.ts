import {
  handleDmNotificationEvent,
  handleChannelNotificationEvent,
  DmNotificationEvent,
  ChannelNotificationEvent,
} from "../src/flow_helpers";

describe("DM notification WebSocket event handling", () => {
  test("valid dm_notification event returns stream entry with refresh flag", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      actor_id: "dale-denton",
      payload: {
        message: "You have a new message from Elizabeth.",
        actor_id: "dale-denton",
        refresh_sms_threads: true,
      },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.streamType).toBe("notice");
    expect(result!.message).toBe("You have a new message from Elizabeth.");
    expect(result!.refreshSmsThreads).toBe(true);
  });

  test("dm_notification without refresh flag does not request SMS refresh", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      payload: { message: "A notification." },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.refreshSmsThreads).toBe(false);
  });

  test("empty message returns null", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      payload: { message: "" },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).toBeNull();
  });

  test("missing message field returns null", () => {
    const event = {
      type: "dm_notification",
      payload: {},
    } as unknown as DmNotificationEvent;

    const result = handleDmNotificationEvent(event);
    expect(result).toBeNull();
  });

  test("notification without actor_id still works", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      payload: { message: "A direct message." },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.message).toBe("A direct message.");
  });
});

describe("Channel notification WebSocket event handling", () => {
  test("valid channel_notification returns stream entry", () => {
    const event: ChannelNotificationEvent = {
      type: "channel_notification",
      payload: { message: "A channel-wide announcement." },
    };

    const result = handleChannelNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.streamType).toBe("notice");
    expect(result!.message).toBe("A channel-wide announcement.");
  });

  test("empty channel message returns null", () => {
    const event: ChannelNotificationEvent = {
      type: "channel_notification",
      payload: { message: "" },
    };

    const result = handleChannelNotificationEvent(event);
    expect(result).toBeNull();
  });
});
