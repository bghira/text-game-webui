(function () {
  function formatJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function nowLabel() {
    return new Date().toLocaleTimeString();
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

  window.textGameApp = function textGameApp() {
    return {
      campaigns: [],
      selectedCampaignId: null,
      inspectorTab: "map",
      statusMessage: "Ready.",
      errorMessage: "",
      turnCounter: 0,
      socket: null,
      turnStream: [],

      campaignForm: {
        namespace: "default",
        name: "",
        actor_id: "",
      },
      turnForm: {
        actor_id: "",
        action: "",
      },
      memory: {
        search: "",
        category: "",
        wildcard: "*",
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

      mapText: "",
      calendarText: "",
      rosterText: "",
      memoryText: "",
      smsText: "",
      debugText: "",

      async init() {
        await this.refreshCampaigns();
        this.statusMessage = "Initialized.";
      },

      async api(path, options) {
        const config = {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          ...options,
        };
        const response = await fetch(path, config);
        const raw = await response.text();
        const data = raw ? JSON.parse(raw) : {};
        if (!response.ok) {
          const detail = data.detail || raw || "Request failed";
          throw new Error(detail);
        }
        return data;
      },

      resetError() {
        this.errorMessage = "";
      },

      pushStream(type, text) {
        this.turnCounter += 1;
        this.turnStream.push({ id: this.turnCounter, type, at: nowLabel(), text });
        this.$nextTick(() => {
          const stream = document.getElementById("turn-stream");
          if (stream) {
            stream.scrollTop = stream.scrollHeight;
          }
        });
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
        const selected = this.campaigns.find((row) => row.id === campaignId);
        if (selected && !this.turnForm.actor_id) {
          this.turnForm.actor_id = selected.actor_id;
        }
        this.connectSocket();
        await Promise.all([
          this.loadMap(),
          this.loadCalendar(),
          this.loadRoster(),
          this.loadDebugSnapshot(),
        ]);
        this.statusMessage = `Selected campaign ${campaignId}.`;
      },

      connectSocket() {
        if (!this.selectedCampaignId) {
          return;
        }
        if (this.socket) {
          this.socket.close();
        }
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const socketUrl = `${protocol}://${window.location.host}/ws/campaigns/${this.selectedCampaignId}`;
        this.socket = new WebSocket(socketUrl);
        this.socket.onopen = () => {
          this.statusMessage = "Realtime connected.";
        };
        this.socket.onmessage = (event) => {
          const payload = JSON.parse(event.data);
          if (payload.type === "turn" && payload.payload) {
            this.pushStream("narrator", normalizeTurnNarration(payload.payload));
          }
          if (payload.type === "sms" && payload.payload) {
            this.pushStream("sms", formatJson(payload.payload));
          }
        };
        this.socket.onerror = () => {
          this.errorMessage = "WebSocket error.";
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
          };
          const body = await this.api(`/api/campaigns/${this.selectedCampaignId}/turns`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          const narration = normalizeTurnNarration(body);
          this.pushStream("narrator", narration);
          if (body.image_prompt) {
            this.pushStream("image_prompt", body.image_prompt);
          }
          if (body.summary_update) {
            this.pushStream("summary", body.summary_update);
          }
          this.turnForm.action = "";
          await Promise.all([
            this.loadMap(),
            this.loadCalendar(),
            this.loadRoster(),
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
