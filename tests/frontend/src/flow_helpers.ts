export type TurnPayload = {
  actor_id: string;
  action: string;
  session_id?: string | null;
};

export type DiagnosticsState = {
  ws_state: "disconnected" | "connecting" | "connected" | "error";
  ws_last_event_at: string | null;
  ws_last_error: string | null;
  ws_reconnect_attempts: number;
  api_last_success_at: string | null;
  api_last_error_at: string | null;
  api_last_error_message: string | null;
};

export type RuntimeInfo = {
  gateway_backend: string;
  tge_completion_mode: string | null;
  tge_llm_model: string | null;
  tge_llm_base_url: string | null;
  tge_ollama_keep_alive?: string | null;
  tge_runtime_probe_llm_default?: boolean | null;
  health_ok: boolean;
};

export type RuntimeChecks = {
  backend: string;
  completion_mode?: string | null;
  database: { ok: boolean | null; detail: string };
  engine: { ok: boolean | null; detail: string };
  llm: { configured: boolean; probe_attempted: boolean; ok: boolean | null; detail: string };
};

export type DiagnosticsBundle = {
  generated_at_client: string;
  app_version: string;
  selected_campaign_id: string | null;
  runtime_cache: RuntimeInfo;
  runtime_checks_cache?: RuntimeChecks;
  runtime_checks_meta?: { generated_at: string | null; probe_llm: boolean };
  diagnostics: DiagnosticsState;
  selected_actor: string | null;
  debug_snapshot_cache: unknown;
};

export type ServerDiagnosticsBundle = {
  generated_at: string;
  runtime: unknown;
  features: unknown;
  campaign_id?: string;
  campaign_debug_snapshot?: unknown;
};

export type FetchLike = (url: string, init?: { method?: string; body?: string }) => Promise<unknown>;

export function buildRuntimeChecksPath(probeLlm: boolean): string {
  return probeLlm ? "/api/runtime/checks?probe_llm=true" : "/api/runtime/checks";
}

export function buildTurnPayload(actorId: string, action: string, sessionId?: string | null): TurnPayload {
  return {
    actor_id: actorId.trim(),
    action: action.trim(),
    session_id: sessionId ? sessionId.trim() : undefined,
  };
}

export function requireNonEmptyAction(payload: TurnPayload): boolean {
  return payload.action.length > 0;
}

export function initDiagnosticsState(): DiagnosticsState {
  return {
    ws_state: "disconnected",
    ws_last_event_at: null,
    ws_last_error: null,
    ws_reconnect_attempts: 0,
    api_last_success_at: null,
    api_last_error_at: null,
    api_last_error_message: null,
  };
}

export function applyApiSuccess(state: DiagnosticsState, timestamp: string): DiagnosticsState {
  return {
    ...state,
    api_last_success_at: timestamp,
  };
}

export function applyApiError(state: DiagnosticsState, timestamp: string, message: string): DiagnosticsState {
  return {
    ...state,
    api_last_error_at: timestamp,
    api_last_error_message: message,
  };
}

export function applyWsConnected(state: DiagnosticsState, timestamp: string): DiagnosticsState {
  return {
    ...state,
    ws_state: "connected",
    ws_last_event_at: timestamp,
    ws_reconnect_attempts: 0,
    ws_last_error: null,
  };
}

export function applyWsClosed(state: DiagnosticsState, shouldReconnect: boolean, maxAttempts = 5): DiagnosticsState {
  if (!shouldReconnect) {
    return {
      ...state,
      ws_state: "disconnected",
    };
  }
  const nextAttempts = state.ws_reconnect_attempts + 1;
  if (nextAttempts > maxAttempts) {
    return {
      ...state,
      ws_state: "disconnected",
      ws_last_error: "WebSocket reconnect limit reached.",
      ws_reconnect_attempts: maxAttempts,
    };
  }
  return {
    ...state,
    ws_state: "disconnected",
    ws_reconnect_attempts: nextAttempts,
  };
}

