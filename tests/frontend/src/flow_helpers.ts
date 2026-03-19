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

/* ---- Turn history types and helpers ---- */

export type HistoryTurn = {
  id?: number | null;
  kind: string;
  content: string;
  session_id?: string;
  created_at?: string;
  meta?: Record<string, unknown>;
};

export type Campaign = {
  id: string;
  name: string;
  actor_id: string;
};

export type Session = {
  id: string;
  surface_key?: string;
  metadata?: Record<string, unknown>;
};

export function populateTurnStreamFromHistory(
  recentTurns: HistoryTurn[],
  selectedSessionId: string,
): { entries: Array<{ id: number; type: string; text: string; at: string; meta: Record<string, unknown>; _backendTurnId: number | null }>; turnCounter: number; gameTime: Record<string, unknown> } {
  let gameTime: Record<string, unknown> = {};
  const entries: Array<{ id: number; type: string; text: string; at: string; meta: Record<string, unknown>; _backendTurnId: number | null }> = [];
  let counter = 0;
  for (const turn of recentTurns) {
    if (selectedSessionId && turn.session_id && turn.session_id !== selectedSessionId) continue;
    if (turn.kind === "narration" || turn.kind === "action_response") {
      counter++;
      const meta = turn.meta || {};
      const entry: { id: number; type: string; text: string; at: string; meta: Record<string, unknown>; _backendTurnId: number | null } = {
        id: counter,
        type: "narrator",
        at: turn.created_at ? new Date(turn.created_at).toLocaleTimeString() : "",
        text: turn.content || "[No content]",
        meta: {},
        _backendTurnId: turn.id || null,
      };
      if (meta.game_time) {
        entry.meta._game_time = meta.game_time;
        gameTime = meta.game_time as Record<string, unknown>;
      }
      entries.push(entry);
    }
  }
  return { entries, turnCounter: counter, gameTime };
}

export function resolveRestoredSelection(
  savedCampaignId: string | null,
  savedSessionId: string | null,
  campaigns: Campaign[],
  sessionsList: Session[],
): { campaignId: string | null; sessionId: string | null } {
  if (!savedCampaignId || !campaigns.some(c => c.id === savedCampaignId)) {
    return { campaignId: null, sessionId: null };
  }
  const sessionId = savedSessionId && sessionsList.some(s => s.id === savedSessionId)
    ? savedSessionId
    : null;
  return { campaignId: savedCampaignId, sessionId };
}

export type FileEntry = {
  name: string;
  text: string;
  status: string;
};

export async function campaignCreationWithDocsFlow(
  fetcher: FetchLike,
  campaignName: string,
  actorId: string,
  files: FileEntry[],
  onRails: boolean,
): Promise<{ calls: string[]; campaignId: string; failedFiles: string[] }> {
  const calls: string[] = [];
  const failedFiles: string[] = [];

  // 1. Create campaign
  calls.push("/api/campaigns");
  const body = await fetcher("/api/campaigns", {
    method: "POST",
    body: JSON.stringify({
      namespace: "default",
      name: campaignName.trim(),
      actor_id: actorId.trim(),
    }),
  }) as { campaign: { id: string; name: string } };

  const campaignId = body.campaign.id;

  // 2. Ingest each file via digest endpoint
  const allTexts: string[] = [];
  for (const f of files) {
    if (!f.text || !f.text.trim()) continue;
    const digestUrl = `/api/campaigns/${campaignId}/source-materials/digest`;
    calls.push(digestUrl);
    try {
      await fetcher(digestUrl, {
        method: "POST",
        body: JSON.stringify({
          text: f.text,
          document_label: f.name.replace(/\.[^.]+$/, ""),
          format: null,
          replace_document: true,
        }),
      });
      allTexts.push(f.text);
    } catch (_err) {
      failedFiles.push(f.name);
    }
  }

  // 3. Start setup wizard with combined text (only when files ingested)
  if (allTexts.length > 0) {
    const setupUrl = `/api/campaigns/${campaignId}/setup/start`;
    calls.push(setupUrl);
    await fetcher(setupUrl, {
      method: "POST",
      body: JSON.stringify({
        actor_id: actorId.trim(),
        on_rails: onRails,
        attachment_text: allTexts.join("\n\n---\n\n"),
      }),
    });
  }

  return { calls, campaignId, failedFiles };
}

