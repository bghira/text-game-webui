export type TurnPayload = {
  actor_id: string;
  action: string;
};

export function buildTurnPayload(actorId: string, action: string): TurnPayload {
  return {
    actor_id: actorId.trim(),
    action: action.trim(),
  };
}

export function requireNonEmptyAction(payload: TurnPayload): boolean {
  return payload.action.length > 0;
}
