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

  function normalizeTurnNotices(payload) {
    if (!payload || !Array.isArray(payload.notices)) {
      return [];
    }
    return payload.notices
      .map((item) => String(item || "").trim())
      .filter((item) => item.length > 0);
  }

  function canonicalKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  /* ---- Alpine Global Store ---- */
  document.addEventListener("alpine:init", () => {
    Alpine.store("app", {
      debugMode: localStorage.getItem("debugMode") === "true",
      settingsOpen: false,
      settingsTab: "llm",
      toggleDebugMode() {
        this.debugMode = !this.debugMode;
        localStorage.setItem("debugMode", this.debugMode ? "true" : "false");
      },
    });
  });

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
      submitting: false,
      _submittingTurn: false,
      _streamingNarration: "",

      /* Settings panel state */
      ollamaModels: [],
      settingsForm: {
        completion_mode: "ollama",
        base_url: "",
        model: "",
        temperature: 0.8,
        max_tokens: 3200,
        timeout_seconds: 90,
        keep_alive: "30m",
        ollama_options_json: "{}",
      },
      settingsSaving: false,
      settingsStatus: { ok: null, message: "" },

      /* Image settings panel state */
      imageSettingsForm: {
        image_backend: "none",
        diffusers_host: "127.0.0.1",
        diffusers_port: 8189,
        diffusers_model: "",
        diffusers_device: "cuda",
        diffusers_dtype: "bf16",
        diffusers_offload: "none",
        diffusers_quantization: "none",
        diffusers_vae_tiling: true,
        diffusers_autostart: false,
        comfyui_url: "http://127.0.0.1:8188",
        comfyui_workflow_json: "",
        image_width: 1024,
        image_height: 1024,
        image_steps: 20,
        image_guidance_scale: 3.5,
        image_cache_max_entries: 50,
      },
      imageSettingsSaving: false,
      imageSettingsStatus: { ok: null, message: "" },
      imageDaemonState: null,
      imageDaemonLogs: "",
      imageDaemonBusy: false,

      runtimeInfo: {
        gateway_backend: "unknown",
        tge_completion_mode: null,
        tge_llm_model: null,
        tge_llm_base_url: null,
        tge_ollama_keep_alive: null,
        tge_runtime_probe_llm_default: null,
        health_ok: false,
        streaming_supported: false,
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

      gpuStats: { available: false, gpu: null, ollama_models: [] },
      _gpuPollId: null,

      campaignForm: {
        namespace: "default",
        name: "",
        actor_id: "",
        files: [],
        on_rails: false,
        creating: false,
        createStatus: "",
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
      playerData: null,
      playerStats: null,
      mediaText: "",
      sessionsText: "",
      memoryText: "",
      smsText: "",
      debugText: "",
      diagnosticsBundleStatus: "",
      campaignExportStatus: "",
      campaignExport: {
        type: "full",
        raw_format: "jsonl",
      },

      /* Campaign flags */
      campaignFlags: {
        guardrails: true,
        on_rails: false,
        timed_events: false,
        difficulty: "normal",
        speed_multiplier: 1.0,
      },

      /* Source material */
      sourceMaterials: [],
      sourceUpload: { label: "", format: "", text: "", replace: true },
      sourceUploadStatus: "",
      campaignRules: [],
      selectedCampaignRule: null,
      campaignRuleLookupKey: "",
      campaignRuleForm: { key: "", value: "", mode: "add" },
      campaignRuleStatus: "",

      /* Campaign setup wizard */
      setupMode: false,
      setupPhase: null,
      setupMessage: "",
      setupResponse: "",
      setupSending: false,
      setupAttachmentText: "",
      setupOnRails: false,

      /* Scene images */
      sceneImages: {},

      /* Literary styles */
      literaryStyles: {},

      /* Source material search */
      sourceSearchQuery: "",
      sourceSearchDocKey: "",
      sourceSearchResults: [],
      sourceSearching: false,
      sourceBrowseKeys: [],

      /* Source material digest ingest */
      digestUpload: { label: "", format: "", text: "", replace: true },
      digestUploadStatus: "",
      digestUploading: false,

      /* Character portrait */
      portraitForm: { slug: "", image_url: "" },
      portraitStatus: "",

      /* Avatar generation */
      avatarGenPrompt: "",
      avatarGenBusy: false,
      avatarGenStatus: "",

      /* Scheduled SMS */
      scheduledSms: { thread: "", sender: "", recipient: "", message: "", delay_seconds: 30 },
      scheduledSmsStatus: "",

      /* Puzzle / Minigame interaction */
      puzzleAnswer: "",
      puzzleStatus: "",
      minigameMove: "",
      minigameBoard: "",
      minigameStatus: "",

      /* Story state (debug) */
      storyState: null,
      rewindTargetTurn: "",
      rewindStatus: "",

      /* Player attributes */
      playerAttributes: null,
      attributeForm: { attribute: "", value: 0 },

      /* Turn history */
      recentTurns: [],

      /* Campaign persona */
      campaignPersona: "",
      campaignPersonaSource: "",
      personaEditText: "",

      /* Game time (extracted from turn state_update) */
      gameTime: {},
      campaignSummary: "",

      async init() {
        await this.loadRuntime();
        await this.refreshCampaigns();
        await this.loadSettingsForm();
        await this.loadImageSettingsForm();
        await this.loadOllamaModels();
        /* watch debug toggle to guard inspector tab */
        this.$watch("$store.app.debugMode", () => this.ensureValidInspectorTab());

        // Restore persisted campaign selection
        const savedCampaignId = localStorage.getItem("selectedCampaignId");
        if (savedCampaignId && this.campaigns.some(c => c.id === savedCampaignId)) {
          await this.selectCampaign(savedCampaignId);
          const savedSessionId = localStorage.getItem("selectedSessionId");
          if (savedSessionId && this.sessionsList.some(s => s.id === savedSessionId)) {
            this.selectSession(savedSessionId);
          } else {
            this.populateTurnStreamFromHistory();
          }
        }

        if (!this.statusMessage.startsWith("Runtime backend:")) {
          this.statusMessage = "Initialized.";
        }
      },

      /* ---- Turn stream hydration from history ---- */
      populateTurnStreamFromHistory() {
        if (!this.recentTurns || this.recentTurns.length === 0) return;
        const sessionId = this.selectedSessionId;
        const entries = [];
        let counter = 0;
        for (const turn of this.recentTurns) {
          if (sessionId && turn.session_id && turn.session_id !== sessionId) continue;
          if (turn.kind === "narrator" || turn.kind === "player") {
            counter++;
            const meta = turn.meta || {};
            const entry = {
              id: counter,
              type: "narrator",
              at: turn.created_at ? new Date(turn.created_at).toLocaleTimeString() : "",
              text: turn.content || "[No content]",
              meta: {},
            };
            if (meta.game_time) {
              entry.meta._game_time = meta.game_time;
              this.gameTime = meta.game_time;
            }
            entries.push(entry);
          }
        }
        this.turnCounter = counter;
        this.turnStream = entries;
        this._scrollStream();
      },

      /* ---- Turn stream filtering ---- */
      visibleTurnStream() {
        if (this.$store.app.debugMode) {
          return this.turnStream;
        }
        return this.turnStream.filter(
          (entry) => entry.type === "narrator" || entry.type === "notice" || entry.type === "image_prompt" || entry.type === "dice"
        );
      },

      /* Deduplicated actor list for the current campaign */
      uniqueActors() {
        const seen = new Set();
        const result = [];
        for (const c of this.campaigns) {
          if (c.id === this.selectedCampaignId && c.actor_id && !seen.has(c.actor_id)) {
            seen.add(c.actor_id);
            result.push(c.actor_id);
          }
        }
        return result;
      },

      /* Guard inspector tab when toggling debug off */
      ensureValidInspectorTab() {
        const normalTabs = ["map", "player", "campaign"];
        if (!this.$store.app.debugMode && !normalTabs.includes(this.inspectorTab)) {
          this.inspectorTab = "map";
        }
      },

      /* ---- Settings methods ---- */
      async loadSettingsForm() {
        try {
          const data = await this.api("/api/settings");
          this.settingsForm.completion_mode = data.completion_mode || "ollama";
          this.settingsForm.base_url = data.base_url || "";
          this.settingsForm.model = data.model || "";
          this.settingsForm.temperature = typeof data.temperature === "number" ? data.temperature : 0.8;
          this.settingsForm.max_tokens = typeof data.max_tokens === "number" ? data.max_tokens : 3200;
          this.settingsForm.timeout_seconds = typeof data.timeout_seconds === "number" ? data.timeout_seconds : 90;
          this.settingsForm.keep_alive = data.keep_alive || "30m";
          this.settingsForm.ollama_options_json = JSON.stringify(data.ollama_options || {}, null, 2);
        } catch (_err) {
          /* settings endpoint may not exist for inmemory backend */
        }
      },

      async loadOllamaModels() {
        try {
          const data = await this.api("/api/ollama/models");
          if (data.reachable && Array.isArray(data.models)) {
            this.ollamaModels = data.models;
            /* ensure current model appears in the list so the dropdown doesn't reset */
            const currentModel = (this.settingsForm.model || "").trim();
            if (currentModel && !this.ollamaModels.some((m) => m.name === currentModel)) {
              this.ollamaModels.unshift({ name: currentModel, size: null, modified_at: null });
            }
          } else {
            this.ollamaModels = [];
          }
        } catch (_err) {
          this.ollamaModels = [];
        }
      },

      async testConnection() {
        this.settingsSaving = true;
        this.settingsStatus = { ok: null, message: "Testing connection..." };
        try {
          const data = await this.api("/api/runtime/checks?probe_llm=true");
          const llm = data.checks && data.checks.llm;
          if (llm && llm.ok === true) {
            this.settingsStatus = { ok: true, message: "Connection OK: " + (llm.detail || "LLM responded.") };
          } else {
            this.settingsStatus = { ok: false, message: "Connection failed: " + (llm && llm.detail ? llm.detail : "Unknown error.") };
          }
        } catch (err) {
          this.settingsStatus = { ok: false, message: "Connection test failed: " + String(err) };
        }
        this.settingsSaving = false;
      },

      async applySettings() {
        this.settingsSaving = true;
        this.settingsStatus = { ok: null, message: "Applying..." };
        try {
          const payload = {
            completion_mode: this.settingsForm.completion_mode,
            base_url: this.settingsForm.base_url,
            model: this.settingsForm.model,
            temperature: this.settingsForm.temperature,
            max_tokens: this.settingsForm.max_tokens,
            timeout_seconds: this.settingsForm.timeout_seconds,
            keep_alive: this.settingsForm.keep_alive,
          };
          const optionsRaw = (this.settingsForm.ollama_options_json || "").trim();
          if (optionsRaw && optionsRaw !== "{}") {
            try {
              payload.ollama_options = JSON.parse(optionsRaw);
            } catch (_e) {
              this.settingsStatus = { ok: false, message: "Invalid Ollama Options JSON." };
              this.settingsSaving = false;
              return;
            }
          }
          const result = await this.api("/api/settings", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.settingsStatus = { ok: true, message: result.note || "Settings applied." };
          await this.loadSettingsForm();
          await this.loadRuntime();
          await this.loadOllamaModels();
          // Auto-probe after apply
          try {
            const probeData = await this.api("/api/runtime/checks?probe_llm=true");
            const llm = probeData.checks && probeData.checks.llm;
            if (llm && llm.ok === true) {
              this.settingsStatus = { ok: true, message: "Applied & verified: LLM responding." };
            } else if (llm) {
              this.settingsStatus = { ok: true, message: "Applied, but LLM probe: " + (llm.detail || "no response.") };
            }
          } catch (_probeErr) {
            /* probe failure is non-fatal */
          }
        } catch (err) {
          this.settingsStatus = { ok: false, message: "Failed: " + String(err) };
        }
        this.settingsSaving = false;
      },

      /* ---- Image settings methods ---- */
      async loadImageSettingsForm() {
        try {
          const data = await this.api("/api/settings/image");
          const f = this.imageSettingsForm;
          f.image_backend = data.image_backend || "none";
          f.diffusers_host = data.diffusers_host || "127.0.0.1";
          f.diffusers_port = typeof data.diffusers_port === "number" ? data.diffusers_port : 8189;
          f.diffusers_model = data.diffusers_model || "";
          f.diffusers_device = data.diffusers_device || "cuda";
          f.diffusers_dtype = data.diffusers_dtype || "bf16";
          f.diffusers_offload = data.diffusers_offload || "none";
          f.diffusers_quantization = data.diffusers_quantization || "none";
          f.diffusers_vae_tiling = typeof data.diffusers_vae_tiling === "boolean" ? data.diffusers_vae_tiling : true;
          f.diffusers_autostart = typeof data.diffusers_autostart === "boolean" ? data.diffusers_autostart : false;
          f.comfyui_url = data.comfyui_url || "http://127.0.0.1:8188";
          f.comfyui_workflow_json = data.comfyui_workflow_json || "";
          f.image_width = typeof data.image_width === "number" ? data.image_width : 1024;
          f.image_height = typeof data.image_height === "number" ? data.image_height : 1024;
          f.image_steps = typeof data.image_steps === "number" ? data.image_steps : 20;
          f.image_guidance_scale = typeof data.image_guidance_scale === "number" ? data.image_guidance_scale : 3.5;
          f.image_cache_max_entries = typeof data.image_cache_max_entries === "number" ? data.image_cache_max_entries : 50;
          this.imageDaemonState = data.daemon_state || null;
          // Fetch recent logs when daemon is in error state
          if (this.imageDaemonState === "error") {
            try {
              const logData = await this.api("/api/image/daemon/logs");
              const lines = logData.logs || [];
              this.imageDaemonLogs = lines.slice(-20).join("\n");
            } catch (_logErr) {
              this.imageDaemonLogs = "";
            }
          } else {
            this.imageDaemonLogs = "";
          }
        } catch (_err) {
          /* image settings endpoint may not exist */
        }
      },

      async applyImageSettings() {
        this.imageSettingsSaving = true;
        this.imageSettingsStatus = { ok: null, message: "Applying..." };
        try {
          const f = this.imageSettingsForm;
          const payload = {
            image_backend: f.image_backend,
            diffusers_host: f.diffusers_host,
            diffusers_port: f.diffusers_port,
            diffusers_model: f.diffusers_model || null,
            diffusers_device: f.diffusers_device,
            diffusers_dtype: f.diffusers_dtype,
            diffusers_offload: f.diffusers_offload,
            diffusers_quantization: f.diffusers_quantization,
            diffusers_vae_tiling: f.diffusers_vae_tiling,
            diffusers_autostart: f.diffusers_autostart,
            comfyui_url: f.comfyui_url,
            comfyui_workflow_json: f.comfyui_workflow_json || null,
            image_width: f.image_width,
            image_height: f.image_height,
            image_steps: f.image_steps,
            image_guidance_scale: f.image_guidance_scale,
            image_cache_max_entries: f.image_cache_max_entries,
          };
          const result = await this.api("/api/settings/image", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          let msg = "Image settings applied.";
          if (result.daemon_restarted) {
            msg += " Daemon restarted with new settings.";
          }
          if (result.restart_required) {
            msg += " Server restart required for some changes to take effect.";
          }
          this.imageSettingsStatus = { ok: true, message: msg };
          await this.loadImageSettingsForm();
        } catch (err) {
          this.imageSettingsStatus = { ok: false, message: "Failed: " + String(err) };
        }
        this.imageSettingsSaving = false;
      },

      async startImageDaemon() {
        this.imageDaemonBusy = true;
        this.imageSettingsStatus = { ok: null, message: "Starting daemon..." };
        try {
          const result = await this.api("/api/image/daemon/start", { method: "POST" });
          if (result.status === "error") {
            this.imageSettingsStatus = { ok: false, message: "Daemon failed: " + (result.message || "unknown error") };
          } else if (result.status === "already_running") {
            this.imageSettingsStatus = { ok: true, message: "Daemon is already running." };
          } else {
            this.imageSettingsStatus = { ok: true, message: "Daemon started." };
          }
        } catch (err) {
          this.imageSettingsStatus = { ok: false, message: "Start failed: " + String(err) };
        }
        await this.loadImageSettingsForm();
        this.imageDaemonBusy = false;
      },

      async stopImageDaemon() {
        this.imageDaemonBusy = true;
        this.imageSettingsStatus = { ok: null, message: "Stopping daemon..." };
        try {
          const result = await this.api("/api/image/daemon/stop", { method: "POST" });
          if (result.status === "already_stopped") {
            this.imageSettingsStatus = { ok: true, message: "Daemon was already stopped." };
          } else {
            this.imageSettingsStatus = { ok: true, message: "Daemon stopped." };
          }
        } catch (err) {
          this.imageSettingsStatus = { ok: false, message: "Stop failed: " + String(err) };
        }
        await this.loadImageSettingsForm();
        this.imageDaemonBusy = false;
      },

      async generateImage(entry) {
        if (entry._imgGenerating) return;
        entry._imgGenerating = true;
        entry._imgError = "";
        entry._imgUrl = "";
        try {
          const result = await this.api("/api/image/generate", {
            method: "POST",
            body: JSON.stringify({ prompt: entry.text }),
          });
          const jobId = result.job_id;
          if (!jobId) {
            entry._imgError = result.detail || "No job ID returned.";
            entry._imgGenerating = false;
            return;
          }
          // Poll for completion
          for (let i = 0; i < 120; i++) {
            await new Promise((r) => setTimeout(r, 2000));
            const status = await this.api(`/api/image/status/${encodeURIComponent(jobId)}`);
            if (status.status === "completed") {
              entry._imgUrl = status.image_url || "";
              entry._imgGenerating = false;
              return;
            }
            if (status.status === "failed" || status.status === "interrupted") {
              entry._imgError = status.error || status.status;
              entry._imgGenerating = false;
              return;
            }
          }
          entry._imgError = "Generation timed out.";
        } catch (err) {
          entry._imgError = String(err);
        }
        entry._imgGenerating = false;
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
        if (this.selectedSessionId) {
          localStorage.setItem("selectedSessionId", this.selectedSessionId);
        } else {
          localStorage.removeItem("selectedSessionId");
        }
        this.syncTurnSessionSelection();
        this.turnStream = [];
        this.connectSocket();
        this.populateTurnStreamFromHistory();
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
          this.runtimeInfo.streaming_supported = runtime.streaming_supported === true;

          const health = await this.api("/api/health");
          this.runtimeInfo.health_ok = health.ok === true;
          await this.runRuntimeChecks(false);

          this.statusMessage = `Runtime backend: ${this.runtimeInfo.gateway_backend}.`;

          await this.loadGpuStats();
          if (this.gpuStats.available && !this._gpuPollId) {
            this._gpuPollId = setInterval(() => this.loadGpuStats(), 15000);
          }
        } catch (error) {
          this.runtimeInfo.health_ok = false;
          this.errorMessage = String(error);
        }
      },

      async loadGpuStats() {
        try {
          const data = await this.api("/api/gpu-stats");
          this.gpuStats = data;
        } catch (_) {
          this.gpuStats = { available: false, gpu: null, ollama_models: [] };
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

      async exportCampaignBundle() {
        this.resetError();
        this.campaignExportStatus = "";
        if (!this.selectedCampaignId) {
          this.errorMessage = "Select a campaign first.";
          return;
        }
        try {
          const params = new URLSearchParams();
          params.set("export_type", this.campaignExport.type || "full");
          params.set("raw_format", this.campaignExport.raw_format || "jsonl");
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/export?${params.toString()}`);
          const files = Array.isArray(body.files) ? body.files : [];
          if (!files.length) {
            this.campaignExportStatus = `No export files returned at ${nowLabel()}.`;
            return;
          }
          for (const row of files) {
            const filename = String((row && row.filename) || "campaign-export.txt").trim() || "campaign-export.txt";
            const content = String((row && row.content) || "");
            const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
            const href = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = href;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(href);
          }
          this.campaignExportStatus = `Downloaded ${files.length} export file(s) at ${nowLabel()}.`;
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Campaign flags ---- */
      async loadCampaignFlags() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/flags`);
          this.campaignFlags.guardrails = !!data.guardrails;
          this.campaignFlags.on_rails = !!data.on_rails;
          this.campaignFlags.timed_events = !!data.timed_events;
          this.campaignFlags.difficulty = data.difficulty || "normal";
          this.campaignFlags.speed_multiplier = typeof data.speed_multiplier === "number" ? data.speed_multiplier : 1.0;
        } catch (_) { /* non-critical */ }
      },

      async setCampaignFlag(key, value) {
        if (!this.selectedCampaignId) return;
        try {
          const payload = {};
          payload[key] = value;
          await this.api(`/api/campaigns/${this.selectedCampaignId}/flags`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          await this.loadCampaignFlags();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Source material ---- */
      async loadSourceMaterials() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/source-materials`);
          this.sourceMaterials = Array.isArray(data.documents) ? data.documents : [];
        } catch (_) { /* non-critical */ }
      },

      async loadCampaignRules(key = "") {
        if (!this.selectedCampaignId) return;
        try {
          const query = key ? `?key=${encodeURIComponent(key)}` : "";
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/campaign-rules${query}`);
          if (key) {
            this.selectedCampaignRule = data.rule || null;
          } else {
            this.campaignRules = Array.isArray(data.rules) ? data.rules : [];
            if (this.selectedCampaignRule && this.selectedCampaignRule.key) {
              const current = this.campaignRules.find((row) => row.key === this.selectedCampaignRule.key);
              if (current) this.selectedCampaignRule = current;
            }
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async ingestSourceMaterial() {
        if (!this.selectedCampaignId) return;
        this.sourceUploadStatus = "";
        const text = (this.sourceUpload.text || "").trim();
        if (!text) return;
        try {
          const payload = { text };
          if (this.sourceUpload.label.trim()) payload.document_label = this.sourceUpload.label.trim();
          if (this.sourceUpload.format) payload.format = this.sourceUpload.format;
          payload.replace_document = this.sourceUpload.replace;
          await this.api(`/api/campaigns/${this.selectedCampaignId}/source-materials`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          this.sourceUploadStatus = `Uploaded at ${nowLabel()}.`;
          this.sourceUpload.text = "";
          this.sourceUpload.label = "";
          await this.loadSourceMaterials();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async saveCampaignRule() {
        if (!this.selectedCampaignId) return;
        this.campaignRuleStatus = "";
        const key = (this.campaignRuleForm.key || "").trim();
        const value = (this.campaignRuleForm.value || "").trim();
        if (!key || !value) return;
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/campaign-rules`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              key,
              value,
              upsert: String(this.campaignRuleForm.mode || "add") === "upsert",
            }),
          });
          if (body && body.ok === false && body.reason === "exists") {
            this.campaignRuleStatus = `Rule already exists. Old: ${body.old_value}`;
            return;
          }
          this.campaignRuleStatus = body && body.replaced ? `Updated ${key}.` : `Added ${key}.`;
          this.selectedCampaignRule = { key, value };
          await this.loadCampaignRules();
          await this.loadCampaignRules(key);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Campaign setup ---- */
      async checkSetupMode() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/setup`);
          this.setupMode = !!data.in_setup;
          this.setupPhase = data.setup_phase || null;
        } catch (_) {
          this.setupMode = false;
          this.setupPhase = null;
        }
      },

      async startCampaignSetup() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        this.setupSending = true;
        try {
          const payload = {
            actor_id: (this.turnForm.actor_id || "").trim() || null,
            on_rails: this.setupOnRails,
            attachment_text: (this.setupAttachmentText || "").trim() || null,
          };
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/setup/start`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.setupResponse = result.message || "";
          this.setupPhase = result.setup_phase || null;
          this.setupMode = !!result.setup_phase;
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this.setupSending = false;
        }
      },

      async sendSetupMessage() {
        this.resetError();
        if (!this.selectedCampaignId || !this.setupMessage.trim()) return;
        this.setupSending = true;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/setup/message`, {
            method: "POST",
            body: JSON.stringify({
              actor_id: (this.turnForm.actor_id || "").trim(),
              message: this.setupMessage.trim(),
            }),
          });
          this.setupResponse = result.message || "";
          this.setupPhase = result.setup_phase || null;
          this.setupMessage = "";
          if (result.completed) {
            this.setupMode = false;
            this.setupPhase = null;
            this.pushStream("notice", "Campaign setup completed!", { setup: true });
            /* Reload campaign data after setup completion */
            await Promise.all([
              this.loadMap(),
              this.loadPlayerState(),
              this.loadPlayerStatistics(),
              this.loadPlayerAttributes(),
              this.loadDebugSnapshot(),
              this.loadCampaignFlags(),
              this.loadStoryState(),
              this.loadCampaignPersona(),
              this.loadSceneImages(),
              this.loadLiteraryStyles(),
              this.loadSourceMaterials(),
            ]);
          }
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this.setupSending = false;
        }
      },

      /* ---- Scene images ---- */
      async loadSceneImages() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/scene-images`);
          this.sceneImages = data.images || {};
        } catch (_) { this.sceneImages = {}; }
      },

      /* ---- Literary styles ---- */
      async loadLiteraryStyles() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/literary-styles`);
          this.literaryStyles = data.styles || {};
        } catch (_) { this.literaryStyles = {}; }
      },

      /* ---- SMS cancel ---- */
      async cancelSmsDeliveries() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/sms/cancel`, {
            method: "POST",
          });
          if (result.ok) {
            this.statusMessage = `Cancelled ${result.cancelled} pending SMS delivery(ies).`;
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Source material search ---- */
      async searchSourceMaterial() {
        this.resetError();
        if (!this.selectedCampaignId || !this.sourceSearchQuery.trim()) return;
        this.sourceSearching = true;
        try {
          const body = { query: this.sourceSearchQuery.trim(), top_k: 5 };
          if (this.sourceSearchDocKey.trim()) body.document_key = this.sourceSearchDocKey.trim();
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/source-materials/search`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
          });
          this.sourceSearchResults = data.results || [];
        } catch (error) { this.errorMessage = String(error); }
        this.sourceSearching = false;
      },

      async browseSourceKeys() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/source-materials/browse`);
          this.sourceBrowseKeys = data.keys || [];
        } catch (_) { this.sourceBrowseKeys = []; }
      },

      /* ---- Digest ingest ---- */
      async ingestWithDigest() {
        this.resetError();
        if (!this.selectedCampaignId || !this.digestUpload.text.trim() || !this.digestUpload.label.trim()) return;
        this.digestUploading = true;
        this.digestUploadStatus = "Ingesting with digest (this may take a while)...";
        try {
          const body = {
            text: this.digestUpload.text.trim(),
            document_label: this.digestUpload.label.trim(),
            replace_document: this.digestUpload.replace,
          };
          if (this.digestUpload.format) body.format = this.digestUpload.format;
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/source-materials/digest`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
          });
          if (data.ok) {
            const profileCount = Object.keys(data.literary_profiles || {}).length;
            this.digestUploadStatus = `Stored ${data.chunks_stored} chunks (${data.document_key}). ${profileCount} literary profile(s) extracted.`;
            this.digestUpload.text = "";
            await Promise.all([this.loadSourceMaterials(), this.loadLiteraryStyles()]);
          } else {
            this.digestUploadStatus = "Ingest failed.";
          }
        } catch (error) {
          this.digestUploadStatus = "Error: " + String(error);
        }
        this.digestUploading = false;
      },

      /* ---- Character portrait ---- */
      async recordCharacterPortrait() {
        this.resetError();
        if (!this.selectedCampaignId || !this.portraitForm.slug.trim() || !this.portraitForm.image_url.trim()) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/roster/portrait`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ character_slug: this.portraitForm.slug.trim(), image_url: this.portraitForm.image_url.trim() }),
          });
          this.portraitStatus = data.ok ? `Portrait set for ${data.character_slug}.` : "Failed to set portrait.";
          if (data.ok) { this.portraitForm.slug = ""; this.portraitForm.image_url = ""; }
        } catch (error) { this.portraitStatus = "Error: " + String(error); }
      },

      /* ---- Avatar generation ---- */
      async generateAvatar() {
        const prompt = (this.avatarGenPrompt || "").trim();
        if (!prompt || !this.selectedCampaignId) return;
        const actorId = this.resolveMediaActorId();
        this.avatarGenBusy = true;
        this.avatarGenStatus = "Submitting...";
        try {
          // 1. Start generation
          const gen = await this.api(`/api/campaigns/${this.selectedCampaignId}/media/avatar/generate`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actorId, prompt }),
          });
          const jobId = gen.job_id;
          if (!jobId) {
            this.avatarGenStatus = gen.detail || "No job ID returned.";
            this.avatarGenBusy = false;
            return;
          }
          // 2. Poll for completion
          this.avatarGenStatus = "Generating...";
          let imageUrl = "";
          for (let i = 0; i < 120; i++) {
            await new Promise((r) => setTimeout(r, 2000));
            const status = await this.api(`/api/image/status/${encodeURIComponent(jobId)}`);
            if (status.status === "completed") {
              imageUrl = status.image_url || "";
              break;
            }
            if (status.status === "failed" || status.status === "interrupted") {
              this.avatarGenStatus = "Generation failed: " + (status.error || status.status);
              this.avatarGenBusy = false;
              return;
            }
          }
          if (!imageUrl) {
            this.avatarGenStatus = "Generation timed out.";
            this.avatarGenBusy = false;
            return;
          }
          // 3. Commit as pending avatar
          this.avatarGenStatus = "Setting as pending avatar...";
          await this.api(`/api/campaigns/${this.selectedCampaignId}/media/avatar/commit`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actorId, image_url: imageUrl, prompt }),
          });
          this.avatarGenStatus = "Avatar generated! Review it below.";
          this.avatarGenPrompt = "";
          await this.loadPlayerState();
        } catch (err) {
          this.avatarGenStatus = "Error: " + String(err);
        }
        this.avatarGenBusy = false;
      },

      /* ---- Scheduled SMS ---- */
      async scheduleSmsDelivery() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const s = this.scheduledSms;
        if (!s.thread.trim() || !s.sender.trim() || !s.recipient.trim() || !s.message.trim()) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/sms/schedule`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              thread: s.thread.trim(), sender: s.sender.trim(),
              recipient: s.recipient.trim(), message: s.message.trim(),
              delay_seconds: Number(s.delay_seconds) || 30,
            }),
          });
          if (data.ok) {
            this.scheduledSmsStatus = `Scheduled in ${data.delay_seconds}s.`;
            this.scheduledSms.message = "";
          } else {
            this.scheduledSmsStatus = data.reason || "Scheduling failed.";
          }
        } catch (error) { this.scheduledSmsStatus = "Error: " + String(error); }
      },

      /* ---- Campaign delete ---- */
      async deleteCampaign() {
        if (!this.selectedCampaignId) return;
        if (!confirm("Delete this campaign and all its data? This cannot be undone.")) return;
        this.resetError();
        try {
          await this.api(`/api/campaigns/${this.selectedCampaignId}`, { method: "DELETE" });
          this.statusMessage = "Campaign deleted.";
          if (this.socket) {
            this.socket._deliberateClose = true;
            this.socket.close();
            this.socket = null;
          }
          if (this.socketReconnectTimer) {
            clearTimeout(this.socketReconnectTimer);
            this.socketReconnectTimer = null;
          }
          this.selectedCampaignId = null;
          localStorage.removeItem("selectedCampaignId");
          localStorage.removeItem("selectedSessionId");
          this.turnStream = [];
          this.sessions = [];
          await this.refreshCampaigns();
        } catch (error) { this.errorMessage = String(error); }
      },

      /* ---- Puzzle interaction ---- */
      async getPuzzleHint() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/puzzle/hint`);
          if (result.hint) {
            this.pushStream("notice", `Hint: ${result.hint}`, { hint: true });
            this.puzzleStatus = `Hint ${result.hints_used}/${result.hints_total}`;
          } else {
            this.puzzleStatus = result.note || "No hints available.";
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async submitPuzzleAnswer() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const answer = (this.puzzleAnswer || "").trim();
        if (!answer) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/puzzle/answer`, {
            method: "POST",
            body: JSON.stringify({ answer }),
          });
          if (result.correct) {
            this.pushStream("notice", `Correct! ${result.feedback}`, { puzzle: true });
          } else {
            this.pushStream("notice", `Wrong: ${result.feedback} (${result.attempts}/${result.max_attempts})`, { puzzle: true });
          }
          this.puzzleAnswer = "";
          this.puzzleStatus = result.solved ? "Solved!" : (result.failed ? "Failed." : "");
          await this.loadStoryState();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Minigame interaction ---- */
      async loadMinigameBoard() {
        if (!this.selectedCampaignId) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/minigame/board`);
          this.minigameBoard = result.board || "";
          this.minigameStatus = result.finished ? `Finished (${result.status})` : (result.status || "");
        } catch (_) { this.minigameBoard = ""; }
      },

      async submitMinigameMove() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const move = (this.minigameMove || "").trim();
        if (!move) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/minigame/move`, {
            method: "POST",
            body: JSON.stringify({ move }),
          });
          if (result.valid) {
            this.pushStream("notice", result.message, { minigame: true });
          } else {
            this.pushStream("notice", `Invalid move: ${result.message}`, { minigame: true });
          }
          this.minigameMove = "";
          this.minigameBoard = result.board || "";
          this.minigameStatus = result.finished ? `Finished (${result.status})` : (result.status || "");
          await this.loadStoryState();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Story state (debug) ---- */
      async loadStoryState() {
        if (!this.selectedCampaignId) return;
        try {
          this.storyState = await this.api(`/api/campaigns/${this.selectedCampaignId}/story`);
        } catch (_) { this.storyState = null; }
      },

      /* ---- Rewind ---- */
      async rewindToTurn() {
        this.resetError();
        this.rewindStatus = "";
        if (!this.selectedCampaignId) {
          this.errorMessage = "Select a campaign first.";
          return;
        }
        const turnId = parseInt(this.rewindTargetTurn, 10);
        if (!Number.isFinite(turnId) || turnId <= 0) {
          this.errorMessage = "Enter a valid turn ID (positive integer).";
          return;
        }
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/rewind?target_turn_id=${turnId}`, {
            method: "POST",
          });
          if (result.ok === false) {
            this.rewindStatus = result.note || "Rewind not supported.";
            return;
          }
          this.rewindStatus = `Rewound to turn ${turnId} at ${nowLabel()}.`;
          this.rewindTargetTurn = "";
          this.pushStream("notice", `Rewound to turn ${turnId}`, { rewind: true });
          /* Reload all state after rewind */
          await Promise.all([
            this.loadMap(),
            this.loadTimers(),
            this.loadCalendar(),
            this.loadRoster(),
            this.loadPlayerState(),
            this.loadPlayerStatistics(),
            this.loadPlayerAttributes(),
            this.loadMedia(),
            this.loadDebugSnapshot(),
            this.loadCampaignFlags(),
            this.loadRecentTurns(),
            this.loadStoryState(),
            this.loadSceneImages(),
          ]);
        } catch (error) {
          this.errorMessage = String(error);
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

      _allowedFileExtensions: [".txt", ".md"],

      _addCampaignFiles(files) {
        const existing = new Set(this.campaignForm.files.map(f => f.file.name));
        for (const file of files) {
          if (existing.has(file.name)) continue;
          const ext = file.name.includes(".") ? "." + file.name.split(".").pop().toLowerCase() : "";
          if (!this._allowedFileExtensions.includes(ext)) continue;
          existing.add(file.name);
          const entry = { file, text: "", status: "reading", _ready: null };
          entry._ready = new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => { entry.text = e.target.result; entry.status = "ready"; resolve(); };
            reader.onerror = () => { entry.status = "error"; reject(new Error("Failed to read " + file.name)); };
            reader.readAsText(file);
          });
          this.campaignForm.files.push(entry);
        }
      },

      handleFileSelect(event) {
        this._addCampaignFiles(Array.from(event.target.files || []));
        event.target.value = "";
      },

      handleFileDrop(event) {
        this._addCampaignFiles(Array.from(event.dataTransfer.files || []));
      },

      removeUploadedFile(index) {
        this.campaignForm.files.splice(index, 1);
      },

      async createCampaign() {
        this.resetError();
        if (!this.campaignForm.name.trim() || !this.campaignForm.actor_id.trim()) return;
        this.campaignForm.creating = true;
        this.campaignForm.createStatus = "Creating campaign...";
        try {
          // 1. Create campaign
          const body = await this.api("/api/campaigns", {
            method: "POST",
            body: JSON.stringify({
              namespace: this.campaignForm.namespace || "default",
              name: this.campaignForm.name.trim(),
              actor_id: this.campaignForm.actor_id.trim(),
            }),
          });
          const campaign = body.campaign;
          await this.refreshCampaigns();
          await this.selectCampaign(campaign.id);
          await this.ensureSharedWindow();

          // 2. Wait for all file reads to complete
          if (this.campaignForm.files.length > 0) {
            this.campaignForm.createStatus = "Reading files...";
            await Promise.allSettled(this.campaignForm.files.map(f => f._ready));
            const readErrors = this.campaignForm.files.filter(f => f.status === "error");
            if (readErrors.length > 0) {
              const names = readErrors.map(f => f.file.name).join(", ");
              this.campaignForm.createStatus = `Could not read: ${names}. Continuing with remaining files...`;
              await new Promise(r => setTimeout(r, 1500));
            }
          }

          // 3. Ingest each file via digest endpoint
          const allTexts = [];
          for (let i = 0; i < this.campaignForm.files.length; i++) {
            const f = this.campaignForm.files[i];
            if (!f.text || !f.text.trim()) continue;
            f.status = "uploading";
            this.campaignForm.createStatus = `Ingesting document ${i + 1}/${this.campaignForm.files.length}: ${f.file.name}...`;
            try {
              await this.api(`/api/campaigns/${campaign.id}/source-materials/digest`, {
                method: "POST",
                body: JSON.stringify({
                  text: f.text,
                  document_label: f.file.name.replace(/\.[^.]+$/, ""),
                  format: null,
                  replace_document: true,
                }),
              });
              f.status = "done";
              allTexts.push(f.text);
            } catch (err) {
              f.status = "error";
              console.warn("Digest ingest failed for", f.file.name, err);
            }
          }

          // 4. Start setup wizard with combined text
          if (allTexts.length > 0) {
            this.campaignForm.createStatus = "Starting setup wizard...";
            try {
              await this.api(`/api/campaigns/${campaign.id}/setup/start`, {
                method: "POST",
                body: JSON.stringify({
                  actor_id: this.campaignForm.actor_id.trim(),
                  on_rails: this.campaignForm.on_rails,
                  attachment_text: allTexts.join("\n\n---\n\n"),
                }),
              });
              await this.checkSetupMode();
            } catch (err) {
              console.warn("Setup wizard start failed:", err);
            }
          }

          // 5. Clean up form
          this.campaignForm.name = "";
          this.campaignForm.files = [];
          this.campaignForm.on_rails = false;
          this.campaignForm.createStatus = "";
          this.$nextTick(() => {
            const input = document.getElementById("action-input");
            if (input) input.focus();
          });
          this.statusMessage = `Created campaign ${campaign.name}.`;
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this.campaignForm.creating = false;
        }
      },

      async selectCampaign(campaignId) {
        this.resetError();
        this.selectedCampaignId = campaignId;
        localStorage.setItem("selectedCampaignId", campaignId);
        this.selectedSessionId = "";
        localStorage.removeItem("selectedSessionId");
        this.turnStream = [];
        /* Reset per-campaign derived state to prevent stale values */
        this.gameTime = {};
        this.campaignSummary = "";
        this.storyState = null;
        this.playerData = null;
        this.playerStats = null;
        this.playerAttributes = null;
        this.recentTurns = [];
        this.campaignPersona = "";
        this.campaignPersonaSource = "";
        this.personaEditText = "";
        this.minigameBoard = "";
        this.minigameStatus = "";
        this.puzzleStatus = "";
        this.mapText = "";
        this.timersText = "";
        this.calendarText = "";
        this.rosterText = "";
        this.playerStateText = "";
        this.mediaText = "";
        this.sessionsText = "";
        this.memoryText = "";
        this.smsText = "";
        this.debugText = "";
        this.sourceMaterials = [];
        this.campaignRules = [];
        this.selectedCampaignRule = null;
        this.setupMode = false;
        this.setupPhase = null;
        this.setupResponse = "";
        this.sceneImages = {};
        this.literaryStyles = {};
        this.sourceSearchResults = [];
        this.sourceBrowseKeys = [];
        this.digestUploadStatus = "";
        this.portraitStatus = "";
        this.scheduledSmsStatus = "";
        const selected = this.campaigns.find((row) => row.id === campaignId);
        if (selected) {
          this.turnForm.actor_id = selected.actor_id;
        }
        if (this.turnForm.actor_id) {
          this.mediaActions.actor_id = this.mediaActions.actor_id || this.turnForm.actor_id;
          this.rosterActions.slug = this.rosterActions.slug || this.turnForm.actor_id;
          this.rosterActions.player = true;
        }
        await Promise.all([
          this.loadSessions(),
          this.loadMap(),
          this.loadTimers(),
          this.loadCalendar(),
          this.loadRoster(),
          this.loadPlayerState(),
          this.loadPlayerStatistics(),
          this.loadPlayerAttributes(),
          this.loadMedia(),
          this.loadDebugSnapshot(),
          this.loadCampaignFlags(),
          this.loadSourceMaterials(),
          this.loadCampaignRules(),
          this.loadRecentTurns(),
          this.loadCampaignPersona(),
          this.checkSetupMode(),
          this.loadSceneImages(),
          this.loadLiteraryStyles(),
          this.loadStoryState(),
        ]);
        this.populateTurnStreamFromHistory();
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
          this.socket._deliberateClose = true;
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
          let payload;
          try {
            payload = JSON.parse(event.data);
          } catch (_err) {
            console.warn("WebSocket: malformed JSON frame ignored", event.data);
            return;
          }
          if (payload.type === "turn" && payload.payload) {
            /* Suppress echo: if we just submitted a turn, skip the WS echo to avoid duplicates */
            const isOwnEcho = this._submittingTurn
              && payload.actor_id === (this.turnForm.actor_id || "").trim();
            if (!isOwnEcho) {
              normalizeTurnNotices(payload.payload).forEach((notice) => {
                this.pushStream("notice", notice, { notice });
              });
              /* XP gain notification from WS */
              if (typeof payload.payload.xp_awarded === "number" && payload.payload.xp_awarded > 0) {
                this.pushStream("notice", `+${payload.payload.xp_awarded} XP`, { xp: true });
              }
              const wsMeta = { ...payload.payload };
              if (wsMeta.state_update && wsMeta.state_update.game_time) {
                wsMeta._game_time = wsMeta.state_update.game_time;
                this.gameTime = wsMeta.state_update.game_time;
              }
              this.pushStream("narrator", normalizeTurnNarration(payload.payload), wsMeta);
              if (payload.payload.reasoning) {
                this.pushStream("reasoning", payload.payload.reasoning, payload.payload);
              }
              if (payload.payload.image_prompt) {
                this.pushStream("image_prompt", payload.payload.image_prompt, payload.payload);
              }
              if (payload.payload.dice_result && payload.payload.dice_result.attribute) {
                const d = payload.payload.dice_result;
                const label = d.success ? "SUCCESS" : "FAIL";
                const text = `${d.attribute} check (DC ${d.dc}): rolled ${d.roll} + ${d.modifier} = ${d.total} — ${label}`;
                this.pushStream("dice", text, d);
              }
              if (payload.payload.active_puzzle && payload.payload.active_puzzle.puzzle_type) {
                this.pushStream("notice", `A puzzle has begun: ${payload.payload.active_puzzle.puzzle_type}`, { puzzle: true });
              }
              if (payload.payload.active_minigame && payload.payload.active_minigame.game_type) {
                this.pushStream("notice", `A minigame challenge: ${payload.payload.active_minigame.game_type}`, { minigame: true });
              }
            }
            this.loadTimers();
            this.loadStoryState();
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
        this.socket.onclose = (event) => {
          this.diagnostics.ws_state = "disconnected";
          if (event.target._deliberateClose) {
            return;
          }
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

      _scrollStream() {
        this.$nextTick(() => {
          const stream = document.getElementById("turn-stream");
          if (stream) stream.scrollTop = stream.scrollHeight;
        });
      },

      _handleStreamEvent(eventType, data, streamEntryId) {
        if (eventType === "phase") {
          const labels = { starting: "Starting turn...", generating: "Generating narration...", narrating: "Streaming narration..." };
          this.statusMessage = labels[data.phase] || `Phase: ${data.phase}`;
        } else if (eventType === "token") {
          this._streamingNarration += data.text;
          const entry = this.turnStream.find((e) => e.id === streamEntryId);
          if (entry) entry.text = this._streamingNarration;
          this._scrollStream();
        } else if (eventType === "complete") {
          const entry = this.turnStream.find((e) => e.id === streamEntryId);
          if (entry) {
            entry.text = normalizeTurnNarration(data);
            entry._streaming = false;
            entry.meta = { ...data };
            if (data.state_update && data.state_update.game_time) {
              entry.meta._game_time = data.state_update.game_time;
            }
          }
          /* Supplementary entries — same as non-streaming path */
          normalizeTurnNotices(data).forEach((notice) => {
            this.pushStream("notice", notice, { notice });
          });
          if (typeof data.xp_awarded === "number" && data.xp_awarded > 0) {
            this.pushStream("notice", `+${data.xp_awarded} XP`, { xp: true });
          }
          if (data.reasoning) {
            this.pushStream("reasoning", data.reasoning, data);
          }
          if (data.image_prompt) {
            this.pushStream("image_prompt", data.image_prompt, data);
          }
          if (data.dice_result && data.dice_result.attribute) {
            const d = data.dice_result;
            const label = d.success ? "SUCCESS" : "FAIL";
            const text = `${d.attribute} check (DC ${d.dc}): rolled ${d.roll} + ${d.modifier} = ${d.total} — ${label}`;
            this.pushStream("dice", text, d);
          }
          if (data.active_puzzle && data.active_puzzle.puzzle_type) {
            this.pushStream("notice", `A puzzle has begun: ${data.active_puzzle.puzzle_type}`, { puzzle: true });
          }
          if (data.active_minigame && data.active_minigame.game_type) {
            this.pushStream("notice", `A minigame challenge: ${data.active_minigame.game_type}`, { minigame: true });
          }
          if (data.summary_update) {
            this.pushStream("summary", data.summary_update, data);
            if (this.campaignSummary) {
              this.campaignSummary += "\n" + data.summary_update;
            } else {
              this.campaignSummary = data.summary_update;
            }
          }
          if (data.state_update && data.state_update.game_time) {
            this.gameTime = data.state_update.game_time;
          }
        } else if (eventType === "error") {
          this.errorMessage = data.message || "Streaming error";
        }
      },

      async submitTurn() {
        this.resetError();
        if (!this.selectedCampaignId) {
          this.errorMessage = "Select a campaign first.";
          return;
        }
        if (!this.turnForm.actor_id || !this.turnForm.actor_id.trim()) {
          this.errorMessage = "Select an actor first.";
          return;
        }
        if (this.submitting) return;
        this.submitting = true;
        this._submittingTurn = true;
        this.statusMessage = "Submitting turn...";
        try {
          const payload = {
            actor_id: this.turnForm.actor_id.trim(),
            action: this.turnForm.action.trim(),
            session_id: this.selectedSessionId || null,
          };

          if (!this.runtimeInfo.streaming_supported) {
            /* Non-streaming fallback (original path) */
            const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/turns`, {
              method: "POST",
              body: JSON.stringify(payload),
            });
            normalizeTurnNotices(body).forEach((notice) => {
              this.pushStream("notice", notice, { notice });
            });
            if (typeof body.xp_awarded === "number" && body.xp_awarded > 0) {
              this.pushStream("notice", `+${body.xp_awarded} XP`, { xp: true });
            }
            const narration = normalizeTurnNarration(body);
            const narratorMeta = { ...body };
            if (body.state_update && body.state_update.game_time) {
              narratorMeta._game_time = body.state_update.game_time;
            }
            this.pushStream("narrator", narration, narratorMeta);
            if (body.reasoning) {
              this.pushStream("reasoning", body.reasoning, body);
            }
            if (body.image_prompt) {
              this.pushStream("image_prompt", body.image_prompt, body);
            }
            if (body.dice_result && body.dice_result.attribute) {
              const d = body.dice_result;
              const label = d.success ? "SUCCESS" : "FAIL";
              const text = `${d.attribute} check (DC ${d.dc}): rolled ${d.roll} + ${d.modifier} = ${d.total} — ${label}`;
              this.pushStream("dice", text, d);
            }
            if (body.active_puzzle && body.active_puzzle.puzzle_type) {
              this.pushStream("notice", `A puzzle has begun: ${body.active_puzzle.puzzle_type}`, { puzzle: true });
            }
            if (body.active_minigame && body.active_minigame.game_type) {
              this.pushStream("notice", `A minigame challenge: ${body.active_minigame.game_type}`, { minigame: true });
            }
            if (body.summary_update) {
              this.pushStream("summary", body.summary_update, body);
              if (this.campaignSummary) {
                this.campaignSummary += "\n" + body.summary_update;
              } else {
                this.campaignSummary = body.summary_update;
              }
            }
            this.turnForm.action = "";
            if (body.state_update && body.state_update.game_time) {
              this.gameTime = body.state_update.game_time;
            }
          } else {
            /* SSE streaming path */
            this._streamingNarration = "";
            this.turnCounter += 1;
            const streamEntryId = this.turnCounter;
            this.turnStream.push({
              id: streamEntryId,
              type: "narrator",
              at: nowLabel(),
              text: "",
              meta: {},
              _streaming: true,
            });
            this._scrollStream();

            const resp = await fetch(`/api/campaigns/${this.selectedCampaignId}/turns/stream`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            if (!resp.ok) {
              const errBody = await resp.text();
              throw new Error(errBody || `HTTP ${resp.status}`);
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let currentEvent = "";
            let currentData = "";

            while (true) {
              const { value, done } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop();  /* keep incomplete line in buffer */
              for (const line of lines) {
                if (line.startsWith("event: ")) {
                  currentEvent = line.slice(7).trim();
                } else if (line.startsWith("data: ")) {
                  currentData = line.slice(6);
                } else if (line === "") {
                  /* End of SSE event block */
                  if (currentEvent && currentData) {
                    try {
                      const parsed = JSON.parse(currentData);
                      this._handleStreamEvent(currentEvent, parsed, streamEntryId);
                    } catch (_e) {
                      /* ignore malformed JSON */
                    }
                  }
                  currentEvent = "";
                  currentData = "";
                }
              }
            }
            /* Flush any remaining event in buffer */
            if (currentEvent && currentData) {
              try {
                const parsed = JSON.parse(currentData);
                this._handleStreamEvent(currentEvent, parsed, streamEntryId);
              } catch (_e) { /* ignore */ }
            }

            this.turnForm.action = "";
          }

          await Promise.all([
            this.loadSessions(),
            this.loadMap(),
            this.loadTimers(),
            this.loadCalendar(),
            this.loadRoster(),
            this.loadPlayerState(),
            this.loadPlayerStatistics(),
            this.loadPlayerAttributes(),
            this.loadMedia(),
            this.loadDebugSnapshot(),
            this.loadRecentTurns(),
            this.loadStoryState(),
            this.loadSceneImages(),
          ]);
          this.statusMessage = "Turn submitted.";
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this._submittingTurn = false;
          this.submitting = false;
        }
      },

      async loadMap() {
        if (!this.selectedCampaignId) {
          return;
        }
        const actor = (this.turnForm.actor_id || "").trim();
        if (!actor) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/map?actor_id=${encodeURIComponent(actor)}`);
          this.mapText = body.map || "";
        } catch (_err) {
          /* background refresh — don't surface */
        }
      },

      async loadTimers() {
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/timers`);
          this.timersText = formatJson(body);
        } catch (_err) {
          /* background refresh */
        }
      },

      async cancelPendingTimer() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/timers/cancel`, {
            method: "POST",
          });
          if (result.ok) {
            this.pushStream("notice", `Timer cancelled: ${result.cancelled_event || 'unknown'}`, { timer: true });
            await this.loadTimers();
          } else {
            this.statusMessage = result.note || "No pending timer to cancel.";
          }
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async loadCalendar() {
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/calendar`);
          this.calendarText = formatJson(body);
          if (body.game_time && typeof body.game_time === "object") {
            this.gameTime = body.game_time;
          }
        } catch (_err) {
          /* background refresh */
        }
      },

      async loadRoster() {
        if (!this.selectedCampaignId) {
          return;
        }
        try {
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/roster`);
          this.rosterText = formatJson(body);
        } catch (_err) {
          /* background refresh */
        }
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
        let body;
        try {
          body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`);
        } catch (_err) {
          return;
        }
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
          this.playerData = null;
          this.playerStateText = formatJson({ detail: "Set actor id to inspect player state." });
          return;
        }
        try {
          const body = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/player-state?actor_id=${encodeURIComponent(actor.trim())}`,
          );
          this.playerData = body.player_state || body;
          this.playerStateText = formatJson(body);
        } catch (error) {
          this.playerData = null;
          this.playerStateText = formatJson({
            detail: "Player state unavailable for selected actor.",
            actor_id: actor.trim(),
            error: String(error),
          });
        }
      },

      async loadPlayerStatistics() {
        if (!this.selectedCampaignId) return;
        const actor = (this.turnForm.actor_id || "").trim();
        if (!actor) { this.playerStats = null; return; }
        try {
          this.playerStats = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/player-statistics?actor_id=${encodeURIComponent(actor)}`,
          );
        } catch (_) { this.playerStats = null; }
      },

      /* ---- Player attributes ---- */
      async loadPlayerAttributes() {
        if (!this.selectedCampaignId) return;
        const actor = (this.turnForm.actor_id || "").trim();
        if (!actor) { this.playerAttributes = null; return; }
        try {
          this.playerAttributes = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/player-attributes?actor_id=${encodeURIComponent(actor)}`,
          );
        } catch (_) { this.playerAttributes = null; }
      },

      async setPlayerAttribute() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const actor = (this.turnForm.actor_id || "").trim();
        const attr = (this.attributeForm.attribute || "").trim();
        const val = parseInt(this.attributeForm.value, 10);
        if (!actor || !attr || !Number.isFinite(val)) {
          this.errorMessage = "Actor, attribute name, and numeric value are required.";
          return;
        }
        try {
          await this.api(`/api/campaigns/${this.selectedCampaignId}/player-attributes`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actor, attribute: attr, value: val }),
          });
          this.attributeForm.attribute = "";
          this.attributeForm.value = 0;
          await this.loadPlayerAttributes();
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async levelUpPlayer() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const actor = (this.turnForm.actor_id || "").trim();
        if (!actor) {
          this.errorMessage = "Select an actor first.";
          return;
        }
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/level-up`, {
            method: "POST",
            body: JSON.stringify({ actor_id: actor }),
          });
          if (result.leveled_up) {
            this.pushStream("notice", `Level up! Now level ${result.new_level}.`, { xp: true });
          } else {
            this.statusMessage = result.reason || "Not enough XP to level up.";
          }
          await Promise.all([this.loadPlayerAttributes(), this.loadPlayerState(), this.loadPlayerStatistics()]);
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      /* ---- Recent turns (history) ---- */
      async loadRecentTurns(limit) {
        if (!this.selectedCampaignId) return;
        try {
          const lim = limit || 30;
          const data = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/recent-turns?limit=${lim}`,
          );
          this.recentTurns = Array.isArray(data.turns) ? data.turns : [];
        } catch (_) { this.recentTurns = []; }
      },

      /* ---- Campaign persona ---- */
      async loadCampaignPersona() {
        if (!this.selectedCampaignId) return;
        try {
          const data = await this.api(`/api/campaigns/${this.selectedCampaignId}/persona`);
          this.campaignPersona = data.persona || "";
          this.campaignPersonaSource = data.source || "default";
          this.personaEditText = this.campaignPersona;
        } catch (_) {
          this.campaignPersona = "";
          this.campaignPersonaSource = "";
          this.personaEditText = "";
        }
      },

      async setCampaignPersona() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const text = (this.personaEditText || "").trim();
        if (!text) {
          this.errorMessage = "Persona text is required.";
          return;
        }
        try {
          await this.api(`/api/campaigns/${this.selectedCampaignId}/persona`, {
            method: "POST",
            body: JSON.stringify({ persona: text }),
          });
          this.statusMessage = "Persona updated.";
          await this.loadCampaignPersona();
        } catch (error) {
          this.errorMessage = String(error);
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
            body: JSON.stringify({ thread: this.sms.thread.trim(), limit: Number(this.sms.limit || 20), viewer_actor_id: (this.turnForm.actor_id || "").trim() || null }),
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
          /* Extract campaign summary for display */
          if (typeof body.summary === "string" && body.summary.trim()) {
            this.campaignSummary = body.summary.trim();
          } else {
            this.campaignSummary = "";
          }
        } catch (_err) {
          this.campaignSummary = "";
          /* background refresh — don't surface */
        }
      },
    };
  };

  window.TextGameWebUI = {
    version: "0.3.0",
  };
})();