/* ---- Rewind from turn stream helpers ---- */

export async function rewindFromStreamFlow(
  fetcher: FetchLike,
  campaignId: string,
  turnId: number,
): Promise<{ calls: string[]; rewindOk: boolean }> {
  const calls: string[] = [];
  if (!Number.isFinite(turnId) || turnId <= 0) {
    return { calls, rewindOk: false };
  }
  const url = `/api/campaigns/${campaignId}/rewind?target_turn_id=${turnId}`;
  calls.push(url);
  const result = (await fetcher(url, { method: "POST" })) as { ok?: boolean };
  return { calls, rewindOk: result.ok !== false };
}

/* ---- Infinite scroll pagination helpers ---- */

export type PaginationState = {
  offset: number;
  hasMore: boolean;
  loading: boolean;
};

export function initPaginationState(): PaginationState {
  return { offset: 0, hasMore: false, loading: false };
}

export function resetPagination(): PaginationState {
  return { offset: 0, hasMore: false, loading: false };
}

export async function loadOlderTurnsFlow(
  fetcher: FetchLike,
  campaignId: string,
  currentTurns: HistoryTurn[],
  pagination: PaginationState,
): Promise<{ calls: string[]; turns: HistoryTurn[]; pagination: PaginationState }> {
  const calls: string[] = [];
  if (pagination.loading || !pagination.hasMore) {
    return { calls, turns: currentTurns, pagination };
  }
  const newOffset = pagination.offset + currentTurns.length;
  const url = `/api/campaigns/${campaignId}/recent-turns?limit=30&offset=${newOffset}`;
  calls.push(url);
  const data = (await fetcher(url)) as { turns?: HistoryTurn[]; has_more?: boolean };
  const older = Array.isArray(data.turns) ? data.turns : [];
  if (older.length === 0) {
    return { calls, turns: currentTurns, pagination: { ...pagination, hasMore: false } };
  }
  return {
    calls,
    turns: [...older, ...currentTurns],
    pagination: { offset: newOffset, hasMore: !!data.has_more, loading: false },
  };
}

/* ---- Unseen-activity helpers ---- */

export type RecentTurn = {
  session_id?: string;
  created_at?: string;
};

/**
 * Determine whether a session has turns the user hasn't seen.
 * - Returns false for the currently-selected session.
 * - When lastSeen is undefined (never visited), any turn means unseen.
 * - Compares via Date.parse() to handle both `Z` and `+00:00` suffixes.
 */
export function sessionHasUnseen(
  sessionId: string,
  selectedSessionId: string,
  lastSeen: string | undefined,
  recentTurns: RecentTurn[],
): boolean {
  if (!sessionId || sessionId === selectedSessionId) return false;
  const lastSeenMs = lastSeen ? Date.parse(lastSeen) : undefined;
  for (const turn of recentTurns) {
    if (turn.session_id !== sessionId || !turn.created_at) continue;
    if (lastSeenMs === undefined) return true;
    if (Date.parse(turn.created_at) > lastSeenMs) return true;
  }
  return false;
}

/**
 * Safely parse a sessionLastSeen JSON string from localStorage.
 * Returns a plain object or {} on any invalid/unexpected shape.
 */
export function parseSessionLastSeen(raw: string | null): Record<string, string> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, string>;
    }
  } catch (_) { /* fall through */ }
  return {};
}

/* ---- Settings + Ollama model preservation ---- */

export type OllamaModel = {
  name: string;
  size: number | null;
  modified_at: string | null;
};

export type SettingsForm = {
  completion_mode: string;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  keep_alive: string;
  ollama_options_json: string;
};