export function buildClientDiagnosticsBundle(
  generatedAtClient: string,
  appVersion: string,
  selectedCampaignId: string | null,
  runtimeCache: RuntimeInfo,
  runtimeChecksCache: RuntimeChecks | null,
  runtimeChecksMeta: { generated_at: string | null; probe_llm: boolean } | null,
  diagnostics: DiagnosticsState,
  selectedActor: string | null,
  debugSnapshotCache: unknown,
): DiagnosticsBundle {
  return {
    generated_at_client: generatedAtClient,
    app_version: appVersion,
    selected_campaign_id: selectedCampaignId,
    runtime_cache: runtimeCache,
    runtime_checks_cache: runtimeChecksCache || undefined,
    runtime_checks_meta: runtimeChecksMeta || undefined,
    diagnostics,
    selected_actor: selectedActor,
    debug_snapshot_cache: debugSnapshotCache,
  };
}

export function mergeDiagnosticsBundle(
  serverBundle: ServerDiagnosticsBundle,
  clientBundle: DiagnosticsBundle,
): Record<string, unknown> {
  return {
    ...serverBundle,
    client_bundle: clientBundle,
  };
}

export async function submitTurnFlow(
  fetcher: FetchLike,
  campaignId: string,
  payload: TurnPayload,
): Promise<{ calls: string[] }> {
  const calls: string[] = [];

  calls.push(`/api/campaigns/${campaignId}/turns`);
  await fetcher(`/api/campaigns/${campaignId}/turns`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  calls.push(`/api/campaigns/${campaignId}/map`);
  await fetcher(`/api/campaigns/${campaignId}/map?actor_id=${encodeURIComponent(payload.actor_id)}`);

  calls.push(`/api/campaigns/${campaignId}/timers`);
  await fetcher(`/api/campaigns/${campaignId}/timers`);

  calls.push(`/api/campaigns/${campaignId}/calendar`);
  await fetcher(`/api/campaigns/${campaignId}/calendar`);

  calls.push(`/api/campaigns/${campaignId}/roster`);
  await fetcher(`/api/campaigns/${campaignId}/roster`);

  calls.push(`/api/campaigns/${campaignId}/player-state`);
  await fetcher(`/api/campaigns/${campaignId}/player-state?actor_id=${encodeURIComponent(payload.actor_id)}`);

  calls.push(`/api/campaigns/${campaignId}/media`);
  await fetcher(`/api/campaigns/${campaignId}/media?actor_id=${encodeURIComponent(payload.actor_id)}`);

  calls.push(`/api/campaigns/${campaignId}/sessions`);
  await fetcher(`/api/campaigns/${campaignId}/sessions`);

  calls.push(`/api/campaigns/${campaignId}/debug/snapshot`);
  await fetcher(`/api/campaigns/${campaignId}/debug/snapshot`);

  return { calls };
}

export async function sessionManagementFlow(
  fetcher: FetchLike,
  campaignId: string,
  createPayload: {
    surface: string;
    surface_key: string;
    surface_guild_id?: string | null;
    surface_channel_id?: string | null;
    surface_thread_id?: string | null;
    enabled?: boolean;
    metadata?: Record<string, unknown>;
  },
  patchPayload: {
    session_id: string;
    enabled?: boolean;
    metadata?: Record<string, unknown> | null;
  },
): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  calls.push(`/api/campaigns/${campaignId}/sessions`);
  await fetcher(`/api/campaigns/${campaignId}/sessions`, {
    method: "POST",
    body: JSON.stringify(createPayload),
  });

  calls.push(`/api/campaigns/${campaignId}/sessions`);
  await fetcher(`/api/campaigns/${campaignId}/sessions`);

  calls.push(`/api/campaigns/${campaignId}/sessions/${patchPayload.session_id}`);
  await fetcher(`/api/campaigns/${campaignId}/sessions/${patchPayload.session_id}`, {
    method: "PATCH",
    body: JSON.stringify({
      enabled: patchPayload.enabled,
      metadata: patchPayload.metadata,
    }),
  });

  calls.push(`/api/campaigns/${campaignId}/sessions`);
  await fetcher(`/api/campaigns/${campaignId}/sessions`);
  return { calls };
}

