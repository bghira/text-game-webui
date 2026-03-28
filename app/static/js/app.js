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

  function stripTrailingInventory(text) {
    return text.replace(/\n\s*\**Inventory\**:[\s\S]*$/i, "").trimEnd();
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttribute(text) {
    return escapeHtml(text).replace(/"/g, "&quot;");
  }

  function autolinkUrls(html) {
    return html.replace(
      /(^|[\s>(])((?:https?:\/\/|www\.)[^\s<]+)(?=$|[\s)<])/g,
      (_match, prefix, rawUrl) => {
        const href = rawUrl.startsWith("www.") ? `https://${rawUrl}` : rawUrl;
        return `${prefix}<a href="${escapeAttribute(href)}" target="_blank" rel="noopener noreferrer">${rawUrl}</a>`;
      }
    );
  }

  function renderInlineDiscordMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);
    const codeTokens = [];
    html = html.replace(/`([^`\n]+)`/g, (_match, code) => {
      const token = `@@CODE${codeTokens.length}@@`;
      codeTokens.push(`<code class="discord-inline-code">${code}</code>`);
      return token;
    });
    html = autolinkUrls(html);
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/~~(.+?)~~/g, "<s>$1</s>");
    html = html.replace(/\*(?!\s)([^*\n]+?)\*(?!\*)/g, "<em>$1</em>");
    html = html.replace(/(^|[\s(])_([^_\n]+?)_(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
    html = html.replace(/@@CODE(\d+)@@/g, (_match, idx) => codeTokens[Number(idx)] || "");
    return html;
  }

  function renderTextBlock(text) {
    const block = String(text || "").replace(/\r\n?/g, "\n").trim();
    if (!block) return "";
    const lines = block.split("\n");

    if (lines.every((line) => /^\s*>\s?/.test(line))) {
      const inner = lines.map((line) => line.replace(/^\s*>\s?/, "")).join("\n");
      return `<blockquote>${renderInlineDiscordMarkdown(inner).replace(/\n/g, "<br>")}</blockquote>`;
    }
    if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
      return `<ul>${lines.map((line) => `<li>${renderInlineDiscordMarkdown(line.replace(/^\s*[-*]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
      return `<ol>${lines.map((line) => `<li>${renderInlineDiscordMarkdown(line.replace(/^\s*\d+\.\s+/, ""))}</li>`).join("")}</ol>`;
    }
    if (/^\s*#{1,6}\s+/.test(lines[0])) {
      const level = Math.min(6, (lines[0].match(/^\s*(#{1,6})\s+/) || ["", "#"])[1].length);
      const headingText = lines[0].replace(/^\s*#{1,6}\s+/, "");
      const rest = lines.slice(1).join("\n").trim();
      const heading = `<div class="discord-heading discord-heading-${level}">${renderInlineDiscordMarkdown(headingText)}</div>`;
      return rest
        ? `${heading}<p>${renderInlineDiscordMarkdown(rest).replace(/\n/g, "<br>")}</p>`
        : heading;
    }
    return `<p>${renderInlineDiscordMarkdown(block).replace(/\n/g, "<br>")}</p>`;
  }

  function renderSimpleMarkdown(text) {
    if (!text) return "";
    const source = String(text || "").replace(/\r\n?/g, "\n");
    const parts = [];
    let cursor = 0;
    const fenceRe = /```([^\n`]*)\n?([\s\S]*?)```/g;
    let match;
    while ((match = fenceRe.exec(source)) !== null) {
      if (match.index > cursor) {
        parts.push({ type: "text", text: source.slice(cursor, match.index) });
      }
      parts.push({
        type: "code",
        lang: String(match[1] || "").trim(),
        text: String(match[2] || "").replace(/\n$/, ""),
      });
      cursor = match.index + match[0].length;
    }
    if (cursor < source.length) {
      parts.push({ type: "text", text: source.slice(cursor) });
    }
    if (!parts.length) {
      parts.push({ type: "text", text: source });
    }
    const rendered = parts.map((part) => {
      if (part.type === "code") {
        const label = part.lang
          ? `<span class="discord-code-label">${escapeHtml(part.lang)}</span>`
          : "";
        return (
          `<div class="discord-code-block">`
          + `<div class="discord-code-toolbar">${label}<button type="button" class="code-copy-btn">Copy</button></div>`
          + `<pre><code>${escapeHtml(part.text)}</code></pre>`
          + `</div>`
        );
      }
      return String(part.text || "")
        .split(/\n{2,}/)
        .map((chunk) => renderTextBlock(chunk))
        .filter(Boolean)
        .join("");
    }).join("");
    return `<div class="discord-md">${rendered}</div>`;
  }

  /**
   * Replace Discord-style timestamps (<t:EPOCH:R>, <t:EPOCH:F>, <t:EPOCH>)
   * with human-readable text.  :R → relative countdown, :F → full date,
   * bare → short date-time.
   */
  function renderDiscordTimestamps(text) {
    return text.replace(/<t:(\d+)(?::([a-zA-Z]))?>/g, (_match, epoch, style) => {
      const date = new Date(Number(epoch) * 1000);
      if (style === "R") {
        const diffMs = date.getTime() - Date.now();
        const absSec = Math.abs(Math.round(diffMs / 1000));
        const mins = Math.floor(absSec / 60);
        const secs = absSec % 60;
        const h = Math.floor(mins / 60);
        const m = mins % 60;
        let label = "";
        if (h > 0) label = `${h}h ${m}m`;
        else if (m > 0) label = `${m}m ${secs}s`;
        else label = `${secs}s`;
        return diffMs > 0 ? `in ${label}` : `${label} ago`;
      }
      if (style === "F") {
        return date.toLocaleString();
      }
      return date.toLocaleString();
    });
  }

  function formatSceneSpeakerName(raw) {
    const text = String(raw || "").trim();
    if (!text || text.toLowerCase() === "narrator") return "narrator";
    if (text.toLowerCase() === text && text.includes("-")) {
      const parts = text.split("-").filter(Boolean);
      if (parts.length) return parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
    }
    return text;
  }

  function renderSceneOutputHtml(sceneOutput, fallbackText) {
    if (!sceneOutput || !Array.isArray(sceneOutput.beats) || !sceneOutput.beats.length) {
      return renderSimpleMarkdown(fallbackText || "");
    }
    const parts = [];
    for (const beat of sceneOutput.beats) {
      if (!beat || typeof beat !== "object") continue;
      const text = String(beat.text || "").trim();
      if (!text) continue;
      const speaker = formatSceneSpeakerName(beat.speaker);
      const escapedText = renderSimpleMarkdown(text);
      parts.push(`<span class="speaker-label">${escapeHtml(speaker)}</span>${escapedText}`);
    }
    if (parts.length) return parts.join("<br><br>");
    return renderSimpleMarkdown(fallbackText || "");
  }

  function normalizeTurnNarration(payload) {
    if (payload.narration && payload.narration.trim().length > 0) {
      return renderDiscordTimestamps(stripTrailingInventory(payload.narration));
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
      sidebarOpen: false,
      modal: null,
      theme: document.documentElement.getAttribute("data-theme") || localStorage.getItem("theme") || "light",
      themes: [],
      toggleDebugMode() {
        this.debugMode = !this.debugMode;
        localStorage.setItem("debugMode", this.debugMode ? "true" : "false");
      },
      openModal(name) {
        this.modal = name;
      },
      closeModal() {
        this.modal = null;
      },
      async loadThemes() {
        try {
          const res = await fetch("/api/themes");
          if (res.ok) this.themes = await res.json();
        } catch (_) {}
      },
      _syncCustomCssLink(name) {
        const customLink = document.getElementById("custom-theme-css");
        if (!customLink) return;
        const builtins = ["light", "dark"];
        if (!builtins.includes(name)) {
          customLink.href = "/api/themes/" + encodeURIComponent(name) + "/theme.css";
          customLink.disabled = false;
        } else {
          customLink.href = "";
          customLink.disabled = true;
        }
      },
      applyTheme(name) {
        this.theme = name;
        localStorage.setItem("theme", name);
        document.documentElement.setAttribute("data-theme", name);
        this._syncCustomCssLink(name);
        // Persist to server
        fetch("/api/settings/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme: name }),
        }).catch(function() {});
      },
    });
    // Sync custom CSS link and load theme list on init
    Alpine.store("app")._syncCustomCssLink(Alpine.store("app").theme);
    Alpine.store("app").loadThemes();
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
      _phaseTyper: null,
      imageGenerating: 0,
      _realtimeRefreshTimer: null,

      /* Unseen activity tracking */
      sessionLastSeen: {},
      _unseenPollTimer: null,

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
        namespace: "all",
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
      _turnQueues: {},
      _turnQueueDraining: false,
      dtmLink: {
        enabled: false,
        linked: false,
        actor_id: "",
        display_name: "",
        link_code: "",
        command: "",
        error: "",
      },
      _dtmLinkPollId: null,
      _initializedAfterLink: false,
      memory: {
        search: "",
        category: "",
        searchWithinTurnIds: "",
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
        clock_start_day_of_week: "monday",
        clock_type: "consequential-calendar",
      },

      /* Song player */
      songQueue: [],
      songIndex: -1,

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
      /* Chapter list for sidebar */
      chapterList: null,
      chaptersPanelOpen: true,
      rewindTargetTurn: "",
      rewindStatus: "",
      collapsedTurnIds: {},
      editingTurnKey: "",
      editingTurnDraft: "",
      turnMutationBusy: false,

      /* Player attributes */
      playerAttributes: null,
      attributeForm: { attribute: "", value: 0 },
      characterNameForm: { value: "" },
      characterNameSaving: false,
      characterNameStatus: "",

      /* Turn history */
      recentTurns: [],
      _turnStreamOffset: 0,
      _turnStreamHasMore: false,
      _turnStreamLoadingOlder: false,

      /* Campaign persona */
      campaignPersona: "",
      campaignPersonaSource: "",
      personaEditText: "",

      /* Campaign config modal sub-tab */
      campaignConfigTab: "general",

      /* New campaign wizard state */
      newCampaignWizard: {
        step: "info",
        name: "",
        actor_id: "",
        files: [],
        on_rails: false,
        createStatus: "",
        campaignId: null,
        setupPhase: null,
        setupResponse: "",
        setupMessages: [],
        setupMessage: "",
        setupSending: false,
        setupAttachmentText: "",
      },

      /* Game time (extracted from turn state_update) */
      gameTime: {},
      calendarEvents: [],
      calendarPanelOpen: true,
      campaignSummary: "",

      async init() {
        const ready = await this.refreshDtmLinkStatus();
        if (!ready) return;
        if (this._initializedAfterLink) return;
        this._initializedAfterLink = true;
        await this.loadRuntime();
        await this.refreshCampaigns();
        await this.loadSettingsForm();
        await this.loadImageSettingsForm();
        await this.loadOllamaModels();
        /* watch debug toggle to guard inspector tab */
        this.$watch("$store.app.debugMode", () => this.ensureValidInspectorTab());
        /* reset wizard when opening new campaign modal */
        this.$watch("$store.app.modal", (val) => {
          if (val === "newCampaign") this.resetNewCampaignWizard();
        });

        // Restore unseen-activity timestamps
        try {
          const raw = localStorage.getItem("sessionLastSeen");
          if (raw) {
            const parsed = JSON.parse(raw);
            this.sessionLastSeen = (parsed && typeof parsed === "object" && !Array.isArray(parsed))
              ? parsed : {};
          }
        } catch (_) { this.sessionLastSeen = {}; }

        // Restore persisted campaign selection
        // Read both before selectCampaign — it clears selectedSessionId from localStorage
        const savedCampaignId = localStorage.getItem("selectedCampaignId");
        const savedSessionId = localStorage.getItem("selectedSessionId");
        if (savedCampaignId && this.campaigns.some(c => c.id === savedCampaignId)) {
          /* Pass savedSessionId so selectCampaign keeps it through loadSessions
             instead of clearing it and trying to auto-pick. */
          await this.selectCampaign(savedCampaignId, savedSessionId || undefined);
          /* selectSession wires the socket, highlights the button, and persists.
             Always call it when a session is selected — this is the single place
             that connects the socket during restore (loadSessions skips it). */
          if (this.selectedSessionId) {
            this.selectSession(this.selectedSessionId);
          } else {
            /* savedSessionId was stale or missing; loadSessions auto-picked but
               skipped connectSocket, so we need to connect now. */
            this.connectSocket();
          }
        }

        /* Infinite scroll: load older turns when scrolled near top */
        this.$nextTick(() => {
          const stream = document.getElementById("turn-stream");
          if (stream) {
            stream.addEventListener("scroll", () => {
              if (stream.scrollTop < 80 && this._turnStreamHasMore && !this._turnStreamLoadingOlder) {
                this.loadOlderTurns();
              }
            });
          }
        });

        if (!this.statusMessage.startsWith("Runtime backend:")) {
          this.statusMessage = "Initialized.";
        }
      },

      async refreshDtmLinkStatus() {
        try {
          const body = await this.api("/api/dtm-link/status");
          this.dtmLink.enabled = !!body.enabled;
          this.dtmLink.linked = !!body.linked;
          this.dtmLink.actor_id = body.actor_id || "";
          this.dtmLink.display_name = body.display_name || "";
          this.dtmLink.link_code = body.link_code || "";
          this.dtmLink.command = body.command || "";
          this.dtmLink.error = "";
          if (this.dtmLink.enabled && !this.dtmLink.linked) {
            this.startDtmLinkPolling();
            return false;
          }
          this.stopDtmLinkPolling();
          if (this.dtmLink.linked && this.dtmLink.actor_id) {
            this.applyLinkedActor(this.dtmLink.actor_id);
          }
          return true;
        } catch (error) {
          this.dtmLink.error = String(error);
          return !this.dtmLink.enabled;
        }
      },

      startDtmLinkPolling() {
        if (this._dtmLinkPollId) return;
        this._dtmLinkPollId = setInterval(async () => {
          const ready = await this.refreshDtmLinkStatus();
          if (ready) {
            this.stopDtmLinkPolling();
            await this.init();
          }
        }, 3000);
      },

      stopDtmLinkPolling() {
        if (!this._dtmLinkPollId) return;
        clearInterval(this._dtmLinkPollId);
        this._dtmLinkPollId = null;
      },

      applyLinkedActor(actorId) {
        const actor = (actorId || "").trim();
        if (!actor) return;
        this.campaignForm.actor_id = actor;
        this.turnForm.actor_id = actor;
        this.mediaActions.actor_id = actor;
        this.newCampaignWizard.actor_id = actor;
      },

      effectiveLinkedActorId() {
        if (!this.dtmLink || !this.dtmLink.enabled || !this.dtmLink.linked) {
          return "";
        }
        return String(this.dtmLink.actor_id || "").trim();
      },

      /* ---- Turn stream hydration from history ---- */
      _buildTurnEntries(turns, sessionFilter) {
        const entries = [];
        let counter = 0;
        let lastGameTime = null;
        for (const turn of turns) {
          if (sessionFilter && turn.session_id && turn.session_id !== sessionFilter) continue;
          if (turn.kind === "narrator" || turn.kind === "player") {
            counter++;
            const meta = turn.meta || {};
            const entry = {
              id: counter,
              type: turn.kind === "player" ? "player" : "narrator",
              at: turn.created_at ? new Date(turn.created_at).toLocaleTimeString() : "",
              text: renderDiscordTimestamps(stripTrailingInventory(turn.content || "[No content]")),
              meta: {
                actor_id: turn.actor_id || "",
                actor_name: turn.actor_name || "",
              },
              _backendTurnId: turn.id || null,
            };
            if (meta.game_time) {
              entry.meta._game_time = meta.game_time;
              lastGameTime = meta.game_time;
            }
            if (meta.scene_output && Array.isArray(meta.scene_output.beats)) {
              entry.meta.scene_output = meta.scene_output;
            }
            entries.push(entry);
          }
        }
        return { entries, counter, lastGameTime };
      },

      populateTurnStreamFromHistory(scrollToBottom) {
        if (!this.recentTurns || this.recentTurns.length === 0) return;
        const sessionId = this.selectedSessionId;
        let result = this._buildTurnEntries(this.recentTurns, sessionId);
        /* If session filter produced zero entries but we have turns, show
           all turns rather than a blank stream. */
        if (result.entries.length === 0 && sessionId) {
          result = this._buildTurnEntries(this.recentTurns, null);
        }
        this.turnCounter = result.counter;
        this.turnStream = result.entries;
        /* Apply turn-derived game time only when we don't already have
           authoritative data (e.g. from loadCalendar). */
        if (result.lastGameTime) {
          if (!this.gameTime || !this.gameTime.day) {
            this.gameTime = result.lastGameTime;
          }
        }
        if (scrollToBottom !== false) this._scrollStream();
      },

      _recentTurnsContainTurnId(turnId) {
        const wanted = Number(turnId) || 0;
        if (wanted <= 0 || !Array.isArray(this.recentTurns)) {
          return false;
        }
        return this.recentTurns.some((turn) => Number(turn && turn.id) === wanted);
      },

      _scheduleRecentTurnRecovery(turnId) {
        const wanted = Number(turnId) || 0;
        if (wanted <= 0 || !this.selectedCampaignId) {
          return;
        }
        setTimeout(async () => {
          try {
            await this.loadRecentTurns(30);
            if (this._recentTurnsContainTurnId(wanted)) {
              this.populateTurnStreamFromHistory();
            }
          } catch (_error) {
          }
        }, 1000);
      },

      /* ---- Turn stream filtering ---- */
      visibleTurnStream() {
        if (this.$store.app.debugMode) {
          return this.turnStream;
        }
        return this.turnStream.filter(
          (entry) => entry.type === "narrator" || entry.type === "player" || entry.type === "notice" || entry.type === "image_prompt" || entry.type === "dice"
        );
      },

      entryTurnKey(entry) {
        if (!entry || typeof entry !== "object") return "";
        const backend = Number(entry._backendTurnId) || 0;
        if (backend > 0) return `turn:${backend}`;
        return `entry:${entry.id || ""}`;
      },

      turnIsCollapsed(entry) {
        const key = this.entryTurnKey(entry);
        return !!(key && this.collapsedTurnIds[key]);
      },

      toggleTurnCollapsed(entry) {
        const key = this.entryTurnKey(entry);
        if (!key) return;
        this.collapsedTurnIds = {
          ...this.collapsedTurnIds,
          [key]: !this.collapsedTurnIds[key],
        };
      },

      turnIsEditing(entry) {
        return this.editingTurnKey && this.editingTurnKey === this.entryTurnKey(entry);
      },

      startTurnEdit(entry) {
        if (!entry || !entry._backendTurnId) return;
        this.editingTurnKey = this.entryTurnKey(entry);
        this.editingTurnDraft = String(entry.text || "");
      },

      cancelTurnEdit() {
        this.editingTurnKey = "";
        this.editingTurnDraft = "";
      },

      async copyToClipboard(text, successMessage) {
        const value = String(text || "");
        if (!value) return;
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
          await navigator.clipboard.writeText(value);
        } else {
          const area = document.createElement("textarea");
          area.value = value;
          area.setAttribute("readonly", "readonly");
          area.style.position = "absolute";
          area.style.left = "-9999px";
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          document.body.removeChild(area);
        }
        this.statusMessage = successMessage || "Copied.";
      },

      async copyTurnText(entry) {
        try {
          await this.copyToClipboard(entry && entry.text ? entry.text : "", "Turn text copied.");
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      handleTurnStreamClick(event) {
        const button = event && event.target && typeof event.target.closest === "function"
          ? event.target.closest(".code-copy-btn")
          : null;
        if (!button) return;
        const code = button.closest(".discord-code-block")?.querySelector("code");
        if (!code) return;
        event.preventDefault();
        this.copyToClipboard(code.textContent || "", "Code block copied.").catch((error) => {
          this.errorMessage = String(error);
        });
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
        /* Capture the model before the dropdown re-renders to guard against
           the <select> syncing an empty value back into settingsForm.model. */
        const savedModel = (this.settingsForm.model || "").trim();
        try {
          const data = await this.api("/api/ollama/models");
          if (data.reachable && Array.isArray(data.models)) {
            this.ollamaModels = data.models;
            /* ensure current model appears in the list so the dropdown doesn't reset */
            const currentModel = savedModel || (this.settingsForm.model || "").trim();
            if (currentModel && !this.ollamaModels.some((m) => m.name === currentModel)) {
              this.ollamaModels.unshift({ name: currentModel, size: null, modified_at: null });
            }
            /* Restore model in case the select element reset it */
            if (savedModel) this.settingsForm.model = savedModel;
          } else {
            this.ollamaModels = [];
          }
        } catch (_err) {
          this.ollamaModels = [];
        }
        /* Final guard: restore model if it was blanked during re-render */
        if (savedModel && !this.settingsForm.model) {
          this.settingsForm.model = savedModel;
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
        if (this.submitting) {
          this.statusMessage = "Wait for the current turn to finish before generating images.";
          return;
        }
        entry._imgGenerating = true;
        entry._imgError = "";
        entry._imgUrl = "";
        this.imageGenerating++;
        try {
          const result = await this.api("/api/image/generate", {
            method: "POST",
            body: JSON.stringify({ prompt: entry.text }),
          });
          const jobId = result.job_id;
          if (!jobId) {
            entry._imgError = result.detail || "No job ID returned.";
            entry._imgGenerating = false;
            this.imageGenerating = Math.max(0, this.imageGenerating - 1);
            return;
          }
          // Poll for completion
          for (let i = 0; i < 120; i++) {
            await new Promise((r) => setTimeout(r, 2000));
            const status = await this.api(`/api/image/status/${encodeURIComponent(jobId)}`);
            if (status.status === "completed") {
              entry._imgUrl = status.image_url || "";
              entry._imgGenerating = false;
              this.imageGenerating = Math.max(0, this.imageGenerating - 1);
              return;
            }
            if (status.status === "failed" || status.status === "interrupted") {
              entry._imgError = status.error || status.status;
              entry._imgGenerating = false;
              this.imageGenerating = Math.max(0, this.imageGenerating - 1);
              return;
            }
          }
          entry._imgError = "Generation timed out.";
        } catch (err) {
          entry._imgError = String(err);
        }
        entry._imgGenerating = false;
        this.imageGenerating = Math.max(0, this.imageGenerating - 1);
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
        const label = this.sessionDisplayLabel(row);
        const scope = metadata.scope || metadata.turn_visibility_default || row.surface;
        return `${label} (${scope})`;
      },

      sessionDisplayLabel(row) {
        if (!row || typeof row !== "object") {
          return "";
        }
        const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
        const label = String(metadata.label || "").trim();
        if (label) {
          return label;
        }
        const surface = String(row.surface || "").trim().toLowerCase();
        const surfaceKey = String(row.surface_key || "").trim();
        if (surface === "discord" || surfaceKey.startsWith("discord:")) {
          return "Discord room";
        }
        return surfaceKey || String(row.id || "").trim();
      },

      turnQueueKey(campaignId, actorId) {
        const campaign = String(campaignId || "").trim();
        const actor = String(actorId || "").trim();
        if (!campaign || !actor) return "";
        return `${campaign}::${actor}`;
      },

      currentTurnQueueKey() {
        return this.turnQueueKey(this.selectedCampaignId, this.turnForm.actor_id);
      },

      currentQueuedTurnCount() {
        const key = this.currentTurnQueueKey();
        if (!key) return 0;
        return Array.isArray(this._turnQueues[key]) ? this._turnQueues[key].length : 0;
      },

      submitButtonLabel() {
        if (this.imageGenerating > 0) return "Generating...";
        if (this.submitting) {
          const queued = this.currentQueuedTurnCount();
          return queued > 0 ? `Queue (${queued})` : "Queue";
        }
        return "Submit";
      },

      _enqueueTurnPayload(campaignId, payload) {
        const key = this.turnQueueKey(campaignId, payload.actor_id);
        if (!key) return;
        if (!Array.isArray(this._turnQueues[key])) {
          this._turnQueues[key] = [];
        }
        this._turnQueues[key].push({
          actor_id: String(payload.actor_id || "").trim(),
          action: String(payload.action || "").trim(),
          session_id: payload.session_id || null,
        });
        this.turnForm.action = "";
        const count = this._turnQueues[key].length;
        this.statusMessage = count === 1 ? "Queued 1 action." : `Queued ${count} actions.`;
      },

      _isQueueRetryableTurnError(error) {
        const text = String(error || "").toLowerCase();
        return (
          text.includes("already resolving")
          || text.includes("timed event in progress")
          || text.includes("waiting for it to finish")
        );
      },

      async _drainQueuedTurns() {
        if (this._turnQueueDraining || this.submitting) return;
        const key = this.currentTurnQueueKey();
        if (!key) return;
        this._turnQueueDraining = true;
        try {
          while (!this.submitting) {
            const queue = this._turnQueues[key];
            if (!Array.isArray(queue) || queue.length === 0) {
              delete this._turnQueues[key];
              break;
            }
            const next = queue.shift();
            if (!queue.length) {
              delete this._turnQueues[key];
            }
            if (!next || !String(next.action || "").trim()) {
              continue;
            }
            const result = await this._submitTurnPayload(this.selectedCampaignId, next, { queued: true });
            if (!result.ok) {
              if (this._isQueueRetryableTurnError(result.error)) {
                if (!Array.isArray(this._turnQueues[key])) {
                  this._turnQueues[key] = [];
                }
                this._turnQueues[key].unshift(next);
                this.statusMessage = "Queued action is waiting for the current turn to clear.";
                await new Promise((resolve) => setTimeout(resolve, 500));
                continue;
              }
              this.errorMessage = String(result.error);
            }
          }
        } finally {
          this._turnQueueDraining = false;
        }
      },

      sidebarCalendarEvents() {
        const rows = Array.isArray(this.calendarEvents) ? [...this.calendarEvents] : [];
        rows.sort((a, b) => {
          const dayA = Number(a && a.fire_day) || 0;
          const dayB = Number(b && b.fire_day) || 0;
          if (dayA !== dayB) return dayA - dayB;
          const hourA = Number(a && a.fire_hour) || 0;
          const hourB = Number(b && b.fire_hour) || 0;
          return hourA - hourB;
        });
        return rows.slice(0, 8);
      },

      calendarSidebarTimeLabel(event) {
        if (!event || typeof event !== "object") return "";
        const hour = String(Number(event.fire_hour) || 0).padStart(2, "0");
        const minute = String(Number(event.fire_minute) || 0).padStart(2, "0");
        const day = Number(event.fire_day) || 0;
        const status = String(event.status || "").trim().toLowerCase();
        if (status === "today") return `Today ${hour}:${minute}`;
        if (status === "imminent") return `Soon ${hour}:${minute}`;
        if (status === "missed") return `Missed Day ${day} ${hour}:${minute}`;
        if (day > 0) return `Day ${day} ${hour}:${minute}`;
        return `${hour}:${minute}`;
      },

      syncTurnSessionSelection() {
        this.turnForm.session_id = this.selectedSessionId || "";
      },

      selectSession(sessionId) {
        this.$store.app.sidebarOpen = false;
        this.selectedSessionId = sessionId || "";
        if (this.selectedSessionId) {
          localStorage.setItem("selectedSessionId", this.selectedSessionId);
          this.sessionLastSeen[this.selectedSessionId] = isoNow();
          this._persistSessionLastSeen();
        } else {
          localStorage.removeItem("selectedSessionId");
        }
        this.syncTurnSessionSelection();
        this.turnStream = [];
        this.connectSocket();
        this.populateTurnStreamFromHistory();
        /* Refresh authoritative game time — turn metadata may be incomplete */
        this.loadCalendar();
        const row = this.currentSessionRecord();
        if (row) {
          this.statusMessage = `Selected window ${this.sessionDisplayLabel(row)}.`;
        }
      },

      _persistSessionLastSeen() {
        try { localStorage.setItem("sessionLastSeen", JSON.stringify(this.sessionLastSeen)); }
        catch (_) {}
      },

      sessionHasUnseen(sessionId) {
        if (!sessionId || sessionId === this.selectedSessionId) return false;
        const lastSeen = this.sessionLastSeen[sessionId];
        const lastSeenMs = lastSeen ? Date.parse(lastSeen) : undefined;
        const selectedSessionId = String(this.selectedSessionId || "").trim();
        for (const turn of this.recentTurns) {
          if (turn.session_id !== sessionId || !turn.created_at) continue;
          const meta = turn && turn.meta && typeof turn.meta === "object" ? turn.meta : {};
          const visibility = meta.visibility && typeof meta.visibility === "object"
            ? meta.visibility
            : (meta.turn_visibility && typeof meta.turn_visibility === "object" ? meta.turn_visibility : {});
          const scope = String(visibility.scope || "").trim().toLowerCase();
          if (selectedSessionId && (scope === "public" || scope === "local")) {
            continue;
          }
          // Never visited — any turn means unseen
          if (lastSeenMs === undefined) return true;
          if (Date.parse(turn.created_at) > lastSeenMs) return true;
        }
        return false;
      },

      _startUnseenPoll() {
        this._stopUnseenPoll();
        if (!this.selectedCampaignId) return;
        this._unseenPollTimer = setInterval(() => {
          if (this.sessionsList.length > 1) this.loadRecentTurns();
        }, 15000);
      },

      _stopUnseenPoll() {
        if (this._unseenPollTimer) {
          clearInterval(this._unseenPollTimer);
          this._unseenPollTimer = null;
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
          this.campaignFlags.clock_start_day_of_week = data.clock_start_day_of_week || "monday";
          this.campaignFlags.clock_type = data.clock_type || "consequential-calendar";
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

      /* ---- Song player ---- */
      _pushSong(song) {
        // Avoid duplicates of the same video back-to-back
        const last = this.songQueue.length > 0 ? this.songQueue[this.songQueue.length - 1] : null;
        if (last && last.video_id === song.video_id) return;
        this.songQueue.push(song);
        // Auto-advance to the new song
        this.songIndex = this.songQueue.length - 1;
      },

      get currentSong() {
        if (this.songIndex < 0 || this.songIndex >= this.songQueue.length) return null;
        return this.songQueue[this.songIndex];
      },

      songPrev() {
        if (this.songIndex > 0) this.songIndex--;
      },

      songNext() {
        if (this.songIndex < this.songQueue.length - 1) this.songIndex++;
      },

      get songEmbedUrl() {
        const song = this.currentSong;
        if (!song || !song.video_id) return "";
        return `https://www.youtube.com/embed/${song.video_id}?autoplay=1&rel=0`;
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
            await this._reloadCampaignData();
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
        if (this.submitting) {
          this.avatarGenStatus = "Wait for the current turn to finish.";
          return;
        }
        const actorId = this.resolveMediaActorId();
        this.avatarGenBusy = true;
        this.imageGenerating++;
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
            this.imageGenerating = Math.max(0, this.imageGenerating - 1);
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
              this.imageGenerating = Math.max(0, this.imageGenerating - 1);
              return;
            }
          }
          if (!imageUrl) {
            this.avatarGenStatus = "Generation timed out.";
            this.avatarGenBusy = false;
            this.imageGenerating = Math.max(0, this.imageGenerating - 1);
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
        this.imageGenerating = Math.max(0, this.imageGenerating - 1);
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
          await Promise.all([this.loadStoryState(), this.loadChapterList()]);
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
          await Promise.all([this.loadStoryState(), this.loadChapterList()]);
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

      /* ---- Chapter list (sidebar) ---- */
      async loadChapterList() {
        if (!this.selectedCampaignId) return;
        try {
          this.chapterList = await this.api(`/api/campaigns/${this.selectedCampaignId}/chapters`);
        } catch (_) { this.chapterList = null; }
      },

      /* ---- Rewind ---- */
      async rewindToTurnId(turnId) {
        this.resetError();
        this.rewindStatus = "";
        if (!this.selectedCampaignId) {
          this.errorMessage = "Select a campaign first.";
          return;
        }
        if (!Number.isFinite(turnId) || turnId <= 0) {
          this.errorMessage = "Enter a valid turn ID (positive integer).";
          return;
        }
        if (!confirm(`Rewind to turn ${turnId}? This is destructive and cannot be undone.`)) return;
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
          this._resetPagination();
          /* Reload all state after rewind */
          await Promise.all([
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
            this.loadChapterList(),
            this.loadSceneImages(),
          ]);
          /* Rebuild visible turn stream from the now-shorter history.
             Clear first so rewind-to-zero doesn't leave stale entries. */
          this.turnStream = [];
          this.turnCounter = 0;
          this.populateTurnStreamFromHistory();
          this.pushStream("notice", `Rewound to turn ${turnId}`, { rewind: true });
        } catch (error) {
          this.errorMessage = String(error);
        }
      },

      async rewindToTurn() {
        const turnId = parseInt(this.rewindTargetTurn, 10);
        await this.rewindToTurnId(turnId);
      },

      async saveTurnEdit(entry) {
        this.resetError();
        const turnId = Number(entry && entry._backendTurnId) || 0;
        const text = String(this.editingTurnDraft || "").trim();
        if (!this.selectedCampaignId || turnId <= 0) return;
        if (!text) {
          this.errorMessage = "Turn text cannot be empty.";
          return;
        }
        this.turnMutationBusy = true;
        try {
          await this.api(`/api/campaigns/${this.selectedCampaignId}/turns/${turnId}`, {
            method: "PATCH",
            body: JSON.stringify({ content: text }),
          });
          this.cancelTurnEdit();
          this._resetPagination();
          await this.loadRecentTurns(30);
          this.populateTurnStreamFromHistory();
          this.statusMessage = `Updated turn ${turnId}.`;
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this.turnMutationBusy = false;
        }
      },

      async deleteTurnEntry(entry) {
        this.resetError();
        const turnId = Number(entry && entry._backendTurnId) || 0;
        if (!this.selectedCampaignId || turnId <= 0) return;
        if (!confirm(`Delete turn ${turnId} from the database? This removes only this turn.`)) return;
        this.turnMutationBusy = true;
        try {
          await this.api(`/api/campaigns/${this.selectedCampaignId}/turns/${turnId}`, {
            method: "DELETE",
          });
          this.cancelTurnEdit();
          this._resetPagination();
          await this.loadRecentTurns(30);
          this.populateTurnStreamFromHistory();
          this.statusMessage = `Deleted turn ${turnId}.`;
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          this.turnMutationBusy = false;
        }
      },

      async refreshCampaigns() {
        this.resetError();
        try {
          const namespace = encodeURIComponent(this.campaignForm.namespace || "all");
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
          const createNamespace = (["", "*", "all"].includes((this.campaignForm.namespace || "").trim().toLowerCase()))
            ? "default"
            : (this.campaignForm.namespace || "default");
          // 1. Create campaign
          const body = await this.api("/api/campaigns", {
            method: "POST",
            body: JSON.stringify({
              namespace: createNamespace,
              name: this.campaignForm.name.trim(),
              actor_id: this.campaignForm.actor_id.trim(),
            }),
          });
          const campaign = body.campaign;
          await this.refreshCampaigns();
          await this.selectCampaign(campaign.id);

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

      async selectCampaign(campaignId, restoreSessionId) {
        this.$store.app.sidebarOpen = false;
        this.resetError();
        this.selectedCampaignId = campaignId;
        localStorage.setItem("selectedCampaignId", campaignId);
        this.selectedSessionId = restoreSessionId || "";
        if (!restoreSessionId) localStorage.removeItem("selectedSessionId");
        this.turnStream = [];
        this._resetPagination();
        /* Reset unseen-activity tracking for previous campaign */
        this.sessionLastSeen = {};
        this._persistSessionLastSeen();
        this._stopUnseenPoll();
        /* Reset per-campaign derived state to prevent stale values */
        this.gameTime = {};
        this.campaignSummary = "";
        this.storyState = null;
        this.chapterList = null;
        this.playerData = null;
        this.playerStats = null;
        this.playerAttributes = null;
        this.recentTurns = [];
        this.songQueue = [];
        this.songIndex = -1;
        this.campaignPersona = "";
        this.campaignPersonaSource = "";
        this.personaEditText = "";
        this.minigameBoard = "";
        this.minigameStatus = "";
        this.puzzleStatus = "";
        this.mapText = "";
        this.timersText = "";
        this.calendarText = "";
        this.calendarEvents = [];
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
        const linkedActorId = this.effectiveLinkedActorId();
        if (linkedActorId) {
          this.turnForm.actor_id = linkedActorId;
        } else if (selected) {
          this.turnForm.actor_id = selected.actor_id;
        }
        if (this.turnForm.actor_id) {
          this.mediaActions.actor_id = this.turnForm.actor_id;
          this.rosterActions.slug = this.turnForm.actor_id;
          this.rosterActions.player = true;
        }
        /* Load session + turn data first so the stream renders immediately,
           then load remaining panels in the background. */
        /* When restoring a session from init(), skip the socket connect in
           loadSessions — selectSession() in init() will own the single connect. */
        await Promise.all([
          this.loadSessions(restoreSessionId ? { skipConnect: true } : undefined),
          this.loadRecentTurns(),
        ]);
        if (!this.sessionsList.some((row) => row && row.surface === "web_shared")) {
          await this.ensureSharedWindow({
            select: !this.selectedSessionId,
            silent: true,
          });
        }
        this.populateTurnStreamFromHistory();
        /* Remaining data loads — fire-and-forget so the UI stays responsive. */
        Promise.all([
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
          this.loadCampaignPersona(),
          this.checkSetupMode(),
          this.loadSceneImages(),
          this.loadLiteraryStyles(),
          this.loadStoryState(),
          this.loadChapterList(),
        ]).catch(() => {});
        this.populateTurnStreamFromHistory();
        this._startUnseenPoll();
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
            this.loadChapterList();
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
          if (payload.type === "turn_refresh") {
            this._scheduleRealtimeTurnRefresh();
          }
          if (payload.type === "roster" && payload.payload) {
            this.pushStream("roster", formatJson(payload.payload));
            this.rosterText = formatJson(payload.payload);
          }
          if (payload.type === "timed_event" && payload.payload) {
            const narration = payload.payload.narration || "";
            if (narration) {
              this.pushStream("narrator", renderDiscordTimestamps(stripTrailingInventory(narration)), { timed_event: true });
            }
            this.loadTimers();
            this.loadRecentTurns();
          }
          if (payload.type === "dm_notification" && payload.payload) {
            const msg = payload.payload.message || "";
            if (msg) {
              this.pushStream("notice", msg, { dm_notification: true });
            }
            if (payload.payload.refresh_sms_threads) {
              this.listSmsThreads();
            }
          }
          if (payload.type === "channel_notification" && payload.payload) {
            const msg = payload.payload.message || "";
            if (msg) {
              this.pushStream("notice", msg, { channel_notification: true });
            }
          }
          if (payload.type === "song_notification" && payload.payload) {
            this._pushSong(payload.payload);
          }
          if (payload.type === "turn_progress" && payload.payload && this.submitting) {
            const label = this._turnProgressLabel(payload.payload.phase, payload.payload);
            this.statusMessage = label;
            const streamEntry = this.turnStream.find((e) => e._streaming);
            if (streamEntry) {
              this._typePhase(streamEntry.id, label);
            }
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

      _typePhase(entryId, label) {
        if (this._phaseTyper && this._phaseTyper.timerId) {
          clearInterval(this._phaseTyper.timerId);
        }
        this._phaseTyper = { text: label, index: 0, timerId: null, entryId };
        const entry = this.turnStream.find((e) => e.id === entryId);
        if (entry) {
          entry.text = "";
          entry._phaseText = true;
        }
        this._phaseTyper.timerId = setInterval(() => {
          this._phaseTyper.index++;
          const entry = this.turnStream.find((e) => e.id === this._phaseTyper.entryId);
          if (entry) entry.text = this._phaseTyper.text.slice(0, this._phaseTyper.index);
          this._scrollStream();
          if (this._phaseTyper.index >= this._phaseTyper.text.length) {
            clearInterval(this._phaseTyper.timerId);
            this._phaseTyper.timerId = null;
          }
        }, 30);
      },

      _clearPhaseTyper() {
        if (this._phaseTyper && this._phaseTyper.timerId) {
          clearInterval(this._phaseTyper.timerId);
        }
        this._phaseTyper = null;
      },

      _scheduleRealtimeTurnRefresh() {
        if (this._realtimeRefreshTimer) {
          clearTimeout(this._realtimeRefreshTimer);
        }
        this._realtimeRefreshTimer = setTimeout(async () => {
          this._realtimeRefreshTimer = null;
          try {
            await Promise.all([
              this.loadRecentTurns(),
              this.loadTimers(),
              this.loadStoryState(),
              this.loadChapterList(),
              this.loadCalendar(),
            ]);
            this.populateTurnStreamFromHistory();
          } catch (_err) {
          }
        }, 150);
      },

      _turnProgressLabel(phase, detail) {
        const labels = {
          starting: "Starting turn...",
          thinking: "Thinking...",
          generating: "Generating...",
          writing: "Writing response...",
          narrating: "Streaming narration...",
          refining: "Refining response...",
        };
        if (phase === "tool_call" && detail && detail.tool) {
          const toolLabels = {
            memory_search: "Searching memories...",
            memory_terms: "Browsing memory index...",
            memory_turn: "Recalling turn details...",
            memory_store: "Storing memory...",
            source_browse: "Browsing sources...",
            sms_list: "Checking messages...",
            sms_read: "Reading messages...",
            sms_write: "Sending message...",
            sms_schedule: "Scheduling message...",
            story_outline: "Reviewing story outline...",
            plot_plan: "Planning plot...",
            chapter_plan: "Planning chapter...",
            consequence_log: "Logging consequences...",
            recent_turns: "Reviewing recent turns...",
            autobiography_append: "Updating character bio...",
            autobiography_update: "Updating character bio...",
            autobiography_compress: "Compressing character bio...",
            name_generate: "Generating names...",
            communication_rules: "Checking communication rules...",
          };
          return toolLabels[detail.tool] || `Using ${detail.tool.replace(/_/g, " ")}...`;
        }
        return labels[phase] || (phase.charAt(0).toUpperCase() + phase.slice(1).replace(/_/g, " ") + "...");
      },

      _handleStreamEvent(eventType, data, streamEntryId) {
        if (eventType === "phase") {
          const label = this._turnProgressLabel(data.phase, data);
          this.statusMessage = label;
          if (streamEntryId && data.phase !== "narrating") {
            this._typePhase(streamEntryId, label);
          } else if (data.phase === "narrating") {
            this._clearPhaseTyper();
            const entry = this.turnStream.find((e) => e.id === streamEntryId);
            if (entry) { entry.text = ""; entry._phaseText = false; }
          }
        } else if (eventType === "token") {
          if (this._phaseTyper) {
            this._clearPhaseTyper();
            const phaseEntry = this.turnStream.find((e) => e.id === streamEntryId);
            if (phaseEntry) phaseEntry._phaseText = false;
          }
          this._streamingNarration += data.text;
          const entry = this.turnStream.find((e) => e.id === streamEntryId);
          if (entry) entry.text = this._streamingNarration;
          this._scrollStream();
        } else if (eventType === "complete") {
          this._clearPhaseTyper();
          const entry = this.turnStream.find((e) => e.id === streamEntryId);
          if (entry) {
            entry._phaseText = false;
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
        if (this.imageGenerating) {
          this.errorMessage = "Wait for image generation to finish before submitting a turn.";
          return;
        }
        const payload = {
          actor_id: this.turnForm.actor_id.trim(),
          action: this.turnForm.action.trim(),
          session_id: this.selectedSessionId || null,
        };
        if (!payload.action) return;
        if (this.submitting) {
          this._enqueueTurnPayload(this.selectedCampaignId, payload);
          return;
        }
        const result = await this._submitTurnPayload(this.selectedCampaignId, payload, { queued: false });
        if (!result.ok) {
          this.errorMessage = String(result.error);
        }
        await this._drainQueuedTurns();
      },

      async _submitTurnPayload(campaignId, payload, { queued = false } = {}) {
        this.submitting = true;
        this._submittingTurn = true;
        this.statusMessage = queued ? "Processing queued action..." : "Submitting turn...";
        let backendTurnId = 0;
        try {
          if (payload.action) {
            this.pushStream("player", payload.action, {
              actor_id: payload.actor_id,
              actor_name: this.resolveActorDisplayName(payload.actor_id, "", payload.actor_id),
            });
          }

          if (!this.runtimeInfo.streaming_supported) {
            const body = await this.api(`/api/campaigns/${campaignId}/turns`, {
              method: "POST",
              body: JSON.stringify(payload),
            });
            backendTurnId = Number(body.turn_id) || 0;
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

            const resp = await fetch(`/api/campaigns/${campaignId}/turns/stream`, {
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
              buffer = lines.pop();
              for (const line of lines) {
                if (line.startsWith("event: ")) {
                  currentEvent = line.slice(7).trim();
                } else if (line.startsWith("data: ")) {
                  currentData = line.slice(6);
                } else if (line === "") {
                  if (currentEvent && currentData) {
                    try {
                      const parsed = JSON.parse(currentData);
                      if (currentEvent === "complete") {
                        backendTurnId = Number(parsed.turn_id) || 0;
                      }
                      this._handleStreamEvent(currentEvent, parsed, streamEntryId);
                    } catch (_e) {
                    }
                  }
                  currentEvent = "";
                  currentData = "";
                }
              }
            }
            if (currentEvent && currentData) {
              try {
                const parsed = JSON.parse(currentData);
                if (currentEvent === "complete") {
                  backendTurnId = Number(parsed.turn_id) || 0;
                }
                this._handleStreamEvent(currentEvent, parsed, streamEntryId);
              } catch (_e) {
              }
            }

            this.turnForm.action = "";
          }

          await Promise.all([
            this.loadSessions(),
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
            this.loadChapterList(),
            this.loadSceneImages(),
          ]);
          if (backendTurnId > 0 && !this._recentTurnsContainTurnId(backendTurnId)) {
            console.warn("recent-turns refresh missing completed turn", {
              campaignId,
              actorId: payload.actor_id,
              sessionId: payload.session_id || null,
              turnId: backendTurnId,
            });
            this.statusMessage = "Turn completed. History refresh has not caught up yet; keeping the live result.";
            this._scheduleRecentTurnRecovery(backendTurnId);
            return { ok: true };
          }
          this.populateTurnStreamFromHistory();
          this.statusMessage = queued ? "Queued action submitted." : "Turn submitted.";
          return { ok: true };
        } catch (error) {
          return { ok: false, error };
        } finally {
          this._clearPhaseTyper();
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
          this.calendarEvents = Array.isArray(body.events) ? body.events : [];
          if (body.game_time && typeof body.game_time === "object") {
            this.gameTime = body.game_time;
          }
        } catch (_err) {
          this.calendarEvents = [];
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

      async loadSessions({ skipConnect } = {}) {
        if (!this.selectedCampaignId) {
          return;
        }
        let body;
        try {
          body = await this.api(`/api/campaigns/${this.selectedCampaignId}/sessions`);
        } catch (_err) {
          return;
        }
        const sessions = Array.isArray(body.sessions) ? body.sessions.slice() : [];
        sessions.sort((a, b) => {
          const aShared = a && a.surface === "web_shared" ? 1 : 0;
          const bShared = b && b.surface === "web_shared" ? 1 : 0;
          if (aShared !== bShared) return bShared - aShared;
          return String(a && a.created_at || "").localeCompare(String(b && b.created_at || ""));
        });
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
          if (!preferred && sessions.length > 0) {
            preferred = sessions.find((row) => row.enabled !== false) || sessions[0];
          }
          if (preferred && preferred.id) {
            this.selectedSessionId = preferred.id;
            localStorage.setItem("selectedSessionId", preferred.id);
            this.sessionLastSeen[preferred.id] = isoNow();
            this._persistSessionLastSeen();
            this.syncTurnSessionSelection();
          }
        }
        if (skipConnect) return;
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

      async ensureSharedWindow({ select = true, silent = false } = {}) {
        if (!silent) {
          this.resetError();
        }
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
          if (select && body.session && body.session.id) {
            this.selectSession(body.session.id);
          }
        } catch (error) {
          if (!silent) {
            this.errorMessage = String(error);
          }
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
          this.characterNameForm.value = this.resolveCharacterName("");
          this.playerStateText = formatJson(body);
        } catch (error) {
          this.playerData = null;
          this.characterNameForm.value = "";
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

      async renamePlayerCharacter() {
        this.resetError();
        if (!this.selectedCampaignId) return;
        const actor = (this.turnForm.actor_id || "").trim();
        const name = String(this.characterNameForm.value || "").trim().split(/\s+/).filter(Boolean).join(" ");
        if (!actor) {
          this.errorMessage = "Select an actor first.";
          return;
        }
        if (!name) {
          this.errorMessage = "Character name is required.";
          return;
        }
        this.characterNameSaving = true;
        try {
          const result = await this.api(`/api/campaigns/${this.selectedCampaignId}/player-name`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ actor_id: actor, name }),
          });
          const statusMessage = result.old_name && result.old_name !== result.name
            ? `Renamed ${result.old_name} to ${result.name}.`
            : `Saved ${result.name}.`;
          this.characterNameStatus = statusMessage;
          this.statusMessage = statusMessage;
          if (this.playerData && this.playerData.state) {
            this.playerData.state.character_name = result.name;
          }
          this.characterNameForm.value = result.name;
          await Promise.all([
            this.loadPlayerState(),
            this.loadPlayerStatistics(),
            this.loadPlayerAttributes(),
            this.loadRoster(),
            this.loadDebugSnapshot(),
          ]);
          this.characterNameStatus = statusMessage;
        } catch (error) {
          this.characterNameStatus = "";
          this.errorMessage = String(error);
        } finally {
          this.characterNameSaving = false;
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
          // Offset represents the number of newest turns already loaded
          this._turnStreamOffset = this.recentTurns.length;
          this._turnStreamHasMore = !!data.has_more;
        } catch (_) { this.recentTurns = []; this._turnStreamOffset = 0; this._turnStreamHasMore = false; }
      },

      async loadOlderTurns() {
        if (this._turnStreamLoadingOlder || !this._turnStreamHasMore || !this.selectedCampaignId) return;
        this._turnStreamLoadingOlder = true;
        try {
          const data = await this.api(
            `/api/campaigns/${this.selectedCampaignId}/recent-turns?limit=30&offset=${this._turnStreamOffset}`,
          );
          const older = Array.isArray(data.turns) ? data.turns : [];
          if (older.length === 0) {
            this._turnStreamHasMore = false;
            return;
          }
          const stream = document.getElementById("turn-stream");
          const prevHeight = stream ? stream.scrollHeight : 0;
          this.recentTurns = [...older, ...this.recentTurns];
          this._turnStreamOffset += older.length;
          this._turnStreamHasMore = !!data.has_more;
          this.populateTurnStreamFromHistory(false);
          this.$nextTick(() => {
            if (stream) stream.scrollTop = stream.scrollHeight - prevHeight;
          });
        } catch (_) {
          /* swallow — will retry on next scroll */
        } finally {
          this._turnStreamLoadingOlder = false;
        }
      },

      _resetPagination() {
        this._turnStreamOffset = 0;
        this._turnStreamHasMore = false;
        this._turnStreamLoadingOlder = false;
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

      /* ---- Extracted helper to reload all campaign data ---- */
      async _reloadCampaignData() {
        await Promise.all([
          this.loadPlayerState(),
          this.loadPlayerStatistics(),
          this.loadPlayerAttributes(),
          this.loadDebugSnapshot(),
          this.loadCampaignFlags(),
          this.loadStoryState(),
          this.loadChapterList(),
          this.loadCampaignPersona(),
          this.loadSceneImages(),
          this.loadLiteraryStyles(),
          this.loadSourceMaterials(),
        ]);
      },

      /* ---- Delete campaign by ID (allows deleting non-selected campaigns) ---- */
      async deleteCampaignById(id) {
        if (!id) return;
        if (!confirm("Delete this campaign and all its data? This cannot be undone.")) return;
        this.resetError();
        try {
          await this.api(`/api/campaigns/${id}`, { method: "DELETE" });
          this.statusMessage = "Campaign deleted.";
          if (this.selectedCampaignId === id) {
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
          }
          await this.refreshCampaigns();
        } catch (error) { this.errorMessage = String(error); }
      },

      /* ---- New Campaign Wizard methods ---- */
      resetNewCampaignWizard() {
        this.newCampaignWizard = {
          step: "info",
          name: "",
          actor_id: "",
          files: [],
          on_rails: false,
          createStatus: "",
          campaignId: null,
          setupPhase: null,
          setupResponse: "",
          setupMessages: [],
          setupMessage: "",
          setupSending: false,
          setupAttachmentText: "",
        };
      },

      handleWizardFileSelect(event) {
        this._addWizardFiles(Array.from(event.target.files || []));
        event.target.value = "";
      },

      handleWizardFileDrop(event) {
        this._addWizardFiles(Array.from(event.dataTransfer.files || []));
      },

      _addWizardFiles(files) {
        const w = this.newCampaignWizard;
        const existing = new Set(w.files.map(f => f.file.name));
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
          w.files.push(entry);
        }
      },

      removeWizardFile(index) {
        this.newCampaignWizard.files.splice(index, 1);
      },

      async wizardCreateCampaign() {
        const w = this.newCampaignWizard;
        if (!w.name.trim() || !w.actor_id.trim()) return;
        w.step = "creating";
        w.createStatus = "Creating campaign...";
        try {
          const createNamespace = (["", "*", "all"].includes((this.campaignForm.namespace || "").trim().toLowerCase()))
            ? "default"
            : (this.campaignForm.namespace || "default");
          const body = await this.api("/api/campaigns", {
            method: "POST",
            body: JSON.stringify({
              namespace: createNamespace,
              name: w.name.trim(),
              actor_id: w.actor_id.trim(),
            }),
          });
          const campaign = body.campaign;
          w.campaignId = campaign.id;
          await this.refreshCampaigns();
          await this.selectCampaign(campaign.id);

          // Ingest files
          const allTexts = [];
          if (w.files.length > 0) {
            w.createStatus = "Reading files...";
            await Promise.allSettled(w.files.map(f => f._ready));
            for (let i = 0; i < w.files.length; i++) {
              const f = w.files[i];
              if (!f.text || !f.text.trim()) continue;
              f.status = "uploading";
              w.createStatus = `Ingesting ${i + 1}/${w.files.length}: ${f.file.name}...`;
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
          }

          // Always start setup wizard
          w.createStatus = "Starting setup wizard...";
          await this.wizardStartSetup(allTexts);
        } catch (error) {
          this.errorMessage = String(error);
          w.step = "info";
        }
      },

      async wizardStartSetup(allTexts) {
        const w = this.newCampaignWizard;
        try {
          const payload = {
            actor_id: w.actor_id.trim(),
            on_rails: w.on_rails,
            attachment_text: (allTexts && allTexts.length > 0)
              ? allTexts.join("\n\n---\n\n")
              : ((w.setupAttachmentText || "").trim() || null),
          };
          const result = await this.api(`/api/campaigns/${w.campaignId}/setup/start`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          w.setupPhase = result.setup_phase || null;
          w.setupResponse = result.message || "";
          if (w.setupResponse) {
            w.setupMessages.push({ role: "narrator", text: w.setupResponse });
          }
          w.step = "setup";
          this._scrollWizardConversation();
        } catch (error) {
          this.errorMessage = String(error);
          w.step = "info";
        }
      },

      async wizardSendSetupMessage() {
        const w = this.newCampaignWizard;
        if (!w.campaignId || !w.setupMessage.trim()) return;
        w.setupSending = true;
        const userMsg = w.setupMessage.trim();
        w.setupMessages.push({ role: "player", text: userMsg });
        w.setupMessage = "";
        this._scrollWizardConversation();
        try {
          const result = await this.api(`/api/campaigns/${w.campaignId}/setup/message`, {
            method: "POST",
            body: JSON.stringify({
              actor_id: w.actor_id.trim(),
              message: userMsg,
            }),
          });
          w.setupResponse = result.message || "";
          w.setupPhase = result.setup_phase || null;
          if (w.setupResponse) {
            w.setupMessages.push({ role: "narrator", text: w.setupResponse });
            this._scrollWizardConversation();
          }
          if (result.completed) {
            w.step = "finalizing";
            await this._reloadCampaignData();
            w.step = "complete";
          }
        } catch (error) {
          this.errorMessage = String(error);
        } finally {
          w.setupSending = false;
        }
      },

      wizardFinish() {
        this.$store.app.closeModal();
        this.resetNewCampaignWizard();
        this.$nextTick(() => {
          const input = document.getElementById("action-input");
          if (input) input.focus();
        });
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

      renderSimpleMarkdown(text) {
        return renderSimpleMarkdown(text);
      },

      renderNarratorHtml(entry) {
        const scene = entry.meta && entry.meta.scene_output;
        return renderSceneOutputHtml(scene, entry.text);
      },

      resolveActorDisplayName(actorId, actorName, fallback) {
        const explicit = String(actorName || "").trim();
        if (explicit) return explicit;
        const actor = String(actorId || "").trim();
        if (actor && actor === String(this.turnForm.actor_id || "").trim()) {
          return this.resolveCharacterName(actor);
        }
        return actor || fallback || "Unknown";
      },

      turnEntryActorLabel(entry) {
        const meta = entry && entry.meta && typeof entry.meta === "object" ? entry.meta : {};
        return this.resolveActorDisplayName(meta.actor_id, meta.actor_name, "");
      },

      _scrollWizardConversation() {
        this.$nextTick(() => {
          const el = document.getElementById("wizard-conversation");
          if (el) el.scrollTop = el.scrollHeight;
        });
      },

      resolveCharacterName(fallback) {
        const cn = this.playerData?.state?.character_name;
        if (!cn) return fallback || this.turnForm.actor_id || "Unknown";
        if (typeof cn === "object" && cn.name) return cn.name;
        const s = String(cn);
        // Handle Python dict repr like "{'name': 'Samwise Gamgee', 'role': '...'}"
        const m = s.match(/'name'\s*:\s*'([^']+)'/);
        if (m) return m[1];
        return s;
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
          const rawTurnIds = (this.memory.searchWithinTurnIds || "").trim();
          if (rawTurnIds) {
            const turnIds = rawTurnIds.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n) && n > 0);
            if (turnIds.length) {
              payload.search_within_turn_ids = turnIds;
            }
          }
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