/**
 * Simulate the loadOllamaModels flow: populate the dropdown and
 * ensure the current model isn't lost in the process.
 *
 * The optional `onModelsAssigned` callback simulates a side-effect that
 * occurs between the moment the model list is assigned and the restoration
 * guard runs — e.g. Alpine's <select x-model> syncing an empty value back
 * into settingsForm.model when options re-render.  The callback receives
 * the mutable settingsForm so it can blank the model field, exercising
 * the restoration branch.
 */
export function applyOllamaModels(
  settingsForm: SettingsForm,
  apiModels: OllamaModel[],
  reachable: boolean,
  onModelsAssigned?: (form: SettingsForm) => void,
): { ollamaModels: OllamaModel[]; settingsForm: SettingsForm } {
  const savedModel = (settingsForm.model || "").trim();
  let ollamaModels: OllamaModel[];

  if (reachable && Array.isArray(apiModels)) {
    ollamaModels = [...apiModels];
    const currentModel = savedModel || (settingsForm.model || "").trim();
    if (currentModel && !ollamaModels.some((m) => m.name === currentModel)) {
      ollamaModels.unshift({ name: currentModel, size: null, modified_at: null });
    }
    /* Simulate Alpine re-render side-effect (may blank the model) */
    if (onModelsAssigned) onModelsAssigned(settingsForm);
    if (savedModel) settingsForm = { ...settingsForm, model: savedModel };
  } else {
    ollamaModels = [];
  }

  /* Final guard: restore model if it was blanked during re-render */
  if (savedModel && !settingsForm.model) {
    settingsForm = { ...settingsForm, model: savedModel };
  }

  return { ollamaModels, settingsForm };
}

/* ---- Theme helpers ---- */

export type ThemeEntry = {
  value: string;
  label: string;
  description: string;
  source: string;
};

export type ThemeState = {
  theme: string;
  themes: ThemeEntry[];
};

export function initThemeState(initial?: string): ThemeState {
  return {
    theme: initial || "light",
    themes: [],
  };
}

export async function loadThemesFlow(
  fetcher: FetchLike,
): Promise<{ calls: string[]; themes: ThemeEntry[] }> {
  const calls: string[] = [];
  calls.push("/api/themes");
  const themes = (await fetcher("/api/themes")) as ThemeEntry[];
  return { calls, themes };
}

export async function applyThemeFlow(
  fetcher: FetchLike,
  state: ThemeState,
  themeName: string,
): Promise<{ calls: string[]; state: ThemeState }> {
  const calls: string[] = [];

  // Validate theme exists in loaded list
  if (!state.themes.some((t) => t.value === themeName)) {
    return { calls, state };
  }

  // Update local state
  const newState: ThemeState = { ...state, theme: themeName };

  // POST to server
  calls.push("/api/settings/theme");
  await fetcher("/api/settings/theme", {
    method: "POST",
    body: JSON.stringify({ theme: themeName }),
  });

  return { calls, state: newState };
}

export async function getThemeSettingFlow(
  fetcher: FetchLike,
): Promise<{ calls: string[]; theme: string }> {
  const calls: string[] = [];
  calls.push("/api/settings/theme");
  const body = (await fetcher("/api/settings/theme")) as { theme: string };
  return { calls, theme: body.theme };
}

export async function themeFullFlow(
  fetcher: FetchLike,
  targetTheme: string,
): Promise<{ calls: string[]; state: ThemeState }> {
  const calls: string[] = [];

  // 1. Load current setting
  const settingResult = await getThemeSettingFlow(fetcher);
  calls.push(...settingResult.calls);

  // 2. Load available themes
  const listResult = await loadThemesFlow(fetcher);
  calls.push(...listResult.calls);

  // 3. Initialize state
  let state: ThemeState = {
    theme: settingResult.theme,
    themes: listResult.themes,
  };

  // 4. Apply the target theme
  const applyResult = await applyThemeFlow(fetcher, state, targetTheme);
  calls.push(...applyResult.calls);
  state = applyResult.state;

  return { calls, state };
}
