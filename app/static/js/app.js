(function () {
  function formatJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function nowLabel() {
    return new Date().toLocaleTimeString();
  }

  function isoNow() {
    return new Date().toISOString();
  }

  function normalizeTurnNarration(payload) {
    if (payload.narration && payload.narration.trim().length > 0) {
      return payload.narration;
    }
    if (Object.keys(payload.state_update || {}).length > 0 || Object.keys(payload.player_state_update || {}).length > 0) {
      return "[No narration returned. State updates were applied.]";
    }
    return "[No narration returned.]";
  }

  function canonicalKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  window.textGameApp = function textGameApp() {
    return {
      campaigns: [],
      selectedCampaignId: null,
      selectedSessionId: "",
      inspectorTab: "map",
      statusMessage: "Ready.",
      errorMessage: "",
      turnCounter: 0,
      socket: null,
      socketReconnectTimer: null,
      turnStream: [],
      sessionsList: [],

      runtimeInfo: {
        gateway_backend: "unknown",
        tge_completion_mode: null,
        tge_llm_model: null,
        tge_llm_base_url: null,
        tge_ollama_keep_alive: null,
        tge_runtime_probe_llm_default: null,
        health_ok: false,
      },
      runtimeChecks: {
        backend: "unknown",
        completion_mode: null,
        database: { ok: null, detail: "Not checked." },
        engine: { ok: null, detail: "Not checked." },
        llm: { configured: false, probe_attempted: false, ok: null, detail: "Not checked." },
      },
      runtimeChecksMeta: {
        generated_at: null,
        probe_llm: false,
      },
      diagnostics: {
        ws_state: "disconnected",
        ws_last_event_at: null,
        ws_last_error: null,
        ws_reconnect_attempts: 0,
        api_last_success_at: null,
        api_last_error_at: null,
        api_last_error_message: null,
      },

      campaignForm: {
        namespace: "default",
        name: "",
        actor_id: "",
      },
      turnForm: {
        actor_id: "",
        action: "",
        session_id: "",
      },
      memory: {
        search: "",
        category: "",
        wildcard: "*",
        turnId: "",
        storeCategory: "",
        storeTerm: "",
        storeText: "",
      },
      sms: {
        wildcard: "*",
        thread: "",
        limit: 20,
        sender: "",
        recipient: "",
        message: "",
      },
      sessions: {
        surface: "discord_thread",
        surface_key: "",
        surface_guild_id: "",
        surface_channel_id: "",
        surface_thread_id: "",
        enabled: true,
        metadata_json: "{}",
        update_session_id: "",
        update_enabled: true,
        update_metadata_json: "",
        quick_private_target: "",
        quick_private_kind: "solo",
      },
      mediaActions: {
        actor_id: "",
      },
      rosterActions: {
        slug: "",
        name: "",
        location: "",
        status: "",
        player: false,
        fields_json: "{}",
      },

      mapText: "",
      timersText: "",
      calendarText: "",
      rosterText: "",
      playerStateText: "",
      mediaText: "",
      sessionsText: "",
      memoryText: "",
      smsText: "",
      debugText: "",
      diagnosticsBundleStatus: "",

      async init() {
        await this.loadRuntime();
        await this.refreshCampaigns();
        if (!this.statusMessage.startsWith("Runtime backend:")) {
          this.statusMessage = "Initialized.";
        }
      },

      resetError() {
        this.errorMessage = "";
      },

      recordApiSuccess() {
        this.diagnostics.api_last_success_at = isoNow();
      },

      recordApiError(message) {
        this.diagnostics.api_last_error_at = isoNow();
        this.diagnostics.api_last_error_message = String(message || "Request failed");
      },

      async api(path, options) {
        let alreadyRecorded = false;
        try {
          const config = {
            method: "GET",
            headers: { "Content-Type": "application/json" },
            ...options,
          };
          const response = await fetch(path, config);
          const raw = await response.text();
          let data = {};
          if (raw) {
            try {
              data = JSON.parse(raw);
            } catch (_err) {
              data = { detail: raw };
            }
          }
          if (!response.ok) {
            const detail = data.detail || raw || "Request failed";
            this.recordApiError(detail);
            alreadyRecorded = true;
            throw new Error(detail);
          }
          this.recordApiSuccess();
          return data;
        } catch (error) {
          if (!alreadyRecorded) {
            this.recordApiError(String(error));
          }
          throw error;
        }
      },

      pushStream(type, text, meta) {
        this.turnCounter += 1;
        this.turnStream.push({
          id: this.turnCounter,
          type,
          at: nowLabel(),
          text,
          meta: meta && typeof meta === "object" ? meta : {},
        });
        this.$nextTick(() => {
          const stream = document.getElementById("turn-stream");
          if (stream) {
            stream.scrollTop = stream.scrollHeight;
          }
        });
      },

      currentSessionRecord() {
        if (!this.selectedSessionId) {
          return null;
        }
        return this.sessionsList.find((row) => row.id === this.selectedSessionId) || null;
      },

      currentSessionLabel() {
        const row = this.currentSessionRecord();
        if (!row) {
          return "No window selected";
        }
        const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
        const label = metadata.label || row.surface_key || row.id;
        const scope = metadata.scope || metadata.turn_visibility_default || row.surface;
        return `${label} (${scope})`;
      },

      syncTurnSessionSelection() {
        this.turnForm.session_id = this.selectedSessionId || "";
      },

      selectSession(sessionId) {
        this.selectedSessionId = sessionId || "";
        this.syncTurnSessionSelection();
        this.turnStream = [];
        this.connectSocket();
        const row = this.currentSessionRecord();
        if (row) {
          const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
          this.statusMessage = `Selected window ${metadata.label || row.surface_key || row.id}.`;
        }
      },

      handleActorIdentityChange() {
        this.syncTurnSessionSelection();
        this.connectSocket();
      },

      buildSharedSessionPayload() {
        return {
          surface: "web_shared",
          surface_key: `webui:${this.selectedCampaignId}:shared`,
          enabled: true,
          metadata: {
            label: "Shared web room",
            scope: "local",
            turn_visibility_default: "local",
          },
        };
      },

      buildPrivateSessionPayload() {
        const actorId = (this.turnForm.actor_id || "").trim();
        if (!actorId) {
          throw new Error("Actor id is required before opening a private window.");
        }
        const target = (this.sessions.quick_private_target || "").trim();
        const kind = String(this.sessions.quick_private_kind || "solo").trim().toLowerCase();
        const actorKey = canonicalKey(actorId) || actorId;
        const targetKey = canonicalKey(target);
        const metadata = {
          label: "",
          scope: "private",
          turn_visibility_default: "private",
          owner_actor_id: actorId,
          allowed_actor_ids: [actorId],
        };
        let surface_key = `webui:${this.selectedCampaignId}:private:${actorKey}`;
        if (kind === "actor" && target) {
          const actorPair = [actorId, target].map((item) => String(item).trim()).filter(Boolean).sort();
          surface_key = `webui:${this.selectedCampaignId}:direct:${actorPair.map(canonicalKey).join(":")}`;
          metadata.scope = "limited";
          metadata.allowed_actor_ids = actorPair;
          metadata.label = `Direct room: ${actorPair.join(" / ")}`;
        } else if (kind === "npc" && target) {
          surface_key = `webui:${this.selectedCampaignId}:npc:${actorKey}:${targetKey || "npc"}`;
          metadata.npc_slugs = [target];
          metadata.label = `Private with ${target}`;
        } else {
          metadata.label = `Private room: ${actorId}`;
        }
        return {
          surface: kind === "actor" ? "web_direct" : "web_private",
          surface_key,
          enabled: true,
          metadata,
        };
      },

      async loadRuntime() {
        this.resetError();
        try {
          const runtime = await this.api("/api/runtime");
          this.runtimeInfo.gateway_backend = runtime.gateway_backend || "unknown";
          this.runtimeInfo.tge_completion_mode = runtime.tge_completion_mode || null;
          this.runtimeInfo.tge_llm_model = runtime.tge_llm_model || null;
          this.runtimeInfo.tge_llm_base_url = runtime.tge_llm_base_url || null;
          this.runtimeInfo.tge_ollama_keep_alive = runtime.tge_ollama_keep_alive || null;
          this.runtimeInfo.tge_runtime_probe_llm_default = runtime.tge_runtime_probe_llm_default === true;

          const health = await this.api("/api/health");
          this.runtimeInfo.health_ok = health.ok === true;
          await this.runRuntimeChecks(false);

          this.statusMessage = `Runtime backend: ${this.runtimeInfo.gateway_backend}.`;
        } catch (error) {
          this.runtimeInfo.health_ok = false;
          this.errorMessage = String(error);
        }
      },

      async runRuntimeChecks(probeLlm) {
        const query = probeLlm === true ? "?probe_llm=true" : "";
        try {
          const checksBody = await this.api(`/api/runtime/checks${query}`);
          if (checksBody && checksBody.checks && typeof checksBody.checks === "object") {
            this.runtimeChecks = checksBody.checks;
            this.runtimeChecksMeta.generated_at = checksBody.generated_at || null;
            this.runtimeChecksMeta.probe_llm = checksBody.probe_llm === true;
          }
          if (probeLlm === true) {
            this.statusMessage = "LLM probe check completed.";
          }
        } catch (_error) {
          this.runtimeChecks = {
            ...this.runtimeChecks,
            database: { ok: null, detail: "Runtime checks unavailable." },
            engine: { ok: null, detail: "Runtime checks unavailable." },
            llm: {
              configured: false,
              probe_attempted: false,
              ok: null,
              detail: "Runtime checks unavailable.",
            },
          };
          this.runtimeChecksMeta.generated_at = null;
          this.runtimeChecksMeta.probe_llm = false;
        }
      },

      runtimeCheckLabel(node) {
        if (!node || typeof node.ok !== "boolean") {
          return "unknown";
        }
        return node.ok ? "ok" : "error";
      },

      runtimeLlmLabel() {
        const llm = this.runtimeChecks.llm || {};
        if (!llm.configured) {
          return "not configured";
        }
        if (llm.probe_attempted !== true) {
          return "configured (probe skipped)";
        }
        if (typeof llm.ok !== "boolean") {
          return "probe unknown";
        }
        return llm.ok ? "probe ok" : "probe failed";
      },

      buildClientDiagnosticsBundle() {
        const version =
          window.TextGameWebUI && typeof window.TextGameWebUI.version === "string"
            ? window.TextGameWebUI.version
            : "unknown";
        let parsedDebug = null;
        if (this.debugText && this.debugText.trim()) {
          try {
            parsedDebug = JSON.parse(this.debugText);
          } catch (_err) {
            parsedDebug = this.debugText;
          }
        }
        return {
          generated_at_client: isoNow(),
          app_version: version,
          selected_campaign_id: this.selectedCampaignId,
          runtime_cache: this.runtimeInfo,
          runtime_checks_cache: this.runtimeChecks,
          runtime_checks_meta: this.runtimeChecksMeta,
          diagnostics: this.diagnostics,
          selected_actor: this.turnForm.actor_id || null,
          debug_snapshot_cache: parsedDebug,
        };
      },

      async copyDiagnosticsBundle() {
        this.resetError();
        let payload;
        let usedServerBundle = false;
        const clientBundle = this.buildClientDiagnosticsBundle();
        try {
          const query = this.selectedCampaignId
            ? `?campaign_id=${encodeURIComponent(this.selectedCampaignId)}`
            : "";
          const serverBundle = await this.api(`/api/diagnostics/bundle${query}`);
          payload = {
            ...serverBundle,
            client_bundle: clientBundle,
          };
          usedServerBundle = true;
        } catch (_error) {
          payload = clientBundle;
        }
        const text = JSON.stringify(payload, null, 2);
        try {
          if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            await navigator.clipboard.writeText(text);
            this.diagnosticsBundleStatus = usedServerBundle
              ? `Copied diagnostics bundle at ${nowLabel()}.`
              : `Copied local-only diagnostics bundle at ${nowLabel()}.`;
            return;
          }
          throw new Error("Clipboard API unavailable");
        } catch (_error) {
          try {
            const blob = new Blob([text], { type: "application/json" });
            const href = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = href;
            link.download = `diagnostics-bundle-${Date.now()}.json`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(href);
            this.diagnosticsBundleStatus = usedServerBundle
              ? `Clipboard unavailable; downloaded bundle at ${nowLabel()}.`
              : `Clipboard unavailable; downloaded local-only bundle at ${nowLabel()}.`;
          } catch (downloadError) {
            this.diagnosticsBundleStatus = "";
            this.errorMessage = String(downloadError);
          }
        }
      },

      async refreshCampaigns() {
        this.resetError();
        try {
          const namespace = encodeURIComponent(this.campaignForm.namespace || "default");
          const body = await this.api(`/api/campaigns?namespace=${namespace}`);
          this.campaigns = body.campaigns || [];
          this.statusMessage = `Loaded ${this.campaigns.length} campaign(s).`;
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async createCampaign() {
        this.resetError();
        try {
          const payload = {
            namespace: this.campaignForm.namespace || "default",
            name: this.campaignForm.name.trim(),
            actor_id: this.campaignForm.actor_id.trim(),
          };
          const body = await this.api("/api/campaigns", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          const campaign = body.campaign;
          this.campaignForm.name = "";
          await this.refreshCampaigns();
          await this.selectCampaign(campaign.id);
          this.statusMessage = `Created campaign ${campaign.name}.`;
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async selectCampaign(campaignId) {
        this.resetError();
        this.selectedCampaignId = campaignId;
        this.selectedSessionId = "";
        this.turnStream = [];
        const selected = this.campaigns.find((row) => row.id === campaignId);
        if (selected && !this.turnForm.actor_id) {
          this.turnForm.actor_id = selected.actor_id;
        }
        if (!this.mediaActions.actor_id && this.turnForm.actor_id) {
          this.mediaActions.actor_id = this.turnForm.actor_id;
        }
        if (!this.rosterActions.slug && this.turnForm.actor_id) {
          this.rosterActions.slug = this.turnForm.actor_id;
          this.rosterActions.player = true;
        }
        await Promise.all([
          this.loadSessions(),
          this.loadMap(),
          this.loadTimers(),
          this.loadCalendar(),
          this.loadRoster(),
          this.loadPlayerState(),
          this.loadMedia(),
          this.loadDebugSnapshot(),
        ]);
        this.statusMessage = `Selected campaign ${campaignId}.`;
      },

      connectSocket() {
        if (!this.selectedCampaignId) {
          return;
        }
        if (this.socketReconnectTimer) {
          clearTimeout(this.socketReconnectTimer);
          this.socketReconnectTimer = null;
        }
        if (this.socket) {
          this.socket.close();
        }
        const campaignId = this.selectedCampaignId;
        this.diagnostics.ws_state = "connecting";
        this.diagnostics.ws_last_error = null;
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const params = new URLSearchParams();
        const actorId = (this.turnForm.actor_id || "").trim();
        if (actorId) {
          params.set("actor_id", actorId);
        }
        if (this.selectedSessionId) {
          params.set("session_id", this.selectedSessionId);
        }
        const suffix = params.toString() ? `?${params.toString()}` : "";
        const socketUrl = `${protocol}://${window.location.host}/ws/campaigns/${campaignId}${suffix}`;
        this.socket = new WebSocket(socketUrl);
        this.socket.onopen = () => {
          this.diagnostics.ws_state = "connected";
          this.diagnostics.ws_last_event_at = isoNow();
          this.diagnostics.ws_reconnect_attempts = 0;
          this.statusMessage = "Realtime connected.";
        };
        this.socket.onmessage = (event) => {
          this.diagnostics.ws_last_event_at = isoNow();
          const payload = JSON.parse(event.data);
          if (payload.type === "turn" && payload.payload) {
            this.pushStream("narrator", normalizeTurnNarration(payload.payload), payload.payload);
            this.loadTimers();
          }
          if (payload.type === "sms" && payload.payload) {
            this.pushStream("sms", formatJson(payload.payload));
          }
          if (payload.type === "session" && payload.payload) {
            this.pushStream("session", formatJson(payload.payload), payload.payload);
            this.loadSessions();
          }
          if (payload.type === "media" && payload.payload) {
            this.pushStream("media", formatJson(payload.payload), payload.payload);
            this.loadMedia();
          }
          if (payload.type === "timers" && payload.payload) {
            this.pushStream("timers", formatJson(payload.payload), payload.payload);
            this.timersText = formatJson(payload.payload);
          }
          if (payload.type === "roster" && payload.payload) {
            this.pushStream("roster", formatJson(payload.payload));
            this.rosterText = formatJson(payload.payload);
          }
        };
        this.socket.onerror = () => {
          this.diagnostics.ws_state = "error";
          this.diagnostics.ws_last_error = "WebSocket transport error.";
          this.errorMessage = "WebSocket error.";
        };
        this.socket.onclose = () => {
          this.diagnostics.ws_state = "disconnected";
          if (!this.selectedCampaignId || this.selectedCampaignId !== campaignId) {
            return;
          }
          if (this.diagnostics.ws_reconnect_attempts >= 5) {
            this.diagnostics.ws_last_error = "WebSocket reconnect limit reached.";
            return;
          }
          this.diagnostics.ws_reconnect_attempts += 1;
          this.socketReconnectTimer = setTimeout(() => {
            this.connectSocket();
          }, 1500);
        };
      },

      async submitTurn() {
        this.resetError();
        if (!this.selectedCampaignId) {
          this.errorMessage = "Select a campaign first.";
          return;
        }
        try {
          const payload = {
            actor_id: this.turnForm.actor_id.trim(),
            action: this.turnForm.action.trim(),
            session_id: this.selectedSessionId || null,
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/turns`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          const narration = normalizeTurnNarration(body);
          this.pushStream("narrator", narration, body);
          if (body.image_prompt) {
            this.pushStream("image_prompt", body.image_prompt, body);
          }
          if (body.summary_update) {
            this.pushStream("summary", body.summary_update, body);
          }
          this.turnForm.action = "";
          await Promise.all([
            this.loadSessions(),
            this.loadMap(),
            this.loadTimers(),
            this.loadCalendar(),
            this.loadRoster(),
            this.loadPlayerState(),
            this.loadMedia(),
            this.loadDebugSnapshot(),
          ]);
          this.statusMessage = "Turn submitted.";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async loadMap() {
        if (!this.selectedCampaignId) {
          return;
        }
        const actor = this.turnForm.actor_id || "player";
        const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/map?actor_id=${encodeURIComponent(actor)}`);
        this.mapText = body.map || "";
      },

      async loadTimers() {
        if (!this.selectedCampaignId) {
          return;
        }
        const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/timers`);
        this.timersText = formatJson(body);
      },

      async loadCalendar() {
        if (!this.selectedCampaignId) {
          return;
        }
        const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/calendar`);
        this.calendarText = formatJson(body);
      },

      async loadRoster() {
        if (!this.selectedCampaignId) {
          return;
        }
        const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/roster`);
        this.rosterText = formatJson(body);
      },

      async upsertRosterCharacter() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        const slug = (this.rosterActions.slug || "").trim();
        if (!slug) {
          this.errorMessage = "Roster slug is required.";
          return;
        }
        try {
          const fields = this.parseJsonInput(this.rosterActions.fields_json, {});
          const payload = {
            slug,
            name: this.rosterActions.name.trim() || null,
            location: this.rosterActions.location.trim() || null,
            status: this.rosterActions.status.trim() || null,
            player: this.rosterActions.player === true,
            fields: fields && typeof fields === "object" ? fields : {},
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/roster/upsert`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.pushStream("roster", formatJson(body));
          await Promise.all([this.loadRoster(), this.loadPlayerState(), this.loadDebugSnapshot()]);
          this.statusMessage = "Roster character upserted.";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async removeRosterCharacter() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        const slug = (this.rosterActions.slug || "").trim();
        if (!slug) {
          this.errorMessage = "Roster slug is required.";
          return;
        }
        try {
          const payload = {
            slug,
            player: this.rosterActions.player === true,
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/roster/remove`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.pushStream("roster", formatJson(body));
          await Promise.all([this.loadRoster(), this.loadPlayerState(), this.loadDebugSnapshot()]);
          this.statusMessage = "Roster character removal processed.";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      parseJsonInput(raw, fallback) {
        if (!raw || !raw.trim()) {
          return fallback;
        }
        try {
          return JSON.parse(raw);
        } catch (_error) {
          throw new Error("Invalid JSON payload.");
        }
      },

      async loadSessions() {
        if (!this.selectedCampaignId) {
          return;
        }
        const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`);
        const sessions = Array.isArray(body.sessions) ? body.sessions : [];
        this.sessionsList = sessions;
        this.sessionsText = formatJson(body);
        if (this.selectedSessionId) {
          const stillExists = sessions.some((row) => row && row.id === this.selectedSessionId);
          if (!stillExists) {
            this.selectedSessionId = "";
            this.syncTurnSessionSelection();
          }
        }
        if (!this.selectedSessionId) {
          const actorId = (this.turnForm.actor_id || "").trim();
          let preferred = sessions.find((row) => row.surface === "web_shared");
          if (!preferred) {
            preferred = sessions.find((row) => {
              const metadata = row && row.metadata && typeof row.metadata === "object" ? row.metadata : {};
              return actorId && row.surface === "web_private" && metadata.owner_actor_id === actorId;
            });
          }
          if (preferred && preferred.id) {
            this.selectedSessionId = preferred.id;
            this.syncTurnSessionSelection();
          }
        }
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
          return;
        }
        this.connectSocket();
      },

      async createOrUpdateSession() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const metadata = this.parseJsonInput(this.sessions.metadata_json, {});
          const payload = {
            surface: this.sessions.surface.trim(),
            surface_key: this.sessions.surface_key.trim(),
            surface_guild_id: this.sessions.surface_guild_id.trim() || null,
            surface_channel_id: this.sessions.surface_channel_id.trim() || null,
            surface_thread_id: this.sessions.surface_thread_id.trim() || null,
            enabled: this.sessions.enabled === true,
            metadata: metadata && typeof metadata === "object" ? metadata : {},
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.sessionsText = formatJson(body);
          this.sessions.update_session_id = body.session && body.session.id ? body.session.id : "";
          await this.loadSessions();
          if (body.session && body.session.id) {
            this.selectSession(body.session.id);
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async ensureSharedWindow() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`, {
            method: "POST",
            body: JSON.stringify(this.buildSharedSessionPayload()),
          });
          this.sessions.update_session_id = body.session && body.session.id ? body.session.id : "";
          await this.loadSessions();
          if (body.session && body.session.id) {
            this.selectSession(body.session.id);
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async ensurePrivateWindow() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`, {
            method: "POST",
            body: JSON.stringify(this.buildPrivateSessionPayload()),
          });
          this.sessions.update_session_id = body.session && body.session.id ? body.session.id : "";
          await this.loadSessions();
          if (body.session && body.session.id) {
            this.selectSession(body.session.id);
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async updateSession() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        const sessionId = (this.sessions.update_session_id || "").trim();
        if (!sessionId) {
          this.errorMessage = "Session id is required.";
          return;
        }
        try {
          const metadata =
            this.sessions.update_metadata_json.trim().length > 0
              ? this.parseJsonInput(this.sessions.update_metadata_json, {})
              : null;
          const payload = {
            enabled: this.sessions.update_enabled === true,
            metadata: metadata,
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions/${encodeURIComponent(sessionId)}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          });
          this.sessionsText = formatJson(body);
          await this.loadSessions();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async loadPlayerState() {
        if (!this.selectedCampaignId) {
          return;
        }
        const actor = this.turnForm.actor_id || "";
        if (!actor.trim()) {
          this.playerStateText = formatJson({ detail: "Set actor id to inspect player state." });
          return;
        }
        try {
          const body = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/player-state?actor_id=${encodeURIComponent(actor.trim())}`,
          );
          this.playerStateText = formatJson(body);
        } catch (error) {
          this.playerStateText = formatJson({
            detail: "Player state unavailable for selected actor.",
            actor_id: actor.trim(),
            error: String(error),
          });
        }
      },

      async loadMedia() {
        if (!this.selectedCampaignId) {
          return;
        }
        const actor = this.turnForm.actor_id || "";
        const query = actor.trim() ? `?actor_id=${encodeURIComponent(actor.trim())}` : "";
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/media${query}`);
          this.mediaText = formatJson(body);
        } catch (error) {
          this.mediaText = formatJson({
            detail: "Media status unavailable.",
            actor_id: actor.trim() || null,
            error: String(error),
          });
        }
      },

      resolveMediaActorId() {
        const actor = (this.mediaActions.actor_id || this.turnForm.actor_id || "").trim();
        if (!actor) {
          throw new Error("Actor id is required for avatar actions.");
        }
        return actor;
      },

      async acceptPendingAvatar() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const actor = this.resolveMediaActorId();
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/media/avatar/accept`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actor }),
          });
          this.pushStream("media", formatJson(body));
          await Promise.all([this.loadMedia(), this.loadPlayerState()]);
          this.statusMessage = "Processed avatar accept.";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async declinePendingAvatar() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const actor = this.resolveMediaActorId();
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/media/avatar/decline`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actor }),
          });
          this.pushStream("media", formatJson(body));
          await Promise.all([this.loadMedia(), this.loadPlayerState()]);
          this.statusMessage = "Processed avatar decline.";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async searchMemory() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const payload = {
            queries: this.memory.search.trim() ? [this.memory.search.trim()] : [],
            category: this.memory.category.trim() || null,
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/memory/search`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.memoryText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async listMemoryTerms() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/memory/terms`, {
            method: "POST",
            body: JSON.stringify({ wildcard: this.memory.wildcard || "*" }),
          });
          this.memoryText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async readMemoryTurn() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        const raw = String(this.memory.turnId || "").trim();
        const turnId = Number.parseInt(raw, 10);
        if (!Number.isFinite(turnId) || turnId <= 0) {
          this.errorMessage = "Turn id must be a positive integer.";
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/memory/turn`, {
            method: "POST",
            body: JSON.stringify({ turn_id: turnId }),
          });
          this.memoryText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async storeMemory() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const payload = {
            category: this.memory.storeCategory.trim(),
            term: this.memory.storeTerm.trim() || null,
            memory: this.memory.storeText.trim(),
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/memory/store`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.memoryText = formatJson(body);
          this.memory.storeText = "";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async listSmsThreads() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sms/list`, {
            method: "POST",
            body: JSON.stringify({ wildcard: this.sms.wildcard || "*" }),
          });
          this.smsText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async readSmsThread() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sms/read`, {
            method: "POST",
            body: JSON.stringify({ thread: this.sms.thread.trim(), limit: Number(this.sms.limit || 20) }),
          });
          this.smsText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async writeSms() {
        this.resetError();
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sms/write`, {
            method: "POST",
            body: JSON.stringify({
              thread: this.sms.thread.trim(),
              sender: this.sms.sender.trim(),
              recipient: this.sms.recipient.trim(),
              message: this.sms.message.trim(),
            }),
          });
          this.smsText = formatJson(body);
          this.sms.message = "";
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async loadDebugSnapshot() {
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/debug/snapshot`);
          this.debugText = formatJson(body);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },
    };
  };

  window.TextGameWebUI = {
    version: "0.2.0",
  };
})();
