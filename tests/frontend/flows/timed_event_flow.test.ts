import {
  loadTimersFlow,
  buildTimedEventWsPayload,
  buildTurnProgressWsPayload,
  submitButtonLabel,
  recoverCompletedTurnAfterReconnectState,
  summarizeTimers,
  TimersResult,
} from "../src/flow_helpers";

const CAMPAIGN = "camp-timed-1";
const NOW = new Date("2026-03-30T13:55:00Z");

describe("Timed event UX", () => {
  test("loadTimers computes active timer count and label", async () => {
    const response: TimersResult = {
      active_count: 1,
      timers: [
        {
          id: "t-1",
          status: "scheduled_bound",
          event_text: "Goblin ambush",
          interruptible: true,
          due_at: "2026-03-30T14:00:00Z",
          fired_at: null,
          cancelled_at: null,
          created_at: "2026-03-30T13:50:00Z",
          updated_at: "2026-03-30T13:50:00Z",
          meta: {},
        },
        {
          id: "t-2",
          status: "fired",
          event_text: "Old event",
          interruptible: false,
          due_at: "2026-03-29T10:00:00Z",
          fired_at: "2026-03-29T10:00:05Z",
          cancelled_at: null,
          created_at: "2026-03-29T09:50:00Z",
          updated_at: "2026-03-29T10:00:05Z",
          meta: {},
        },
      ],
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, activeCount, activeLabel } = await loadTimersFlow(
      fetcher,
      CAMPAIGN,
      { now: NOW },
    );

    expect(calls).toEqual([`/api/campaigns/${CAMPAIGN}/timers`]);
    expect(activeCount).toBe(1);
    expect(activeLabel).toContain("Goblin ambush");
    expect(activeLabel).toContain("fires in");
  });

  test("loadTimers with no active timers returns zero count and empty label", async () => {
    const response: TimersResult = {
      active_count: 0,
      timers: [
        {
          id: "t-3",
          status: "fired",
          event_text: "Past event",
          interruptible: false,
          due_at: null,
          fired_at: "2026-03-29T10:00:00Z",
          cancelled_at: null,
          created_at: "2026-03-29T09:50:00Z",
          updated_at: "2026-03-29T10:00:00Z",
          meta: {},
        },
      ],
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { activeCount, activeLabel } = await loadTimersFlow(
      fetcher,
      CAMPAIGN,
      { now: NOW },
    );

    expect(activeCount).toBe(0);
    expect(activeLabel).toBe("");
  });

  test("loadTimers ignores scheduled timers whose due time has passed", async () => {
    const response: TimersResult = {
      active_count: 1,
      timers: [
        {
          id: "t-stale",
          status: "scheduled_bound",
          event_text: "Stale event",
          interruptible: false,
          due_at: "2026-03-30T13:54:00Z",
          fired_at: null,
          cancelled_at: null,
          created_at: "2026-03-30T13:40:00Z",
          updated_at: "2026-03-30T13:40:00Z",
          meta: {},
        },
      ],
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { activeCount, activeLabel } = await loadTimersFlow(
      fetcher,
      CAMPAIGN,
      { now: NOW },
    );

    expect(activeCount).toBe(0);
    expect(activeLabel).toBe("");
  });

  test("realtime timers payload updates the same visible active timer summary", () => {
    const payload: TimersResult = {
      active_count: 1,
      timers: [
        {
          id: "t-ws",
          status: "scheduled_unbound",
          event_text: "Alarm trip",
          interruptible: true,
          due_at: "2026-03-30T14:10:00",
          fired_at: null,
          cancelled_at: null,
          created_at: "2026-03-30T13:55:00Z",
          updated_at: "2026-03-30T13:55:00Z",
          meta: {},
        },
      ],
    };

    const summary = summarizeTimers(payload, { now: NOW });

    expect(summary.activeCount).toBe(1);
    expect(summary.activeLabel).toContain("Alarm trip");
    expect(summary.activeLabel).toContain("fires in");
  });

  test("buildTimedEventWsPayload creates correct structure", () => {
    const msg = buildTimedEventWsPayload(
      "The goblins spring from the bushes!",
      "actor-42",
    );
    expect(msg.type).toBe("timed_event");
    expect(msg.actor_id).toBe("actor-42");
    expect(msg.payload.narration).toBe(
      "The goblins spring from the bushes!",
    );
  });

  test("buildTurnProgressWsPayload creates correct structure", () => {
    const msg = buildTurnProgressWsPayload("thinking", {
      actor_id: "a1",
      session_id: "s1",
    });
    expect(msg.type).toBe("turn_progress");
    expect(msg.payload.phase).toBe("thinking");
    expect(msg.actor_id).toBe("a1");
  });

  test("submit button shows Queue when timed event in progress", () => {
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: false,
        timedEventInProgress: true,
        queuedCount: 0,
      }),
    ).toBe("Queue");
  });

  test("submit button shows Queue(N) with queued actions during timed event", () => {
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: false,
        timedEventInProgress: true,
        queuedCount: 2,
      }),
    ).toBe("Queue (2)");
  });

  test("submit button shows Submit when no timed event", () => {
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: false,
        timedEventInProgress: false,
        queuedCount: 0,
      }),
    ).toBe("Submit");
  });

  test("submit button shows Queue when already submitting (not timed event)", () => {
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: true,
        timedEventInProgress: false,
        queuedCount: 0,
      }),
    ).toBe("Queue");
  });

  test("image generation does not block queued turn affordance", () => {
    expect(
      submitButtonLabel({
        imageGenerating: 1,
        submitting: false,
        timedEventInProgress: true,
        queuedCount: 0,
      }),
    ).toBe("Queue");
  });

  test("reconnect recovery clears stuck submission state and drains queued action", () => {
    const recovered = recoverCompletedTurnAfterReconnectState({
      queuedCount: 1,
    });

    expect(recovered.submitting).toBe(false);
    expect(recovered.timedEventInProgress).toBe(false);
    expect(recovered.activeProgressLabel).toBe("");
    expect(recovered.shouldDrainQueue).toBe(true);
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: recovered.submitting,
        timedEventInProgress: recovered.timedEventInProgress,
        queuedCount: 1,
      }),
    ).toBe("Submit");
  });

  test("full timed event lifecycle: timer active → progress → event fires → cleared", async () => {
    // Step 1: Timer is active — loadTimers shows active indicator
    const activeTimerResponse: TimersResult = {
      active_count: 1,
      timers: [
        {
          id: "t-lifecycle",
          status: "scheduled_bound",
          event_text: "Earthquake",
          interruptible: false,
          due_at: "2026-03-30T15:00:00Z",
          fired_at: null,
          cancelled_at: null,
          created_at: "2026-03-30T14:50:00Z",
          updated_at: "2026-03-30T14:50:00Z",
          meta: {},
        },
      ],
    };
    const timerFetcher = jest.fn().mockResolvedValue(activeTimerResponse);
    const step1 = await loadTimersFlow(timerFetcher, CAMPAIGN, { now: NOW });
    expect(step1.activeCount).toBe(1);
    expect(step1.activeLabel).toContain("Earthquake");

    // Step 2: Turn progress arrives — simulating the engine processing the timer
    const progressMsg = buildTurnProgressWsPayload("thinking");
    // When !submitting and turn_progress arrives, timedEventInProgress should be set
    let timedEventInProgress = false;
    // Simulate the WS handler logic
    if (progressMsg.type === "turn_progress" && progressMsg.payload) {
      timedEventInProgress = true;
    }
    expect(timedEventInProgress).toBe(true);
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: false,
        timedEventInProgress,
        queuedCount: 0,
      }),
    ).toBe("Queue");

    // Step 3: Timed event fires — narration delivered
    const eventMsg = buildTimedEventWsPayload(
      "The ground shakes violently!",
    );
    expect(eventMsg.payload.narration).toBe("The ground shakes violently!");
    // After receiving timed_event, the flag is cleared
    timedEventInProgress = false;
    expect(
      submitButtonLabel({
        imageGenerating: 0,
        submitting: false,
        timedEventInProgress,
        queuedCount: 0,
      }),
    ).toBe("Submit");

    // Step 4: Timers reload — now no active timers
    const clearedTimerResponse: TimersResult = {
      active_count: 0,
      timers: [
        {
          id: "t-lifecycle",
          status: "fired",
          event_text: "Earthquake",
          interruptible: false,
          due_at: "2026-03-30T15:00:00Z",
          fired_at: "2026-03-30T15:00:05Z",
          cancelled_at: null,
          created_at: "2026-03-30T14:50:00Z",
          updated_at: "2026-03-30T15:00:05Z",
          meta: {},
        },
      ],
    };
    const clearedFetcher = jest.fn().mockResolvedValue(clearedTimerResponse);
    const step4 = await loadTimersFlow(clearedFetcher, CAMPAIGN, { now: NOW });
    expect(step4.activeCount).toBe(0);
    expect(step4.activeLabel).toBe("");
  });
});
