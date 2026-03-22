import {
  handleDmNotificationEvent,
  DmNotificationEvent,
} from "../src/flow_helpers";

describe("DM notification WebSocket event handling", () => {
  test("valid dm_notification event returns stream entry", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      actor_id: "dale-denton",
      payload: { message: "You have a new message from Elizabeth.", actor_id: "dale-denton" },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.streamType).toBe("notice");
    expect(result!.message).toBe("You have a new message from Elizabeth.");
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
    const event: DmNotificationEvent = {
      type: "dm_notification",
      payload: { message: "" },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).toBeNull();
  });

  test("notification without actor_id still works", () => {
    const event: DmNotificationEvent = {
      type: "dm_notification",
      payload: { message: "A channel-wide announcement." },
    };

    const result = handleDmNotificationEvent(event);
    expect(result).not.toBeNull();
    expect(result!.message).toBe("A channel-wide announcement.");
  });
});