export async function mediaAvatarActionsFlow(
  fetcher: FetchLike,
  campaignId: string,
  actorId: string,
): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  calls.push(`/api/campaigns/${campaignId}/media/avatar/accept`);
  await fetcher(`/api/campaigns/${campaignId}/media/avatar/accept`, {
    method: "POST",
    body: JSON.stringify({ actor_id: actorId }),
  });
  calls.push(`/api/campaigns/${campaignId}/media`);
  await fetcher(`/api/campaigns/${campaignId}/media?actor_id=${encodeURIComponent(actorId)}`);
  calls.push(`/api/campaigns/${campaignId}/player-state`);
  await fetcher(`/api/campaigns/${campaignId}/player-state?actor_id=${encodeURIComponent(actorId)}`);

  calls.push(`/api/campaigns/${campaignId}/media/avatar/decline`);
  await fetcher(`/api/campaigns/${campaignId}/media/avatar/decline`, {
    method: "POST",
    body: JSON.stringify({ actor_id: actorId }),
  });
  calls.push(`/api/campaigns/${campaignId}/media`);
  await fetcher(`/api/campaigns/${campaignId}/media?actor_id=${encodeURIComponent(actorId)}`);
  calls.push(`/api/campaigns/${campaignId}/player-state`);
  await fetcher(`/api/campaigns/${campaignId}/player-state?actor_id=${encodeURIComponent(actorId)}`);

  return { calls };
}

export async function rosterManagementFlow(
  fetcher: FetchLike,
  campaignId: string,
  payload: {
    slug: string;
    name?: string | null;
    location?: string | null;
    status?: string | null;
    player?: boolean;
    fields?: Record<string, unknown>;
  },
): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  calls.push(`/api/campaigns/${campaignId}/roster/upsert`);
  await fetcher(`/api/campaigns/${campaignId}/roster/upsert`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  calls.push(`/api/campaigns/${campaignId}/roster`);
  await fetcher(`/api/campaigns/${campaignId}/roster`);

  calls.push(`/api/campaigns/${campaignId}/roster/remove`);
  await fetcher(`/api/campaigns/${campaignId}/roster/remove`, {
    method: "POST",
    body: JSON.stringify({ slug: payload.slug, player: payload.player === true }),
  });
  calls.push(`/api/campaigns/${campaignId}/roster`);
  await fetcher(`/api/campaigns/${campaignId}/roster`);
  return { calls };
}

export async function memoryToolsFlow(
  fetcher: FetchLike,
  campaignId: string,
  payload: {
    queries: string[];
    category?: string | null;
    wildcard: string;
    turn_id: number;
    store: { category: string; term?: string | null; memory: string };
  },
): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  calls.push(`/api/campaigns/${campaignId}/memory/search`);
  await fetcher(`/api/campaigns/${campaignId}/memory/search`, {
    method: "POST",
    body: JSON.stringify({
      queries: payload.queries,
      category: payload.category ?? null,
    }),
  });

  calls.push(`/api/campaigns/${campaignId}/memory/terms`);
  await fetcher(`/api/campaigns/${campaignId}/memory/terms`, {
    method: "POST",
    body: JSON.stringify({ wildcard: payload.wildcard }),
  });

  calls.push(`/api/campaigns/${campaignId}/memory/turn`);
  await fetcher(`/api/campaigns/${campaignId}/memory/turn`, {
    method: "POST",
    body: JSON.stringify({ turn_id: payload.turn_id }),
  });

  calls.push(`/api/campaigns/${campaignId}/memory/store`);
  await fetcher(`/api/campaigns/${campaignId}/memory/store`, {
    method: "POST",
    body: JSON.stringify(payload.store),
  });

  return { calls };
}

export async function smsToolsFlow(
  fetcher: FetchLike,
  campaignId: string,
  payload: {
    wildcard: string;
    thread: string;
    limit: number;
    sender: string;
    recipient: string;
    message: string;
  },
): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  calls.push(`/api/campaigns/${campaignId}/sms/list`);
  await fetcher(`/api/campaigns/${campaignId}/sms/list`, {
    method: "POST",
    body: JSON.stringify({ wildcard: payload.wildcard }),
  });

  calls.push(`/api/campaigns/${campaignId}/sms/read`);
  await fetcher(`/api/campaigns/${campaignId}/sms/read`, {
    method: "POST",
    body: JSON.stringify({ thread: payload.thread, limit: payload.limit }),
  });

  calls.push(`/api/campaigns/${campaignId}/sms/write`);
  await fetcher(`/api/campaigns/${campaignId}/sms/write`, {
    method: "POST",
    body: JSON.stringify({
      thread: payload.thread,
      sender: payload.sender,
      recipient: payload.recipient,
      message: payload.message,
    }),
  });

  return { calls };
}
