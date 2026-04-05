import {
  loadCalendarFlow,
  setCalendarVisibilityFlow,
  deleteCalendarEventFlow,
  CalendarState,
} from "../src/flow_helpers";

const CAMPAIGN = "camp-cal-1";

const INITIAL_CALENDAR: CalendarState = {
  game_time: { day: 1, hour: 9, minute: 0 },
  events: [
    {
      event_key: "concierge-callback:1:11",
      name: "Concierge callback",
      fire_day: 1,
      fire_hour: 11,
      description: "The concierge promised to call back before lunch.",
      scope: "targeted",
      target_players: ["rigby"],
    },
    {
      event_key: "market-opening:2:8",
      name: "Market opens",
      fire_day: 2,
      fire_hour: 8,
      scope: "global",
    },
  ],
};

function makeVisibilityResponse(eventKey: string, visibility: string): CalendarState {
  return {
    ...INITIAL_CALENDAR,
    events: INITIAL_CALENDAR.events.map((e) => {
      if (e.event_key !== eventKey) return e;
      if (visibility === "public") {
        const { target_players: _tp, ...rest } = e;
        return { ...rest, scope: "global" };
      }
      return { ...e, scope: "targeted", target_players: ["rigby"] };
    }),
  };
}

function makeDeleteResponse(eventKey: string): CalendarState {
  return {
    ...INITIAL_CALENDAR,
    events: INITIAL_CALENDAR.events.filter((e) => e.event_key !== eventKey),
  };
}

describe("Calendar flow", () => {
  test("loadCalendar returns events with game time", async () => {
    const fetcher = jest.fn().mockResolvedValue(INITIAL_CALENDAR);
    const { calls, result } = await loadCalendarFlow(fetcher, CAMPAIGN);
    expect(calls).toEqual([`/api/campaigns/${CAMPAIGN}/calendar`]);
    expect(result.game_time.day).toBe(1);
    expect(result.events).toHaveLength(2);
    expect(result.events[0].event_key).toBe("concierge-callback:1:11");
    expect(result.events[1].scope).toBe("global");
  });

  test("setCalendarVisibility toggles scope to public", async () => {
    const response = makeVisibilityResponse("concierge-callback:1:11", "public");
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await setCalendarVisibilityFlow(
      fetcher, CAMPAIGN, "concierge-callback:1:11", "public",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain("/visibility");
    const body = JSON.parse(
      (fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body,
    );
    expect(body.visibility).toBe("public");
    const updated = result.events.find((e) => e.event_key === "concierge-callback:1:11");
    expect(updated?.scope).toBe("global");
    expect(updated?.target_players).toBeUndefined();
  });

  test("setCalendarVisibility toggles scope to private", async () => {
    const response = makeVisibilityResponse("market-opening:2:8", "private");
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await setCalendarVisibilityFlow(
      fetcher, CAMPAIGN, "market-opening:2:8", "private",
    );
    const updated = result.events.find((e) => e.event_key === "market-opening:2:8");
    expect(updated?.scope).toBe("targeted");
    expect(updated?.target_players).toEqual(["rigby"]);
  });

  test("deleteCalendarEvent removes the event", async () => {
    const response = makeDeleteResponse("concierge-callback:1:11");
    const fetcher = jest.fn().mockResolvedValue(response);
    const { calls, result } = await deleteCalendarEventFlow(
      fetcher, CAMPAIGN, "concierge-callback:1:11",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain("/calendar/concierge-callback");
    expect((fetcher.mock.calls[0] as unknown as [string, { method: string }])[1].method).toBe("DELETE");
    expect(result.events).toHaveLength(1);
    expect(result.events[0].event_key).toBe("market-opening:2:8");
  });

  test("deleteCalendarEvent on last event returns empty list", async () => {
    const response: CalendarState = {
      game_time: { day: 1, hour: 9, minute: 0 },
      events: [],
    };
    const fetcher = jest.fn().mockResolvedValue(response);
    const { result } = await deleteCalendarEventFlow(
      fetcher, CAMPAIGN, "only-event:1:1",
    );
    expect(result.events).toHaveLength(0);
  });
});
