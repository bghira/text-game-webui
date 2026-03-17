from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.settings import Settings
from app.services.schemas import CampaignSummary, MemoryStoreRequest, TurnRequest, TurnResult

from .engine_gateway import EngineGateway

try:
    from text_game_engine.core.engine import GameEngine
    from text_game_engine.core.types import GiveItemInstruction, LLMTurnOutput, TimerInstruction
    from text_game_engine.tool_aware_llm import (
        DeterministicLLM as EngineDeterministicLLM,
        ToolAwareZorkLLM as EngineToolAwareLLM,
    )
    from text_game_engine.persistence.sqlalchemy import (
        SQLAlchemyUnitOfWork,
        build_engine,
        build_session_factory,
        create_schema,
    )
    from text_game_engine.persistence.sqlalchemy.models import (
        Campaign,
        Embedding,
        InflightTurn,
        MediaRef,
        OutboxEvent,
        Player,
        Session as GameSession,
        Snapshot,
        Timer,
        Turn,
    )
    from text_game_engine.core.source_material_memory import SourceMaterialMemory
    from text_game_engine.zork_emulator import ZorkEmulator
except Exception as exc:  # pragma: no cover - import guarded at runtime
    raise RuntimeError(
        "text-game-engine backend selected but package is unavailable. "
        "Install it with: pip install -e ../text-game-engine"
    ) from exc


class CompletionPortProtocol(Protocol):
    async def complete(
        self,
        system_prompt: str,
        prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> str | None:
        ...

    async def probe(self, timeout_seconds: int = 8) -> tuple[bool, str]:
        ...


class OpenAICompatibleCompletionPort:
    """Minimal OpenAI-compatible /chat/completions client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 90,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = max(int(timeout_seconds or 90), 1)

    @staticmethod
    def _extract_content(choice: dict[str, Any]) -> str:
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
                    continue
                nested = item.get("content")
                if isinstance(nested, str) and nested.strip():
                    parts.append(nested)
            return "\n".join(parts).strip()
        return ""

    def _request_sync(self, payload: dict[str, Any]) -> str | None:
        url = f"{self._base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            _ = exc.read().decode("utf-8", errors="replace")
            return None
        except Exception:
            return None

        try:
            data = json.loads(raw)
        except Exception:
            return None

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        content = self._extract_content(choices[0])
        return content or None

    async def complete(
        self,
        system_prompt: str,
        prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> str | None:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        return await asyncio.to_thread(self._request_sync, payload)

    async def probe(self, timeout_seconds: int = 8) -> tuple[bool, str]:
        timeout = max(int(timeout_seconds or 8), 1)
        try:
            response = await asyncio.wait_for(
                self.complete(
                    "Return ONLY the token OK.",
                    "health check",
                    temperature=0.0,
                    max_tokens=8,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            return False, f"Timed out after {timeout}s."
        except Exception as exc:
            return False, f"Probe failed: {exc.__class__.__name__}"

        if not response or not response.strip():
            return False, "No completion content returned."
        return True, "Completion endpoint responded."


class OllamaCompletionPort:
    """Ollama completion port using the OpenAI-compatible /v1/chat/completions endpoint.

    Ollama 0.13+ removed the native /api/chat and /api/generate endpoints.
    This implementation targets the stable /v1/chat/completions endpoint and
    includes Ollama-specific extras (keep_alive, options) in the request body.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: int = 90,
        keep_alive: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        # Normalise to bare host so we can append /v1/chat/completions.
        clean_url = base_url.rstrip("/")
        for suffix in ("/v1", "/api"):
            if clean_url.endswith(suffix):
                clean_url = clean_url[: -len(suffix)]
                break
        self._base_url = clean_url
        self._model = model
        self._timeout_seconds = max(int(timeout_seconds or 90), 1)
        self._keep_alive = keep_alive
        self._options = dict(options or {})

    def _request_sync(self, payload: dict[str, Any]) -> str | None:
        url = f"{self._base_url}/v1/chat/completions"
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError:
            return None
        except Exception:
            return None

        try:
            data = json.loads(raw)
        except Exception:
            return None

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        return OpenAICompatibleCompletionPort._extract_content(choices[0]) or None

    async def complete(
        self,
        system_prompt: str,
        prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> str | None:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        if self._options:
            payload["options"] = self._options
        return await asyncio.to_thread(self._request_sync, payload)

    async def probe(self, timeout_seconds: int = 8) -> tuple[bool, str]:
        timeout = max(int(timeout_seconds or 8), 1)
        try:
            response = await asyncio.wait_for(
                self.complete(
                    "Return ONLY the token OK.",
                    "health check",
                    temperature=0.0,
                    max_tokens=8,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            return False, f"Timed out after {timeout}s."
        except Exception as exc:
            return False, f"Probe failed: {exc.__class__.__name__}"

        if not response or not response.strip():
            return False, "No completion content returned."
        return True, "Ollama endpoint responded."


class DeterministicLLM:
    """Local fallback LLM for webui adapter bring-up."""

    @staticmethod
    def _advance_time(game_time: dict[str, Any]) -> dict[str, Any]:
        day = int(game_time.get("day", 1) or 1)
        hour = int(game_time.get("hour", 8) or 8)
        minute = int(game_time.get("minute", 0) or 0)

        minute += 10
        if minute >= 60:
            hour += minute // 60
            minute = minute % 60
        if hour >= 24:
            day += hour // 24
            hour = hour % 24

        if hour < 12:
            period = "morning"
        elif hour < 17:
            period = "afternoon"
        elif hour < 21:
            period = "evening"
        else:
            period = "night"

        return {
            "day": day,
            "hour": hour,
            "minute": minute,
            "period": period,
            "date_label": f"Day {day}, {period.title()}",
        }

    async def complete_turn(self, context, *, progress=None) -> LLMTurnOutput:
        action = (context.action or "").strip()
        lowered = action.lower()
        current_time = context.campaign_state.get("game_time", {}) if isinstance(context.campaign_state, dict) else {}
        next_time = self._advance_time(current_time if isinstance(current_time, dict) else {})

        if any(token in lowered for token in ["look", "scan", "observe", "examine"]):
            return LLMTurnOutput(
                narration="You pause and take stock. The room is quiet, details sharp at the edges.",
                state_update={"game_time": next_time},
                summary_update="You took a careful look around.",
                xp_awarded=1,
                player_state_update={
                    "room_title": "Holding Room",
                    "room_summary": "A functional room with steel desk, chair, and one narrow door.",
                    "location": "holding-room",
                    "exits": ["north door", "desk drawer"],
                },
                scene_image_prompt=(
                    "Sparse holding room, steel desk under fluorescent lighting, muted colors, "
                    "narrow door with worn paint, realistic perspective"
                ),
            )

        if any(token in lowered for token in ["wait", "rest", "sleep"]):
            return LLMTurnOutput(
                narration="Time passes in measured silence.",
                state_update={"game_time": next_time},
                summary_update="You waited and let the scene breathe.",
                xp_awarded=0,
                player_state_update={"room_summary": "Still in the holding room. Nothing immediate changes."},
            )

        return LLMTurnOutput(
            narration=f"You {action}. The world answers with small, immediate consequences.",
            state_update={"game_time": next_time},
            summary_update=f"Action resolved: {action}",
            xp_awarded=1,
            player_state_update={"room_summary": "You remain in control of the next move."},
        )


class ZorkToolAwareLLM:
    """Model adapter that reuses ZorkEmulator prompt + tool call semantics."""
    AUTO_FIX_COUNTERS_KEY = "_auto_fix_counters"

    def __init__(
        self,
        *,
        session_factory,
        completion_port: CompletionPortProtocol,
        temperature: float,
        max_tokens: int,
        max_tool_rounds: int = 4,
    ) -> None:
        self._session_factory = session_factory
        self._completion = completion_port
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        self._max_tool_rounds = int(max_tool_rounds)
        self._fallback = DeterministicLLM()
        self._emulator: ZorkEmulator | None = None

    def bind_emulator(self, emulator: ZorkEmulator) -> None:
        self._emulator = emulator

    @staticmethod
    def _parse_json(text: str | None, default: Any) -> Any:
        if not text:
            return default
        try:
            return json.loads(text)
        except Exception:
            return default

    @staticmethod
    def _tool_call_signature(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        try:
            return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        except Exception:
            return str(payload)

    def _bump_auto_fix_counter(
        self,
        campaign_id: str,
        key: str,
        amount: int = 1,
    ) -> None:
        safe_key = re.sub(r"[^a-z0-9_]+", "_", str(key or "").strip().lower()).strip("_")
        if not safe_key:
            return
        try:
            safe_amount = max(1, int(amount))
        except Exception:
            safe_amount = 1
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            counters = state.get(self.AUTO_FIX_COUNTERS_KEY)
            if not isinstance(counters, dict):
                counters = {}
                state[self.AUTO_FIX_COUNTERS_KEY] = counters
            try:
                current = max(0, int(counters.get(safe_key, 0) or 0))
            except Exception:
                current = 0
            counters[safe_key] = min(10**9, current + safe_amount)
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()

    @staticmethod
    def _should_force_auto_memory_search(action_text: str) -> bool:
        if re.match(r"\s*\[OOC\b", str(action_text or ""), re.IGNORECASE):
            return False
        text = " ".join(str(action_text or "").strip().lower().split())
        if not text or text.startswith("!") or len(text) < 6:
            return False
        trivial = {
            "look",
            "l",
            "inventory",
            "inv",
            "i",
            "map",
            "yes",
            "y",
            "no",
            "n",
            "ok",
            "okay",
            "thanks",
            "thank you",
        }
        return text not in trivial

    def _derive_auto_memory_queries(
        self,
        campaign_id: str,
        actor_id: str,
        action_text: str,
        limit: int = 4,
    ) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        def _push(raw: object) -> None:
            text = " ".join(str(raw or "").strip().split())
            if not text:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            out.append(text[:120])

        with self._session_factory() as session:
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            pstate = self._parse_json(player.state_json if player is not None else "{}", {})
            if isinstance(pstate, dict):
                _push(pstate.get("location"))
                _push(pstate.get("room_title"))
                player_name = " ".join(str(pstate.get("character_name") or "").strip().lower().split())
            else:
                player_name = ""

            others = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .order_by(Player.actor_id.asc())
                .all()
            )
            for row in others[:6]:
                ostate = self._parse_json(row.state_json or "{}", {})
                if not isinstance(ostate, dict):
                    continue
                name = " ".join(str(ostate.get("character_name") or "").strip().split())
                if not name:
                    continue
                if name.lower() == player_name:
                    continue
                _push(name)
                if len(out) >= limit:
                    break

        _push(action_text)
        return out[: max(1, int(limit or 4))]

    @staticmethod
    def _is_emptyish_payload(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return True
        narration = " ".join(str(payload.get("narration") or "").strip().lower().split())
        trivial_narration = narration in {
            "",
            "the world shifts, but nothing clear emerges.",
            "a hollow silence answers. try again.",
            "a hollow silence answers.",
        }
        short_narration = len(narration) < 24
        state_update = payload.get("state_update")
        player_state_update = payload.get("player_state_update")
        summary_update = payload.get("summary_update")
        character_updates = payload.get("character_updates")
        calendar_update = payload.get("calendar_update")
        scene_image_prompt = payload.get("scene_image_prompt")
        xp_awarded = payload.get("xp_awarded", 0)
        has_signal = bool(state_update) or bool(player_state_update) or bool(character_updates) or bool(calendar_update)
        has_signal = has_signal or bool(str(summary_update or "").strip()) or bool(str(scene_image_prompt or "").strip())
        try:
            has_signal = has_signal or int(xp_awarded or 0) > 0
        except Exception:
            pass
        if trivial_narration and not has_signal:
            return True
        if short_narration and not has_signal:
            return True
        return False

    @staticmethod
    def _looks_like_major_narrative_beat(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        narration = " ".join(str(payload.get("narration") or "").lower().split())
        summary = " ".join(str(payload.get("summary_update") or "").lower().split())
        text = f"{narration} {summary}".strip()
        cues = (
            "reveals",
            "reveal",
            "confirms",
            "confirmed",
            "pregnant",
            "paternity",
            "dies",
            "dead",
            "betray",
            "arrest",
            "results",
            "test result",
            "identity",
            "truth",
            "confession",
            "escape",
            "ambush",
        )
        if any(cue in text for cue in cues):
            return True
        if isinstance(payload.get("character_updates"), dict):
            for row in payload.get("character_updates", {}).values():
                if isinstance(row, dict) and str(row.get("deceased_reason") or "").strip():
                    return True
        if isinstance(payload.get("calendar_update"), dict):
            cal = payload.get("calendar_update") or {}
            if isinstance(cal.get("add"), list) or isinstance(cal.get("remove"), list):
                return True
        if isinstance(payload.get("state_update"), dict):
            if "current_chapter" in payload.get("state_update", {}) or "current_scene" in payload.get("state_update", {}):
                return True
        return False

    @staticmethod
    def _action_requests_clock_time(action_text: str) -> bool:
        text = " ".join(str(action_text or "").strip().lower().split())
        if not text:
            return False
        return any(
            token in text
            for token in (
                "what time",
                "current time",
                "check time",
                "clock",
                "time is it",
            )
        )

    @staticmethod
    def _narration_has_explicit_clock_time(narration_text: str) -> bool:
        return bool(re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", str(narration_text or "")))

    def _fallback_memory_state(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return []
            state = self._parse_json(campaign.state_json, {})
        rows = state.get("_webui_curated_memory", []) if isinstance(state, dict) else []
        return rows if isinstance(rows, list) else []

    def _persist_fallback_memory_state(self, campaign_id: str, entries: list[dict[str, Any]]) -> None:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            state["_webui_curated_memory"] = entries[-500:]
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()

    def _parse_model_payload(self, response: str | None) -> dict[str, Any] | None:
        emulator = self._emulator
        if emulator is None:
            return None
        if not response:
            return None
        cleaned = emulator._clean_response(response)  # noqa: SLF001
        json_text = emulator._extract_json(cleaned)  # noqa: SLF001
        try:
            payload = emulator._parse_json_lenient(json_text or cleaned)  # noqa: SLF001
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _payload_to_output(self, payload: dict[str, Any]) -> LLMTurnOutput:
        emulator = self._emulator
        if emulator is None:
            return LLMTurnOutput(narration="")

        narration = payload.get("narration")
        if not isinstance(narration, str):
            narration = ""

        state_update = payload.get("state_update")
        if not isinstance(state_update, dict):
            state_update = {}

        player_state_update = payload.get("player_state_update")
        if not isinstance(player_state_update, dict):
            player_state_update = {}

        turn_visibility = payload.get("turn_visibility")
        if not isinstance(turn_visibility, dict):
            turn_visibility = None

        state_update, player_state_update = emulator._split_room_state(state_update, player_state_update)  # noqa: SLF001

        summary_update = payload.get("summary_update")
        if not isinstance(summary_update, str) or not summary_update.strip():
            summary_update = None
        reasoning = payload.get("reasoning")
        if isinstance(reasoning, str):
            reasoning = " ".join(reasoning.strip().split())[:1200] or None
        else:
            reasoning = None

        xp_awarded_raw = payload.get("xp_awarded", 0)
        try:
            xp_awarded = max(0, min(10, int(xp_awarded_raw)))
        except Exception:
            xp_awarded = 0

        scene_image_prompt = payload.get("scene_image_prompt")
        if not isinstance(scene_image_prompt, str) or not scene_image_prompt.strip():
            image_prompt = payload.get("image_prompt")
            if isinstance(image_prompt, str) and image_prompt.strip():
                scene_image_prompt = image_prompt
            else:
                scene_image_prompt = None

        timer_instruction = None
        timer_delay = payload.get("set_timer_delay")
        timer_event = payload.get("set_timer_event")
        if isinstance(timer_delay, (int, float)) and isinstance(timer_event, str) and timer_event.strip():
            timer_interruptible = payload.get("set_timer_interruptible", True)
            timer_interrupt_action = payload.get("set_timer_interrupt_action")
            timer_scope = payload.get("set_timer_interrupt_scope", "global")
            if not isinstance(timer_scope, str) or timer_scope.strip().lower() not in {"local", "global"}:
                timer_scope = "global"
            timer_instruction = TimerInstruction(
                delay_seconds=max(1, int(timer_delay)),
                event_text=timer_event.strip(),
                interruptible=bool(timer_interruptible),
                interrupt_action=str(timer_interrupt_action).strip() if timer_interrupt_action is not None else None,
                interrupt_scope=timer_scope,
            )

        give_item = None
        give_item_payload = payload.get("give_item")
        if isinstance(give_item_payload, dict):
            item = give_item_payload.get("item")
            if isinstance(item, str) and item.strip():
                to_actor_id = give_item_payload.get("to_actor_id")
                to_discord_mention = give_item_payload.get("to_discord_mention")
                give_item = GiveItemInstruction(
                    item=item.strip(),
                    to_actor_id=to_actor_id.strip() if isinstance(to_actor_id, str) and to_actor_id.strip() else None,
                    to_discord_mention=(
                        to_discord_mention.strip()
                        if isinstance(to_discord_mention, str) and to_discord_mention.strip()
                        else None
                    ),
                )

        character_updates = payload.get("character_updates")
        if not isinstance(character_updates, dict):
            character_updates = {}

        return LLMTurnOutput(
            narration=narration,
            reasoning=reasoning,
            state_update=state_update,
            summary_update=summary_update,
            xp_awarded=xp_awarded,
            player_state_update=player_state_update,
            turn_visibility=turn_visibility,
            scene_image_prompt=scene_image_prompt,
            timer_instruction=timer_instruction,
            character_updates=character_updates,
            give_item=give_item,
        )

    def _tool_memory_search(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> str:
        queries_raw = payload.get("queries")
        category_raw = payload.get("category")

        queries: list[str] = []
        if isinstance(queries_raw, list):
            for row in queries_raw:
                if isinstance(row, str) and row.strip():
                    queries.append(row.strip())
        elif isinstance(queries_raw, str) and queries_raw.strip():
            queries.append(queries_raw.strip())

        category = category_raw.strip() if isinstance(category_raw, str) and category_raw.strip() else None
        category_scope = " ".join((category or "").lower().split())
        interaction_participant_slug: str | None = None
        awareness_npc_slug: str | None = None
        visibility_scope_filter: str | None = None
        structured_turn_scope = False
        if category_scope in {"interaction", "interactions"}:
            structured_turn_scope = True
        elif category_scope.startswith("interaction:") and self._emulator is not None:
            structured_turn_scope = True
            interaction_participant_slug = self._emulator._player_slug_key(category_scope.split(":", 1)[1])  # noqa: SLF001
        elif category_scope.startswith("awareness:"):
            structured_turn_scope = True
            awareness_npc_slug = category_scope.split(":", 1)[1].strip() or None
        elif category_scope.startswith("visibility:"):
            structured_turn_scope = True
            visibility_scope_filter = category_scope.split(":", 1)[1].strip().lower() or None
        if not queries:
            return "MEMORY_RECALL: No queries provided."
        try:
            source_before_lines = int(payload.get("before_lines", 0))
        except Exception:
            source_before_lines = 0
        try:
            source_after_lines = int(payload.get("after_lines", 0))
        except Exception:
            source_after_lines = 0
        source_before_lines = max(0, min(50, source_before_lines))
        source_after_lines = max(0, min(50, source_after_lines))

        curated_hits: list[tuple[str, str, float]] = []
        source_docs: list[dict[str, Any]] = []
        has_source_material = False
        source_scope = False
        source_scope_key: str | None = None
        source_doc_formats: dict[str, str] = {}
        if self._emulator is not None:
            source_docs = self._emulator.list_source_material_documents(campaign_id, limit=8)
            has_source_material = bool(source_docs)
            for row in source_docs:
                doc_key = str(row.get("document_key") or "")
                if not doc_key:
                    continue
                doc_format = str(row.get("format") or "").strip().lower()
                if not doc_format:
                    doc_format = str(
                        self._emulator._source_material_format_heuristic(  # noqa: SLF001
                            str(row.get("sample_chunk") or "")
                        )
                    ).strip().lower()
                if not doc_format:
                    doc_format = "generic"
                source_doc_formats[doc_key] = doc_format
            if category_scope in {"source", "source-material"}:
                source_scope = True
            elif category_scope.startswith("source:"):
                source_scope = True
                source_scope_key = category_scope.split(":", 1)[1].strip() or None
            for query in queries[:4]:
                curated_hits.extend(
                    self._emulator.search_curated_memories(
                        query=query,
                        campaign_id=campaign_id,
                        category=category,
                        top_k=5,
                    )
                )

        roster_hints: list[dict[str, Any]] = []
        if self._emulator is not None and hasattr(self._emulator, "record_memory_search_usage"):
            try:
                roster_hints_raw = self._emulator.record_memory_search_usage(campaign_id, queries[:8])
                if isinstance(roster_hints_raw, list):
                    for row in roster_hints_raw:
                        if isinstance(row, dict):
                            roster_hints.append(row)
            except Exception:
                roster_hints = []

        narrator_hits: dict[int, dict[str, Any]] = {}
        with self._session_factory() as session:
            turns = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .filter(Turn.kind == "narrator")
                .order_by(Turn.id.desc())
                .limit(500)
                .all()
            )
            actor_row = None
            if actor_id:
                actor_row = (
                    session.query(Player)
                    .filter(Player.campaign_id == campaign_id)
                    .filter(Player.actor_id == actor_id)
                    .first()
                )
        actor_slug = None
        actor_location_key = ""
        if actor_row is not None and self._emulator is not None:
            actor_state = self._parse_json(actor_row.state_json, {})
            actor_slug = self._emulator._player_visibility_slug(actor_id)  # noqa: SLF001
            actor_location_key = self._emulator._room_key_from_player_state(actor_state)  # noqa: SLF001

        for query in queries[:4]:
            q = query.lower().strip()
            parts = [token for token in re.split(r"\W+", q) if token]
            for turn in turns:
                content = str(turn.content or "")
                if not content:
                    continue
                meta = self._parse_json(turn.meta_json, {})
                visibility = meta.get("visibility") if isinstance(meta, dict) else None
                if actor_id and self._emulator is not None:
                    if not self._emulator._turn_visible_to_viewer(turn, actor_id, actor_slug or "", actor_location_key.lower()):  # noqa: SLF001
                        continue
                if structured_turn_scope:
                    actor_player_slug = str(meta.get("actor_player_slug") or "").strip()
                    if interaction_participant_slug:
                        visible_player_slugs = visibility.get("visible_player_slugs") if isinstance(visibility, dict) else []
                        visible_slug_set = {
                            self._emulator._player_slug_key(item)  # noqa: SLF001
                            for item in (visible_player_slugs if isinstance(visible_player_slugs, list) else [])
                            if self._emulator is not None
                        }
                        if actor_player_slug != interaction_participant_slug and interaction_participant_slug not in visible_slug_set:
                            continue
                    if awareness_npc_slug:
                        aware_npc_slugs = visibility.get("aware_npc_slugs") if isinstance(visibility, dict) else []
                        if awareness_npc_slug not in {
                            str(item or "").strip() for item in (aware_npc_slugs if isinstance(aware_npc_slugs, list) else [])
                        }:
                            continue
                    if visibility_scope_filter in {"public", "private", "limited", "local"}:
                        row_scope = str((visibility or {}).get("scope") or "public").strip().lower()
                        if row_scope != visibility_scope_filter:
                            continue
                hay = content.lower()
                score = 0.0
                if q and q in hay:
                    score = 1.0
                elif parts:
                    score = sum(1 for token in parts if token in hay) / len(parts)
                if score <= 0.0:
                    continue
                prior = narrator_hits.get(int(turn.id))
                if prior is None or score > float(prior.get("score", 0.0)):
                    narrator_hits[int(turn.id)] = {
                        "turn_id": int(turn.id),
                        "score": score,
                        "content": content,
                        "visibility_scope": str((visibility or {}).get("scope") or "public"),
                        "actor_player_slug": str(meta.get("actor_player_slug") or ""),
                        "location_key": str(meta.get("location_key") or ""),
                    }

        ordered_narrator = sorted(
            narrator_hits.values(),
            key=lambda row: (float(row.get("score", 0.0)), int(row.get("turn_id", 0))),
            reverse=True,
        )[:5]
        source_hits_flat: list[tuple[str, str, int, str, float]] = []
        if self._emulator is not None and has_source_material and (source_scope or not category_scope):
            for query in queries[:4]:
                source_hits_flat.extend(
                    self._emulator.search_source_material(
                        query,
                        campaign_id,
                        document_key=source_scope_key,
                        top_k=10 if source_scope else 6,
                        before_lines=source_before_lines,
                        after_lines=source_after_lines,
                    )
                )
        source_hits_unique: list[tuple[str, str, int, str, float]] = []
        seen_source = set()
        for row in source_hits_flat:
            row_key = (str(row[0] or ""), int(row[2] or 0))
            if row_key in seen_source:
                continue
            seen_source.add(row_key)
            source_hits_unique.append(row)
        source_hits_unique = source_hits_unique[:12]

        lines = ["MEMORY_RECALL (results from memory_search):"]
        for query in queries[:4]:
            lines.append(f"Results for '{query}':")
        lines.append("Narrator turn matches:")
        if ordered_narrator:
            for hit in ordered_narrator:
                snippet = str(hit.get("content") or "").strip().replace("\n", " ")
                if len(snippet) > 280:
                    snippet = snippet[:279].rstrip() + "..."
                lines.append(
                    "- [narrator turn "
                    f"{hit['turn_id']}, relevance {float(hit['score']):.2f}"
                    f"{', actor ' + str(hit.get('actor_player_slug')) if hit.get('actor_player_slug') else ''}"
                    f"{', visibility ' + str(hit.get('visibility_scope')) if str(hit.get('visibility_scope') or 'public') != 'public' else ''}"
                    f"{', location ' + str(hit.get('location_key')) if hit.get('location_key') else ''}"
                    f"]: {snippet}"
                )
        else:
            lines.append("- (no narrator turn matches)")

        if curated_hits:
            lines.append("Curated memory matches:")
            for term, memory, score in curated_hits[:5]:
                snippet = str(memory or "").strip().replace("\n", " ")
                if len(snippet) > 220:
                    snippet = snippet[:219].rstrip() + "..."
                lines.append(f"- [term {term}, relevance {float(score):.2f}]: {snippet}")
        if source_hits_unique:
            lines.append("Source material matches:")
            for source_doc_key, source_doc_label, source_chunk_index, source_chunk_text, source_score in source_hits_unique:
                if float(source_score) < 0.40:
                    continue
                source_format = source_doc_formats.get(source_doc_key, "generic")
                source_text_lines = [
                    line.strip()
                    for line in str(source_chunk_text or "").splitlines()
                    if line.strip()
                ]
                source_text = (
                    "\n    ".join(source_text_lines)
                    if source_text_lines
                    else str(source_chunk_text or "").strip()
                )
                if len(source_text) > 4000:
                    source_text = source_text[:4000].rsplit(" ", 1)[0].strip() + "..."
                lines.append(
                    "- [source "
                    f"{source_doc_label} ({source_doc_key}) snippet {int(source_chunk_index)}, "
                    f"format {source_format}, relevance {float(source_score):.2f}]:\n    {source_text}"
                )
        elif has_source_material and source_scope:
            scope_label = f"source:{source_scope_key}" if source_scope_key else "source"
            lines.append(f"Source material matches: (none in scope '{scope_label}')")
        if has_source_material:
            total_snippets = 0
            for row in source_docs:
                try:
                    total_snippets += int(row.get("chunk_count") or 0)
                except Exception:
                    continue
            lines.append(
                f"SOURCE_MATERIAL_INDEX: {len(source_docs)} document(s), {total_snippets} total snippet(s)."
            )
            for row in source_docs[:5]:
                row_format = str(row.get("format") or "").strip().lower()
                if not row_format:
                    row_format = source_doc_formats.get(
                        str(row.get("document_key") or ""), "generic"
                    )
                lines.append(
                    "- "
                    f"key='{row.get('document_key')}' "
                    f"label='{row.get('document_label')}' "
                    f"format='{row_format}' "
                    f"snippets={row.get('chunk_count')}"
                )

        lines.extend(
            [
                "MEMORY_RECALL_NEXT_ACTIONS:",
                "- To retrieve FULL text for a specific hit turn number:",
                '  {"tool_call": "memory_turn", "turn_id": 1234}',
                "- To discover curated memory categories/terms before narrowing search:",
                '  {"tool_call": "memory_terms", "wildcard": "char:*"}',
                "- To search inside one curated category after term discovery:",
                '  {"tool_call": "memory_search", "category": "char:character-slug", "queries": ["keyword1", "keyword2"]}',
                "- To search narrator memories for interactions involving a player slug:",
                '  {"tool_call": "memory_search", "category": "interaction:player-slug", "queries": ["argument", "deal", "kiss"]}',
                "- To search for turns noticed by a specific NPC slug:",
                '  {"tool_call": "memory_search", "category": "awareness:npc-slug", "queries": ["overheard", "promise", "secret"]}',
                "- To restrict narrator-memory recall by visibility scope:",
                '  {"tool_call": "memory_search", "category": "visibility:private", "queries": ["secret meeting"]}',
                '  {"tool_call": "memory_search", "category": "visibility:local", "queries": ["bar argument"]}',
                "- To inspect off-scene SMS communications:",
                '  {"tool_call": "sms_list", "wildcard": "*"}',
                '  {"tool_call": "sms_read", "thread": "contact-slug", "limit": 20}',
                "- To schedule a delayed incoming SMS (hidden until delivery):",
                '  {"tool_call": "sms_schedule", "thread": "contact-slug", "from": "NPC", "to": "Player", "message": "...", "delay_seconds": 120}',
            ]
        )
        if has_source_material:
            source_formats = sorted(set(source_doc_formats.values()) or {"generic"})
            source_formats_set = set(source_formats)
            has_rulebook = "rulebook" in source_formats_set
            has_only_generic = source_formats_set == {"generic"}
            format_descriptions = {
                "story": "scripted scenes / prose",
                "rulebook": "line facts (`KEY: value`)",
                "generic": "notes/dumps (usually not indexed)",
            }
            lines.extend(
                [
                    "SOURCE_MATERIAL_FORMAT_GUIDE:",
                    f"- Active formats: {', '.join(source_formats)}",
                ]
            )
            for fmt in source_formats:
                lines.append(f"- {fmt}: {format_descriptions.get(fmt, fmt)}")
            lines.extend(
                [
                    "To inspect source text:",
                    '  {"tool_call": "memory_search", "category": "source", "queries": ["keyword"]}',
                    '  {"tool_call": "memory_search", "category": "source:<document-key>", "queries": ["keyword"]}',
                ]
            )
            if has_only_generic:
                lines.append(
                    "- Generic docs are usually summarized in setup prompts; use source search only for "
                    "exact wording when needed."
                )
            if has_rulebook:
                lines.extend(
                    [
                        "- Rulebook docs expose keyed snippets. First pass (no filter) to discover keys:",
                        '  {"tool_call": "source_browse"}',
                        '  {"tool_call": "source_browse", "document_key": "document-key"}',
                        "Then narrow with wildcard keys:",
                        '  {"tool_call": "source_browse", "wildcard": "keyword*"}',
                    ]
                )
        if roster_hints:
            lines.append("MEMORY_RECALL_ROSTER_RECOMMENDATIONS:")
            for hint in roster_hints[:6]:
                term = str(hint.get("term") or hint.get("slug") or "").strip() or "unknown-term"
                slug = str(hint.get("slug") or "").strip() or "character-slug"
                try:
                    count = int(hint.get("count") or 0)
                except Exception:
                    count = 0
                lines.append(
                    "- You have looked for "
                    f"'{term}' {count} times and it is not present in WORLD_CHARACTERS. "
                    "If this is stable/non-stale information and you can confirm it, "
                    f"store it with character_updates using slug '{slug}'."
                )
        return "\n".join(lines)

    def _tool_memory_terms(self, campaign_id: str, payload: dict[str, Any]) -> str:
        wildcard_raw = payload.get("wildcard")
        wildcard = wildcard_raw.strip() if isinstance(wildcard_raw, str) and wildcard_raw.strip() else "*"
        wildcard_sql = wildcard.replace("*", "%")

        terms: list[Any] = []
        if self._emulator is not None:
            terms = self._emulator.list_memory_terms(campaign_id, wildcard=wildcard_sql, limit=50)

        if not terms:
            fallback_rows = self._fallback_memory_state(campaign_id)
            distinct = sorted({str(row.get("term") or "") for row in fallback_rows if row.get("term")})
            terms = [term for term in distinct if term and fnmatch(term, wildcard)]

        lines = ["MEMORY_TERMS:"]
        if terms:
            for row in terms[:40]:
                if isinstance(row, dict):
                    category = str(row.get("category") or "").strip()
                    term = str(row.get("term") or "").strip()
                    label = f"{category} :: {term}" if category else term
                    lines.append(f"- {label}")
                else:
                    lines.append(f"- {row}")
        else:
            lines.append("- (none)")

        lines.extend(
            [
                "NEXT_ACTIONS:",
                '- {"tool_call": "memory_search", "category": "char:character-slug", "queries": ["keyword"]}',
                '- {"tool_call": "memory_store", "category": "char:character-slug", "term": "keyword", "memory": "fact"}',
            ]
        )
        return "\n".join(lines)

    def _tool_source_browse(self, campaign_id: str, payload: dict[str, Any]) -> str:
        doc_key_raw = payload.get("document_key") or payload.get("document")
        document_key = str(doc_key_raw).strip()[:120] if isinstance(doc_key_raw, str) else ""
        wildcard_raw = payload.get("wildcard")
        wildcard = (
            str(wildcard_raw).strip()[:120]
            if isinstance(wildcard_raw, str)
            else ""
        )
        wildcard_provided = bool(wildcard)
        wildcard = wildcard or "*"
        wildcard_meta = f"wildcard={wildcard!r}"
        if not wildcard_provided:
            wildcard_meta = "wildcard=(omitted)"
        limit = 60
        try:
            limit = max(1, min(120, int(payload.get("limit") or 60)))
        except Exception:
            pass

        rows: list[str] = []
        if self._emulator is not None:
            browse = getattr(self._emulator, "browse_source_keys", None)
            if callable(browse):
                rows = browse(
                    campaign_id,
                    document_key=document_key or None,
                    wildcard=wildcard,
                    limit=limit,
                )
            else:
                rows = []
        else:
            rows = []

        if rows:
            return (
                f"SOURCE_BROWSE_RESULT "
                f"(document_key={document_key or '*'!r}, "
                f"{wildcard_meta}, "
                f"showing {len(rows)}):\n"
                + "\n".join(str(row) for row in rows)
            )
        return (
            f"SOURCE_BROWSE_RESULT "
            f"(document_key={document_key or '*'!r}, "
            f"{wildcard_meta}): no entries found"
        )

    def _tool_name_generate(self, campaign_id: str, payload: dict[str, Any]) -> str:
        raw_origins = payload.get("origins") or []
        if isinstance(raw_origins, str):
            raw_origins = [raw_origins]
        origins = [
            str(o).strip().lower()
            for o in raw_origins
            if str(o or "").strip()
        ][:4]
        ng_gender = str(payload.get("gender") or "both").strip().lower()
        ng_count = 5
        try:
            ng_count = max(1, min(6, int(payload.get("count") or 5)))
        except (TypeError, ValueError):
            pass
        ng_context = str(payload.get("context") or "").strip()[:300]

        names: list[str] = []
        if self._emulator is not None:
            fetch = getattr(self._emulator, "_fetch_random_names", None)
            if callable(fetch):
                names = fetch(
                    origins=origins or None,
                    gender=ng_gender,
                    count=ng_count,
                )

        if names:
            result = (
                f"NAME_GENERATE_RESULT "
                f"(origins={origins or 'any'}, "
                f"gender={ng_gender}, "
                f"count={len(names)}):\n"
                + "\n".join(f"- {n}" for n in names)
                + "\n\nEvaluate these against your character concept"
            )
            if ng_context:
                result += f" ({ng_context})"
            result += (
                ". Pick the best fit, or call name_generate again "
                "with different origins/gender for more options."
            )
            return result
        return (
            f"NAME_GENERATE_RESULT "
            f"(origins={origins or 'any'}): "
            "no names returned — try broader origins "
            "or fewer filters."
        )

    def _tool_memory_turn(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> str:
        turn_id_raw = payload.get("turn_id")
        try:
            turn_id = int(turn_id_raw)
        except Exception:
            return "MEMORY_TURN: invalid turn_id"

        with self._session_factory() as session:
            turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .filter(Turn.id == turn_id)
                .first()
            )
            actor_row = None
            if actor_id:
                actor_row = (
                    session.query(Player)
                    .filter(Player.campaign_id == campaign_id)
                    .filter(Player.actor_id == actor_id)
                    .first()
                )
        if turn is None:
            return f"MEMORY_TURN: no turn found for turn_id={turn_id}"
        if actor_id and self._emulator is not None:
            actor_state = self._parse_json(actor_row.state_json, {}) if actor_row is not None else {}
            actor_slug = self._emulator._player_visibility_slug(actor_id)  # noqa: SLF001
            actor_location_key = self._emulator._room_key_from_player_state(actor_state)  # noqa: SLF001
            if not self._emulator._turn_visible_to_viewer(turn, actor_id, actor_slug or "", actor_location_key.lower()):  # noqa: SLF001
                return "MEMORY_TURN: that turn exists, but it is not visible to this player."

        content = str(turn.content or "")
        if len(content) > 12000:
            content = content[:11999].rstrip() + "..."
        return (
            "MEMORY_TURN_FULLTEXT:\n"
            f"turn_id={int(turn.id)}\n"
            f"kind={turn.kind}\n"
            f"actor_id={turn.actor_id}\n"
            f"created_at={turn.created_at.isoformat() if turn.created_at else None}\n"
            "content:\n"
            f"{content}\n"
        )

    def _tool_memory_store(self, campaign_id: str, payload: dict[str, Any]) -> str:
        category = payload.get("category")
        term = payload.get("term")
        memory = payload.get("memory")
        if not isinstance(category, str) or not category.strip() or not isinstance(memory, str) or not memory.strip():
            return "MEMORY_STORE_RESULT: invalid payload"

        if self._emulator is not None:
            ok, reason = self._emulator.store_memory(
                campaign_id,
                category=category.strip(),
                term=term.strip() if isinstance(term, str) and term.strip() else None,
                memory=memory.strip(),
            )
            if ok:
                return f"MEMORY_STORE_RESULT: stored via memory_port ({reason})"

        entries = self._fallback_memory_state(campaign_id)
        entry = {
            "id": len(entries) + 1,
            "category": category.strip(),
            "term": term.strip() if isinstance(term, str) and term.strip() else None,
            "memory": memory.strip(),
            "created_at": datetime.now(UTC).isoformat(),
            "source": "webui_fallback",
        }
        entries.append(entry)
        self._persist_fallback_memory_state(campaign_id, entries)
        return "MEMORY_STORE_RESULT: stored via fallback memory state"

    def _tool_sms_list(self, campaign_id: str, payload: dict[str, Any]) -> str:
        wildcard_raw = payload.get("wildcard")
        wildcard = wildcard_raw.strip() if isinstance(wildcard_raw, str) and wildcard_raw.strip() else "*"

        rows = self._emulator.list_sms_threads(campaign_id, wildcard=wildcard, limit=20) if self._emulator else []
        lines = ["SMS_LIST:"]
        if rows:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or row.get("thread") or "unknown")
                thread = str(row.get("thread") or "unknown")
                count = int(row.get("count") or 0)
                preview = str(row.get("last_preview") or "")
                lines.append(f"- {label} [{thread}] count={count} preview={preview}")
        else:
            lines.append("- (none)")

        lines.extend(
            [
                "NEXT_ACTIONS:",
                '- {"tool_call": "sms_read", "thread": "contact-slug", "limit": 20}',
                '- {"tool_call": "sms_write", "thread": "contact-slug", "from": "A", "to": "B", "message": "..."}',
                '- {"tool_call": "sms_schedule", "thread": "contact-slug", "from": "NPC", "to": "Player", "message": "...", "delay_seconds": 120}',
            ]
        )
        return "\n".join(lines)

    def _tool_sms_read(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> str:
        thread_raw = payload.get("thread")
        limit_raw = payload.get("limit", 20)
        thread = thread_raw.strip() if isinstance(thread_raw, str) and thread_raw.strip() else ""
        try:
            limit = max(1, min(40, int(limit_raw)))
        except Exception:
            limit = 20

        if not thread:
            return "SMS_READ_RESULT: invalid thread"

        canonical, matched, messages = (
            self._emulator.read_sms_thread(
                campaign_id,
                thread,
                limit=limit,
                viewer_actor_id=actor_id,
            )
            if self._emulator
            else (None, None, [])
        )
        lines = [f"SMS_READ_RESULT: thread={canonical or thread} matched={matched}"]
        if messages:
            for msg in messages[-limit:]:
                if not isinstance(msg, dict):
                    continue
                frm = str(msg.get("from") or "")
                to = str(msg.get("to") or "")
                text = str(msg.get("message") or "")
                try:
                    day = int(msg.get("day") or 0)
                except Exception:
                    day = 0
                try:
                    hour = max(0, min(23, int(msg.get("hour") or 0)))
                except Exception:
                    hour = 0
                try:
                    minute = max(0, min(59, int(msg.get("minute") or 0)))
                except Exception:
                    minute = 0
                lines.append(f"- Day {day} {hour:02d}:{minute:02d} {frm} -> {to}: {text}")
        else:
            lines.append("- (no messages)")
        return "\n".join(lines)

    def _tool_sms_write(self, campaign_id: str, payload: dict[str, Any]) -> str:
        thread_raw = payload.get("thread")
        sender_raw = payload.get("from", payload.get("sender"))
        recipient_raw = payload.get("to", payload.get("recipient"))
        message_raw = payload.get("message")

        thread = thread_raw.strip() if isinstance(thread_raw, str) and thread_raw.strip() else ""
        sender = sender_raw.strip() if isinstance(sender_raw, str) and sender_raw.strip() else ""
        recipient = recipient_raw.strip() if isinstance(recipient_raw, str) and recipient_raw.strip() else ""
        message = message_raw.strip() if isinstance(message_raw, str) and message_raw.strip() else ""

        if not thread or not sender or not recipient or not message:
            return "SMS_WRITE_RESULT: invalid payload"

        with self._session_factory() as session:
            latest_turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .order_by(Turn.id.desc())
                .first()
            )
            turn_id = int(latest_turn.id) if latest_turn is not None else 0

        if self._emulator is None:
            return "SMS_WRITE_RESULT: emulator unavailable"

        ok, reason = self._emulator.write_sms_thread(
            campaign_id,
            thread=thread,
            sender=sender,
            recipient=recipient,
            message=message,
            turn_id=turn_id,
        )
        return f"SMS_WRITE_RESULT: stored={bool(ok)} reason={reason} thread={thread}"

    def _tool_sms_schedule(self, campaign_id: str, payload: dict[str, Any]) -> str:
        thread_raw = payload.get("thread")
        sender_raw = payload.get("from", payload.get("sender"))
        recipient_raw = payload.get("to", payload.get("recipient"))
        message_raw = payload.get("message")
        delay_raw = payload.get("delay_seconds", payload.get("delay"))
        delay_minutes_raw = payload.get("delay_minutes")

        thread = thread_raw.strip() if isinstance(thread_raw, str) and thread_raw.strip() else ""
        sender = sender_raw.strip() if isinstance(sender_raw, str) and sender_raw.strip() else ""
        recipient = recipient_raw.strip() if isinstance(recipient_raw, str) and recipient_raw.strip() else ""
        message = message_raw.strip() if isinstance(message_raw, str) and message_raw.strip() else ""

        if not thread or not sender or not recipient or not message:
            return "SMS_SCHEDULE_RESULT: invalid payload"

        if delay_raw is None and delay_minutes_raw is not None:
            try:
                delay_raw = int(delay_minutes_raw) * 60
            except Exception:
                delay_raw = None
        try:
            delay_seconds = int(delay_raw)
        except Exception:
            delay_seconds = 90

        if self._emulator is None:
            return "SMS_SCHEDULE_RESULT: emulator unavailable"

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return "SMS_SCHEDULE_RESULT: campaign not found"
            latest_turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .order_by(Turn.id.desc())
                .first()
            )
        speed = self._emulator.get_speed_multiplier(campaign) if campaign is not None else 1.0
        if speed > 0:
            delay_seconds = int(delay_seconds / speed)
        delay_seconds = max(15, min(86_400, delay_seconds))
        turn_id = int(latest_turn.id) if latest_turn is not None else 0
        ok, reason, applied_delay = self._emulator.schedule_sms_thread_delivery(
            campaign_id,
            thread=thread,
            sender=sender,
            recipient=recipient,
            message=message,
            delay_seconds=delay_seconds,
            turn_id=turn_id,
        )
        return (
            "SMS_SCHEDULE_RESULT: "
            f"scheduled={bool(ok)} reason={reason} "
            f"thread={thread} delay_seconds={applied_delay if ok else delay_seconds} "
            "delivery_visibility=hidden_until_delivery interruptible=false"
        )

    def _tool_story_outline(self, campaign_id: str, payload: dict[str, Any]) -> str:
        chapter_key_raw = payload.get("chapter")
        chapter_key = chapter_key_raw.strip().lower() if isinstance(chapter_key_raw, str) and chapter_key_raw.strip() else None

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return "STORY_OUTLINE: campaign not found"
            state = self._parse_json(campaign.state_json, {})

        outline = state.get("story_outline") if isinstance(state, dict) else None
        if not isinstance(outline, dict):
            return "STORY_OUTLINE: none"

        if chapter_key:
            chapters = outline.get("chapters", [])
            if isinstance(chapters, list):
                for index, chapter in enumerate(chapters):
                    if not isinstance(chapter, dict):
                        continue
                    title = str(chapter.get("title") or "").strip()
                    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                    if chapter_key in {slug, str(index), str(index + 1)}:
                        data = {"index": index, "chapter": chapter}
                        return f"STORY_OUTLINE_CHAPTER:\n{json.dumps(data, ensure_ascii=True)}"
            return "STORY_OUTLINE_CHAPTER: not found"

        current = {
            "current_chapter": state.get("current_chapter"),
            "current_scene": state.get("current_scene"),
            "story_outline": outline,
        }
        text = json.dumps(current, ensure_ascii=True)
        if len(text) > 10000:
            text = text[:9999] + "..."
        return f"STORY_OUTLINE:\n{text}"

    def _tool_plot_plan(self, campaign_id: str, payload: dict[str, Any]) -> str:
        plans = payload.get("plans")
        if isinstance(plans, dict):
            plans = [plans]
        if not isinstance(plans, list):
            return "PLOT_PLAN_RESULT: invalid payload"

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return "PLOT_PLAN_RESULT: campaign not found"
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            threads = state.get("_plot_threads")
            if not isinstance(threads, dict):
                threads = {}
            updated = 0
            removed = 0
            for row in plans[:12]:
                if not isinstance(row, dict):
                    continue
                slug_raw = row.get("thread") or row.get("slug")
                slug = re.sub(r"[^a-z0-9]+", "-", str(slug_raw or "").strip().lower()).strip("-")[:80]
                if not slug:
                    continue
                if bool(row.get("remove") or row.get("delete") or row.get("_delete")):
                    if slug in threads:
                        threads.pop(slug, None)
                        removed += 1
                    continue
                item = dict(threads.get(slug) or {"thread": slug, "status": "active"})
                for field in ("setup", "intended_payoff", "resolution"):
                    if row.get(field) is not None:
                        item[field] = " ".join(str(row.get(field) or "").split())[:260]
                if row.get("target_turns") is not None:
                    try:
                        item["target_turns"] = max(1, min(250, int(row.get("target_turns"))))
                    except Exception:
                        item["target_turns"] = int(item.get("target_turns") or 8)
                deps = row.get("dependencies")
                if isinstance(deps, list):
                    clean = []
                    for dep in deps[:8]:
                        text = " ".join(str(dep or "").split())[:120]
                        if text:
                            clean.append(text)
                    item["dependencies"] = clean
                status = str(row.get("status") or item.get("status") or "active").strip().lower()
                if row.get("resolve"):
                    status = "resolved"
                if status not in {"active", "resolved"}:
                    status = "active"
                item["status"] = status
                threads[slug] = item
                updated += 1
            state["_plot_threads"] = threads
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        return f"PLOT_PLAN_RESULT: updated={updated} removed={removed} total={len(threads)}"

    def _tool_chapter_plan(self, campaign_id: str, payload: dict[str, Any]) -> str:
        action = str(payload.get("action") or "create").strip().lower()
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return "CHAPTER_PLAN_RESULT: campaign not found"
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            if bool(state.get("on_rails")):
                return "CHAPTER_PLAN_RESULT: ignored (on_rails enabled)"
            chapters = state.get("_chapter_plan")
            if not isinstance(chapters, dict):
                chapters = {}

            chapter_obj = payload.get("chapter")
            if isinstance(chapter_obj, dict):
                slug_raw = chapter_obj.get("slug") or chapter_obj.get("title")
            else:
                slug_raw = payload.get("chapter") or payload.get("slug")
            slug = re.sub(r"[^a-z0-9]+", "-", str(slug_raw or "").strip().lower()).strip("-")[:80]
            changed = 0

            if action in {"create", "update"}:
                if not slug:
                    return "CHAPTER_PLAN_RESULT: missing slug"
                row = dict(chapters.get(slug) or {"slug": slug, "status": "active"})
                if isinstance(chapter_obj, dict):
                    if chapter_obj.get("title") is not None:
                        row["title"] = " ".join(str(chapter_obj.get("title") or "").split())[:120]
                    if chapter_obj.get("summary") is not None:
                        row["summary"] = " ".join(str(chapter_obj.get("summary") or "").split())[:260]
                    scenes = chapter_obj.get("scenes")
                    if isinstance(scenes, list):
                        row["scenes"] = [
                            re.sub(r"[^a-z0-9]+", "-", str(scene or "").strip().lower()).strip("-")[:80]
                            for scene in scenes[:20]
                            if str(scene or "").strip()
                        ]
                    if chapter_obj.get("current_scene") is not None:
                        row["current_scene"] = re.sub(
                            r"[^a-z0-9]+", "-", str(chapter_obj.get("current_scene") or "").strip().lower()
                        ).strip("-")[:80]
                    if chapter_obj.get("active") is not None:
                        row["status"] = "active" if bool(chapter_obj.get("active")) else "resolved"
                chapters[slug] = row
                changed += 1
            elif action == "advance_scene":
                if slug and slug in chapters:
                    row = dict(chapters.get(slug) or {})
                    to_scene = payload.get("to_scene") or payload.get("scene")
                    scene_slug = re.sub(r"[^a-z0-9]+", "-", str(to_scene or "").strip().lower()).strip("-")[:80]
                    if scene_slug:
                        row["current_scene"] = scene_slug
                        scenes = row.get("scenes")
                        if not isinstance(scenes, list):
                            scenes = []
                        if scene_slug not in scenes:
                            scenes.append(scene_slug)
                        row["scenes"] = scenes[:20]
                    row["status"] = "active"
                    chapters[slug] = row
                    changed += 1
            elif action in {"resolve", "close"}:
                if slug and slug in chapters:
                    row = dict(chapters.get(slug) or {})
                    row["status"] = "resolved"
                    row["resolution"] = " ".join(str(payload.get("resolution") or "").split())[:260]
                    chapters[slug] = row
                    changed += 1

            state["_chapter_plan"] = chapters
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        return f"CHAPTER_PLAN_RESULT: updated={changed} total={len(chapters)}"

    def _tool_consequence_log(self, campaign_id: str, payload: dict[str, Any]) -> str:
        def _iter_rows(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, dict):
                return [value]
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            return []

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return "CONSEQUENCE_LOG_RESULT: campaign not found"
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            rows = state.get("_consequences")
            if not isinstance(rows, dict):
                rows = {}

            added = 0
            resolved = 0
            removed = 0
            for entry in _iter_rows(payload.get("add")):
                trigger = " ".join(str(entry.get("trigger") or "").split())[:240]
                consequence = " ".join(str(entry.get("consequence") or "").split())[:300]
                if not trigger or not consequence:
                    continue
                cid_raw = entry.get("id") or entry.get("slug") or trigger[:60]
                cid = re.sub(r"[^a-z0-9]+", "-", str(cid_raw or "").strip().lower()).strip("-")[:90]
                if not cid:
                    continue
                severity = str(entry.get("severity") or "low").strip().lower()
                if severity not in {"low", "moderate", "high", "critical"}:
                    severity = "low"
                row = dict(rows.get(cid) or {})
                row.update(
                    {
                        "id": cid,
                        "trigger": trigger,
                        "consequence": consequence,
                        "severity": severity,
                        "status": "active",
                        "resolution": str(row.get("resolution") or "")[:260],
                    }
                )
                rows[cid] = row
                added += 1

            for entry in _iter_rows(payload.get("resolve")):
                cid_raw = entry.get("id") or entry.get("slug") or entry.get("trigger")
                cid = re.sub(r"[^a-z0-9]+", "-", str(cid_raw or "").strip().lower()).strip("-")[:90]
                if not cid or cid not in rows:
                    continue
                row = dict(rows.get(cid) or {})
                row["status"] = "resolved"
                row["resolution"] = " ".join(str(entry.get("resolution") or row.get("resolution") or "resolved").split())[:260]
                rows[cid] = row
                resolved += 1

            remove_keys = payload.get("remove")
            if isinstance(remove_keys, list):
                for raw in remove_keys:
                    cid = re.sub(r"[^a-z0-9]+", "-", str(raw or "").strip().lower()).strip("-")[:90]
                    if cid and cid in rows:
                        rows.pop(cid, None)
                        removed += 1

            state["_consequences"] = rows
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        return f"CONSEQUENCE_LOG_RESULT: added={added} resolved={resolved} removed={removed} total={len(rows)}"

    def _execute_tool_call(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> str:
        tool = payload.get("tool_call")
        if not isinstance(tool, str):
            return "TOOL_ERROR: missing tool_call"
        name = tool.strip().lower()

        if name == "memory_search":
            return self._tool_memory_search(campaign_id, payload, actor_id=actor_id)
        if name == "memory_terms":
            return self._tool_memory_terms(campaign_id, payload)
        if name == "source_browse":
            return self._tool_source_browse(campaign_id, payload)
        if name == "name_generate":
            return self._tool_name_generate(campaign_id, payload)
        if name == "memory_turn":
            return self._tool_memory_turn(campaign_id, payload, actor_id=actor_id)
        if name == "memory_store":
            return self._tool_memory_store(campaign_id, payload)
        if name == "sms_list":
            return self._tool_sms_list(campaign_id, payload)
        if name == "sms_read":
            return self._tool_sms_read(campaign_id, payload, actor_id=actor_id)
        if name == "sms_write":
            return self._tool_sms_write(campaign_id, payload)
        if name == "sms_schedule":
            return self._tool_sms_schedule(campaign_id, payload)
        if name == "story_outline":
            return self._tool_story_outline(campaign_id, payload)
        if name == "plot_plan":
            return self._tool_plot_plan(campaign_id, payload)
        if name == "chapter_plan":
            return self._tool_chapter_plan(campaign_id, payload)
        if name == "consequence_log":
            return self._tool_consequence_log(campaign_id, payload)
        return f"TOOL_ERROR: unsupported tool_call '{name}'"

    async def _resolve_payload(
        self,
        campaign_id: str,
        actor_id: str,
        action_text: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        first = await self._completion.complete(
            system_prompt,
            user_prompt,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        payload = self._parse_model_payload(first)
        if payload is None:
            return None

        tool_history = ""
        used_tool_names: set[str] = set()
        seen_tool_signatures: set[str] = set()
        emulator = self._emulator
        if emulator is None:
            return None
        memory_lookup_enabled = "memory_lookup_enabled: true" in user_prompt.lower()
        if (
            not emulator._is_tool_call(payload)  # noqa: SLF001
            and memory_lookup_enabled
            and self._should_force_auto_memory_search(action_text)
        ):
            forced_queries = self._derive_auto_memory_queries(
                campaign_id,
                actor_id,
                action_text,
                limit=4,
            )
            if forced_queries:
                tool_payload = {"tool_call": "memory_search", "queries": forced_queries}
                tool_result = self._execute_tool_call(
                    campaign_id,
                    tool_payload,
                    actor_id=actor_id,
                )
                tool_history += f"\n\n{tool_result}"
                augmented_prompt = (
                    f"{user_prompt}\n"
                    f"{tool_history}\n\n"
                    "Use the memory results above. Return ONLY the final turn JSON object."
                )
                nxt = await self._completion.complete(
                    system_prompt,
                    augmented_prompt,
                    temperature=max(0.1, self._temperature - 0.2),
                    max_tokens=self._max_tokens,
                )
                payload = self._parse_model_payload(nxt)
                self._bump_auto_fix_counter(campaign_id, "forced_memory_search")
                if payload is None:
                    return None

        for _ in range(max(0, self._max_tool_rounds)):
            if not emulator._is_tool_call(payload):  # noqa: SLF001
                break
            tool_name = str(payload.get("tool_call") or "").strip().lower()
            if tool_name:
                used_tool_names.add(tool_name)
            if not memory_lookup_enabled and tool_name.startswith("memory_"):
                tool_history += (
                    "\n\nMEMORY_TOOLS_DISABLED: Long-term memory lookup is disabled for this turn "
                    "(early campaign context still fits prompt budget). "
                    "Do NOT call memory_* tools; continue with direct context or non-memory tools."
                )
                augmented_prompt = (
                    f"{user_prompt}\n"
                    f"{tool_history}\n\n"
                    "Return ONLY the final turn JSON object."
                )
                nxt = await self._completion.complete(
                    system_prompt,
                    augmented_prompt,
                    temperature=max(0.1, self._temperature - 0.2),
                    max_tokens=self._max_tokens,
                )
                payload = self._parse_model_payload(nxt)
                if payload is None:
                    return None
                continue
            tool_signature = self._tool_call_signature(payload)
            if tool_signature and tool_signature in seen_tool_signatures:
                tool_history += (
                    "\n\nTOOL_DEDUP_RESULT: duplicate tool_call payload already executed this turn; skipped. "
                    "Do NOT repeat identical tool calls. Use a distinct tool/payload or return final JSON (no tool_call)."
                )
                augmented_prompt = (
                    f"{user_prompt}\n"
                    f"{tool_history}\n\n"
                    "Return ONLY the final turn JSON object."
                )
                nxt = await self._completion.complete(
                    system_prompt,
                    augmented_prompt,
                    temperature=max(0.1, self._temperature - 0.2),
                    max_tokens=self._max_tokens,
                )
                payload = self._parse_model_payload(nxt)
                if payload is None:
                    return None
                continue
            if tool_signature:
                seen_tool_signatures.add(tool_signature)
            tool_result = self._execute_tool_call(
                campaign_id,
                payload,
                actor_id=actor_id,
            )
            tool_history += f"\n\n{tool_result}"
            augmented_prompt = (
                f"{user_prompt}\n"
                f"{tool_history}\n\n"
                "Use the tool results above. Return ONLY the final turn JSON object."
            )
            nxt = await self._completion.complete(
                system_prompt,
                augmented_prompt,
                temperature=max(0.1, self._temperature - 0.2),
                max_tokens=self._max_tokens,
            )
            payload = self._parse_model_payload(nxt)
            if payload is None:
                return None

        if emulator._is_tool_call(payload):  # noqa: SLF001
            return None
        if self._is_emptyish_payload(payload):
            self._bump_auto_fix_counter(campaign_id, "empty_response_repair_retry")
            repair_prompt = (
                f"{user_prompt}\n"
                f"{tool_history}\n\n"
                "OUTPUT_VALIDATION_FAILED: previous response was too empty.\n"
                "Return ONLY final JSON (no tool_call) with:\n"
                "- reasoning string grounded in evidence/context used\n"
                "- narration containing one concrete scene development\n"
                "- state_update object with game_time advanced\n"
                "- summary_update with durable consequence when applicable.\n"
            )
            repaired = await self._completion.complete(
                system_prompt,
                repair_prompt,
                temperature=max(0.1, self._temperature - 0.1),
                max_tokens=self._max_tokens,
            )
            repaired_payload = self._parse_model_payload(repaired)
            if (
                repaired_payload is not None
                and not emulator._is_tool_call(repaired_payload)  # noqa: SLF001
            ):
                payload = repaired_payload

        narration = str(payload.get("narration") or "")
        if (
            self._narration_has_explicit_clock_time(narration)
            and not self._action_requests_clock_time(action_text)
        ):
            self._bump_auto_fix_counter(campaign_id, "clock_drift_retry")
            clock_prompt = (
                f"{user_prompt}\n"
                f"{tool_history}\n\n"
                "OUTPUT_VALIDATION_FAILED: Do not invent explicit HH:MM clock timestamps unless asked.\n"
                "Use canonical CURRENT_GAME_TIME or omit exact times.\n"
                "Return ONLY final JSON (no tool_call) with reasoning.\n"
            )
            clock_retry = await self._completion.complete(
                system_prompt,
                clock_prompt,
                temperature=max(0.1, self._temperature - 0.1),
                max_tokens=self._max_tokens,
            )
            clock_payload = self._parse_model_payload(clock_retry)
            if (
                clock_payload is not None
                and not emulator._is_tool_call(clock_payload)  # noqa: SLF001
            ):
                payload = clock_payload

        planning_used = bool({"plot_plan", "chapter_plan", "consequence_log"} & used_tool_names)
        if not planning_used and self._looks_like_major_narrative_beat(payload):
            planning_prompt = (
                f"{user_prompt}\n"
                f"{tool_history}\n\n"
                "PLANNING_ENFORCEMENT: A major beat occurred.\n"
                "Return ONLY one planning tool call JSON now: plot_plan OR consequence_log "
                "(chapter_plan optional off-rails).\n"
                "No narration.\n"
            )
            planning_resp = await self._completion.complete(
                system_prompt,
                planning_prompt,
                temperature=max(0.1, self._temperature - 0.2),
                max_tokens=700,
            )
            planning_payload = self._parse_model_payload(planning_resp)
            if planning_payload is not None and emulator._is_tool_call(planning_payload):  # noqa: SLF001
                planning_name = str(planning_payload.get("tool_call") or "").strip().lower()
                if planning_name in {"plot_plan", "chapter_plan", "consequence_log"}:
                    _ = self._execute_tool_call(
                        campaign_id,
                        planning_payload,
                        actor_id=actor_id,
                    )
                    self._bump_auto_fix_counter(campaign_id, "forced_planning_tool")
        return payload

    async def complete_turn(self, context) -> LLMTurnOutput:
        emulator = self._emulator
        if emulator is None:
            return await self._fallback.complete_turn(context)

        with self._session_factory() as session:
            campaign = session.get(Campaign, context.campaign_id)
            if campaign is None:
                return await self._fallback.complete_turn(context)
            player = (
                session.query(Player)
                .filter(Player.campaign_id == context.campaign_id)
                .filter(Player.actor_id == context.actor_id)
                .first()
            )
            if player is None:
                return await self._fallback.complete_turn(context)
            turns = (
                session.query(Turn)
                .filter(Turn.campaign_id == context.campaign_id)
                .order_by(Turn.id.desc())
                .limit(emulator.MAX_RECENT_TURNS)
                .all()
            )
            turns.reverse()

        try:
            turn_visibility_default = self._session_visibility_default(
                context.session_id,
                campaign_id=context.campaign_id,
            )
            system_prompt, user_prompt = emulator.build_prompt(
                campaign,
                player,
                context.action,
                turns,
                turn_visibility_default=turn_visibility_default,
            )
            payload = await self._resolve_payload(
                context.campaign_id,
                context.actor_id,
                context.action,
                system_prompt,
                user_prompt,
            )
            if payload is None:
                return await self._fallback.complete_turn(context)
            return self._payload_to_output(payload)
        except Exception:
            return await self._fallback.complete_turn(context)


class TextGameEngineGateway(EngineGateway):
    @staticmethod
    def _parse_json_object(text: str, env_name: str) -> dict[str, Any]:
        raw = str(text or "").strip() or "{}"
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"{env_name} must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{env_name} must decode to a JSON object")
        return parsed

    def __init__(self, settings: Settings):
        self._settings = settings
        self._completion_mode = (settings.tge_completion_mode or "deterministic").strip().lower()

        engine = build_engine(settings.tge_database_url)
        create_schema(engine)
        self._session_factory = build_session_factory(engine)

        def _uow_factory():
            return SQLAlchemyUnitOfWork(self._session_factory)

        completion_port: CompletionPortProtocol | None = None
        if self._completion_mode == "openai":
            completion_port = OpenAICompatibleCompletionPort(
                base_url=settings.tge_llm_base_url,
                api_key=settings.tge_llm_api_key,
                model=settings.tge_llm_model,
                timeout_seconds=settings.tge_llm_timeout_seconds,
            )
            llm = EngineToolAwareLLM(
                session_factory=self._session_factory,
                completion_port=completion_port,
                temperature=settings.tge_llm_temperature,
                max_tokens=settings.tge_llm_max_tokens,
                turn_visibility_default_resolver=self._session_visibility_default,
            )
        elif self._completion_mode == "ollama":
            ollama_options = self._parse_json_object(
                settings.tge_ollama_options_json,
                "TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON",
            )
            completion_port = OllamaCompletionPort(
                base_url=settings.tge_llm_base_url,
                model=settings.tge_llm_model,
                timeout_seconds=settings.tge_llm_timeout_seconds,
                keep_alive=settings.tge_ollama_keep_alive,
                options=ollama_options,
            )
            llm = EngineToolAwareLLM(
                session_factory=self._session_factory,
                completion_port=completion_port,
                temperature=settings.tge_llm_temperature,
                max_tokens=settings.tge_llm_max_tokens,
                turn_visibility_default_resolver=self._session_visibility_default,
            )
        elif self._completion_mode == "deterministic":
            llm = EngineDeterministicLLM()
        else:
            raise ValueError(f"Unsupported tge completion mode: {self._completion_mode}")

        self._game_engine = GameEngine(uow_factory=_uow_factory, llm=llm)
        self._uow_factory = _uow_factory
        self._emulator = ZorkEmulator(
            game_engine=self._game_engine,
            session_factory=self._session_factory,
            completion_port=completion_port,
            map_completion_port=completion_port,
            memory_port=None,
            imdb_port=None,
            media_port=None,
        )
        self._completion_port = completion_port
        self._llm = llm
        self._reconfigure_lock = threading.Lock()
        self._probe_timeout_seconds = max(int(settings.tge_runtime_probe_timeout_seconds or 8), 1)
        if isinstance(llm, EngineToolAwareLLM):
            llm.bind_emulator(self._emulator)

    @property
    def completion_mode(self) -> str:
        return self._completion_mode

    @staticmethod
    def _pick(merged: dict[str, Any], key: str, fallback: Any) -> Any:
        val = merged.get(key)
        return val if val is not None else fallback

    def reconfigure_llm(self, merged: dict[str, Any]) -> dict[str, str]:
        with self._reconfigure_lock:
            mode = str(self._pick(merged, "completion_mode", self._completion_mode)).strip().lower()
            base_url = str(self._pick(merged, "base_url", self._settings.tge_llm_base_url)).strip()
            api_key = str(self._pick(merged, "api_key", self._settings.tge_llm_api_key)).strip()
            model = str(self._pick(merged, "model", self._settings.tge_llm_model)).strip()
            temperature = float(self._pick(merged, "temperature", self._settings.tge_llm_temperature))
            max_tokens = int(self._pick(merged, "max_tokens", self._settings.tge_llm_max_tokens))
            timeout_seconds = int(self._pick(merged, "timeout_seconds", self._settings.tge_llm_timeout_seconds))
            keep_alive = str(self._pick(merged, "keep_alive", self._settings.tge_ollama_keep_alive)).strip()
            ollama_options = merged.get("ollama_options")
            if ollama_options is None:
                ollama_options = self._parse_json_object(
                    self._settings.tge_ollama_options_json,
                    "ollama_options",
                )

            # -- build new completion port --
            new_port: CompletionPortProtocol | None = None
            if mode == "ollama":
                new_port = OllamaCompletionPort(
                    base_url=base_url,
                    model=model,
                    timeout_seconds=timeout_seconds,
                    keep_alive=keep_alive,
                    options=ollama_options if isinstance(ollama_options, dict) else {},
                )
            elif mode == "openai":
                new_port = OpenAICompatibleCompletionPort(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout_seconds=timeout_seconds,
                )
            elif mode == "deterministic":
                new_port = None
            else:
                raise ValueError(f"Unsupported completion mode: {mode}")

            # -- swap or rebuild the LLM instance --
            need_new_llm = False
            if mode == "deterministic" and not isinstance(self._llm, DeterministicLLM):
                need_new_llm = True
            elif mode != "deterministic" and not isinstance(self._llm, EngineToolAwareLLM):
                need_new_llm = True

            if need_new_llm:
                if mode == "deterministic":
                    new_llm = EngineDeterministicLLM()
                else:
                    new_llm = EngineToolAwareLLM(
                        session_factory=self._session_factory,
                        completion_port=new_port,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        turn_visibility_default_resolver=self._session_visibility_default,
                    )
                    new_llm.bind_emulator(self._emulator)
                self._llm = new_llm
                self._game_engine._llm = new_llm
            elif isinstance(self._llm, EngineToolAwareLLM):
                self._llm._completion = new_port
                self._llm._temperature = temperature
                self._llm._max_tokens = max_tokens

            self._emulator._completion_port = new_port
            self._emulator._map_completion_port = new_port
            self._completion_port = new_port
            self._completion_mode = mode

            self._settings.tge_completion_mode = mode
            self._settings.tge_llm_base_url = base_url
            self._settings.tge_llm_api_key = api_key
            self._settings.tge_llm_model = model
            self._settings.tge_llm_temperature = temperature
            self._settings.tge_llm_max_tokens = max_tokens
            self._settings.tge_llm_timeout_seconds = timeout_seconds
            self._settings.tge_ollama_keep_alive = keep_alive
            if isinstance(ollama_options, dict):
                self._settings.tge_ollama_options_json = json.dumps(ollama_options)

            return {
                "status": "ok",
                "completion_mode": mode,
                "model": model,
                "base_url": base_url,
                "note": "Settings applied and saved.",
            }

    async def runtime_checks(self, probe_llm: bool = False) -> dict:
        database_ok = True
        database_detail = "Connected."
        try:
            with self._session_factory() as session:
                _ = session.query(Campaign).limit(1).all()
        except Exception as exc:
            database_ok = False
            database_detail = f"{exc.__class__.__name__}: {exc}"

        llm_configured = self._completion_mode in {"openai", "ollama"} and self._completion_port is not None
        llm_probe_attempted = bool(probe_llm and llm_configured)
        llm_ok: bool | None = None
        if llm_configured:
            if llm_probe_attempted and self._completion_port is not None:
                llm_ok, llm_detail = await self._completion_port.probe(self._probe_timeout_seconds)
            else:
                llm_detail = "Configured. Probe not requested."
        else:
            llm_detail = "Not configured for deterministic mode."

        return {
            "backend": "tge",
            "completion_mode": self._completion_mode,
            "database": {"ok": database_ok, "detail": database_detail},
            "engine": {"ok": True, "detail": "ZorkEmulator initialized."},
            "llm": {
                "configured": llm_configured,
                "probe_attempted": llm_probe_attempted,
                "ok": llm_ok,
                "detail": llm_detail,
            },
        }

    @staticmethod
    def _to_summary(row: Campaign) -> CampaignSummary:
        return CampaignSummary(
            id=str(row.id),
            namespace=str(row.namespace),
            name=str(row.name),
            actor_id=str(row.created_by_actor_id or ""),
            created_at=row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at,
        )

    @staticmethod
    def _to_session_record(row: GameSession) -> dict:
        return {
            "id": row.id,
            "campaign_id": row.campaign_id,
            "surface": row.surface,
            "surface_key": row.surface_key,
            "surface_guild_id": row.surface_guild_id,
            "surface_channel_id": row.surface_channel_id,
            "surface_thread_id": row.surface_thread_id,
            "enabled": bool(row.enabled),
            "metadata": {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _session_visibility_default(
        self,
        session_id: str | None,
        *,
        campaign_id: str | None = None,
    ) -> str:
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            return "public"
        if campaign_id is not None:
            try:
                metadata = self._session_metadata(campaign_id, session_id_text)
            except KeyError:
                return "public"
        else:
            with self._session_factory() as session:
                row = session.get(GameSession, session_id_text)
                if row is None:
                    return "public"
                metadata = self._parse_json(row.metadata_json, {})
        if not isinstance(metadata, dict):
            return "public"
        default_value = str(
            metadata.get("turn_visibility_default") or metadata.get("scope") or ""
        ).strip().lower()
        if default_value == "local":
            return "local"
        if default_value == "public":
            return "public"
        if default_value in {"private", "limited"}:
            return "private"
        return "public"

    def _session_metadata(self, campaign_id: str, session_id: str | None) -> dict[str, Any]:
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            return {}
        with self._session_factory() as session:
            row = session.get(GameSession, session_id_text)
            if row is None or str(row.campaign_id) != str(campaign_id):
                raise KeyError(f"Unknown session: {session_id_text}")
            metadata = self._parse_json(row.metadata_json, {})
        return metadata if isinstance(metadata, dict) else {}

    async def validate_realtime_subscription(
        self,
        campaign_id: str,
        *,
        actor_id: str | None,
        session_id: str | None,
    ) -> None:
        session_id_text = str(session_id or "").strip() or None
        if not session_id_text:
            return
        actor_id_text = str(actor_id or "").strip() or None
        self._enforce_session_access(campaign_id, actor_id_text or "", session_id_text)

    def _enforce_session_access(self, campaign_id: str, actor_id: str, session_id: str | None) -> None:
        metadata = self._session_metadata(campaign_id, session_id)
        if not metadata:
            return
        scope = str(metadata.get("scope") or "").strip().lower()
        if scope not in {"private", "limited"}:
            return
        allowed_actor_ids: list[str] = []
        owner_actor_id = str(metadata.get("owner_actor_id") or "").strip()
        if owner_actor_id:
            allowed_actor_ids.append(owner_actor_id)
        raw_allowed = metadata.get("allowed_actor_ids")
        if isinstance(raw_allowed, list):
            for item in raw_allowed:
                text = str(item or "").strip()
                if text and text not in allowed_actor_ids:
                    allowed_actor_ids.append(text)
        if allowed_actor_ids and str(actor_id or "").strip() not in allowed_actor_ids:
            raise ValueError("This private window is not available to the selected actor.")

    def _player_slug_to_actor_ids(self, campaign_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        if self._emulator is None:
            return out
        with self._session_factory() as session:
            players = session.query(Player).filter(Player.campaign_id == campaign_id).all()
        for player in players:
            state = self._parse_json(player.state_json, {})
            if not isinstance(state, dict):
                continue
            actor_id = str(player.actor_id or "").strip()
            if not actor_id:
                continue
            stable_slug = self._emulator._player_visibility_slug(actor_id)  # noqa: SLF001
            if stable_slug and stable_slug not in out:
                out[stable_slug] = actor_id
            legacy_slug = self._emulator._player_slug_key(state.get("character_name"))  # noqa: SLF001
            if legacy_slug and legacy_slug not in out:
                out[legacy_slug] = actor_id
        return out

    def _resolve_turn_visibility(self, campaign_id: str, raw_visibility: Any) -> dict[str, Any]:
        visibility = dict(raw_visibility) if isinstance(raw_visibility, dict) else {}
        scope = str(visibility.get("scope") or "public").strip().lower()
        if scope not in {"public", "private", "limited", "local"}:
            scope = "public"
        resolved_actor_ids: list[str] = []
        raw_actor_ids = visibility.get("visible_actor_ids")
        if isinstance(raw_actor_ids, list):
            for item in raw_actor_ids:
                text = str(item or "").strip()
                if text and text not in resolved_actor_ids:
                    resolved_actor_ids.append(text)
        raw_player_slugs = visibility.get("visible_player_slugs")
        if isinstance(raw_player_slugs, list) and raw_player_slugs:
            slug_map = self._player_slug_to_actor_ids(campaign_id)
            for item in raw_player_slugs:
                slug = self._canonical_slug(str(item or ""))
                actor_id = slug_map.get(slug)
                if actor_id and actor_id not in resolved_actor_ids:
                    resolved_actor_ids.append(actor_id)
        visibility["scope"] = scope
        visibility["visible_actor_ids"] = resolved_actor_ids
        visibility["location_key"] = str(visibility.get("location_key") or "").strip() or None
        return visibility

    @staticmethod
    def _parse_json(text: str | None, default: Any) -> Any:
        if not text:
            return default
        try:
            return json.loads(text)
        except Exception:
            return default

    @staticmethod
    def _canonical_slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")

    def _resolve_roster_slug(self, existing: dict[str, Any], raw_slug: str) -> str:
        slug = str(raw_slug or "").strip()
        if not slug:
            return ""
        if slug in existing:
            return slug
        canonical = self._canonical_slug(slug)
        if not canonical:
            return slug
        for existing_slug in existing.keys():
            if self._canonical_slug(existing_slug) == canonical:
                return str(existing_slug)
        partials: list[str] = []
        for existing_slug in existing.keys():
            esc = self._canonical_slug(existing_slug)
            if esc.startswith(canonical) or canonical in esc:
                partials.append(str(existing_slug))
        if len(partials) == 1:
            return partials[0]
        return slug

    def _fallback_memory_state(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
        entries = state.get("_webui_curated_memory", []) if isinstance(state, dict) else []
        return entries if isinstance(entries, list) else []

    def _persist_fallback_memory_state(self, campaign_id: str, entries: list[dict[str, Any]]) -> None:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            state["_webui_curated_memory"] = entries[-500:]
            campaign.state_json = json.dumps(state, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()

    async def list_campaigns(self, namespace: str) -> list[CampaignSummary]:
        rows = self._emulator.list_campaigns(namespace)
        return [self._to_summary(row) for row in rows]

    async def list_sessions(self, campaign_id: str) -> list[dict]:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            rows = (
                session.query(GameSession)
                .filter(GameSession.campaign_id == campaign_id)
                .order_by(GameSession.created_at.asc())
                .all()
            )

        out = []
        for row in rows:
            record = self._to_session_record(row)
            meta = self._parse_json(row.metadata_json, {})
            record["metadata"] = meta if isinstance(meta, dict) else {}
            out.append(record)
        return out

    async def create_or_update_session(
        self,
        campaign_id: str,
        *,
        surface: str,
        surface_key: str,
        surface_guild_id: str | None = None,
        surface_channel_id: str | None = None,
        surface_thread_id: str | None = None,
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

            row = session.query(GameSession).filter(GameSession.surface_key == surface_key).first()
            now = datetime.now(UTC).replace(tzinfo=None)
            if row is None:
                row = GameSession(
                    campaign_id=campaign_id,
                    surface=surface,
                    surface_key=surface_key,
                    surface_guild_id=surface_guild_id,
                    surface_channel_id=surface_channel_id,
                    surface_thread_id=surface_thread_id,
                    enabled=bool(enabled),
                    metadata_json=json.dumps(metadata if isinstance(metadata, dict) else {}, ensure_ascii=True),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                record = self._to_session_record(row)
                record["metadata"] = self._parse_json(row.metadata_json, {})
                return record

            if row.campaign_id != campaign_id:
                raise ValueError(f"surface_key already belongs to campaign {row.campaign_id}")

            row.surface = surface
            row.surface_guild_id = surface_guild_id
            row.surface_channel_id = surface_channel_id
            row.surface_thread_id = surface_thread_id
            row.enabled = bool(enabled)
            if isinstance(metadata, dict):
                row.metadata_json = json.dumps(metadata, ensure_ascii=True)
            row.updated_at = now
            session.commit()
            session.refresh(row)
            record = self._to_session_record(row)
            record["metadata"] = self._parse_json(row.metadata_json, {})
            return record

    async def update_session(
        self,
        campaign_id: str,
        session_id: str,
        *,
        enabled: bool | None = None,
        metadata: dict | None = None,
    ) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            row = session.get(GameSession, session_id)
            if row is None or row.campaign_id != campaign_id:
                raise KeyError(f"Unknown session: {session_id}")

            if enabled is not None:
                row.enabled = bool(enabled)
            if metadata is not None:
                row.metadata_json = json.dumps(metadata if isinstance(metadata, dict) else {}, ensure_ascii=True)
            row.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
            session.refresh(row)
            record = self._to_session_record(row)
            record["metadata"] = self._parse_json(row.metadata_json, {})
            return record

    async def create_campaign(self, namespace: str, name: str, actor_id: str) -> CampaignSummary:
        actor = self._emulator.get_or_create_actor(actor_id, display_name=actor_id)
        campaign = self._emulator.get_or_create_campaign(namespace, name, created_by_actor_id=actor.id)
        self._emulator.get_or_create_player(campaign.id, actor.id)

        with self._session_factory() as session:
            row = session.get(Campaign, campaign.id)
            if row is not None:
                state = self._parse_json(row.state_json, {})
                if not isinstance(state, dict):
                    state = {}
                if "game_time" not in state:
                    state["game_time"] = {
                        "day": 1,
                        "hour": 8,
                        "minute": 0,
                        "period": "morning",
                        "date_label": "Day 1, Morning",
                    }
                    state["calendar"] = []
                    row.state_json = json.dumps(state, ensure_ascii=True)
                    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
                    session.commit()
                return self._to_summary(row)

        raise KeyError(f"Unknown campaign: {campaign.id}")

    def _pre_turn_setup(
        self,
        campaign_id: str,
        request: TurnRequest,
    ) -> tuple[int, str | None]:
        """Validate campaign, resolve session, and capture XP before the turn.

        Returns ``(xp_before, session_id)``.
        """
        xp_before = 0
        session_id = str(request.session_id or "").strip() or None
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player_before = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == request.actor_id)
                .first()
            )
            if player_before is not None:
                xp_before = int(player_before.xp or 0)

        self._enforce_session_access(campaign_id, request.actor_id, session_id)
        self._emulator.get_or_create_player(campaign_id, request.actor_id)
        return xp_before, session_id

    def _build_turn_result(
        self,
        campaign_id: str,
        request: TurnRequest,
        narration: str,
        notices: list[str],
        xp_before: int,
        session_id: str | None,
    ) -> TurnResult:
        """Post-turn DB queries to assemble the complete TurnResult."""
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == request.actor_id)
                .first()
            )
            campaign_state = self._parse_json(campaign.state_json, {})
            player_state = self._parse_json(player.state_json if player is not None else "{}", {})
            xp_after = int(player.xp or 0) if player is not None else xp_before
            narrator_turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .filter(Turn.kind == "narrator")
                .filter(Turn.actor_id == request.actor_id)
                .filter(Turn.session_id == session_id if session_id is not None else Turn.session_id.is_(None))
                .order_by(Turn.id.desc())
                .first()
            )

        state_update = {}
        if isinstance(campaign_state, dict) and isinstance(campaign_state.get("game_time"), dict):
            state_update["game_time"] = campaign_state["game_time"]

        player_state_update = {}
        if isinstance(player_state, dict):
            for key in ["room_title", "room_summary", "room_description", "location", "exits"]:
                if key in player_state:
                    player_state_update[key] = player_state.get(key)

        summary_update = None
        if isinstance(campaign.summary, str) and campaign.summary.strip():
            lines = [line.strip() for line in campaign.summary.splitlines() if line.strip()]
            if lines:
                summary_update = lines[-1]

        turn_visibility: dict[str, Any] = {}
        reasoning: str | None = None
        if narrator_turn is not None:
            turn_meta = self._parse_json(narrator_turn.meta_json, {})
            if isinstance(turn_meta, dict):
                turn_visibility = self._resolve_turn_visibility(campaign_id, turn_meta.get("visibility"))
                raw_reasoning = turn_meta.get("reasoning")
                if isinstance(raw_reasoning, str) and raw_reasoning.strip():
                    reasoning = raw_reasoning.strip()

        # Extract latest scene image prompt from outbox (if generated this turn)
        image_prompt: str | None = None
        if narrator_turn is not None:
            with self._session_factory() as session:
                latest_scene = (
                    session.query(OutboxEvent)
                    .filter(OutboxEvent.campaign_id == campaign_id)
                    .filter(OutboxEvent.event_type == "scene_image_requested")
                    .order_by(OutboxEvent.created_at.desc())
                    .first()
                )
                if latest_scene is not None:
                    scene_payload = self._parse_json(latest_scene.payload_json, {})
                    if isinstance(scene_payload, dict) and scene_payload.get("turn_id") == narrator_turn.id:
                        raw_prompt = scene_payload.get("scene_image_prompt")
                        if isinstance(raw_prompt, str) and raw_prompt.strip():
                            image_prompt = raw_prompt.strip()

        # Extract dice check result from campaign state
        dice_result: dict | None = None
        if isinstance(campaign_state, dict):
            raw_dice = campaign_state.get("_last_dice_check")
            if isinstance(raw_dice, dict) and raw_dice.get("attribute"):
                dice_result = raw_dice

        # Extract active puzzle / minigame from campaign state
        active_puzzle: dict | None = None
        active_minigame: dict | None = None
        if isinstance(campaign_state, dict):
            raw_puzzle = campaign_state.get("_active_puzzle")
            if isinstance(raw_puzzle, dict) and raw_puzzle.get("puzzle_type"):
                active_puzzle = raw_puzzle
            raw_minigame = campaign_state.get("_active_minigame")
            if isinstance(raw_minigame, dict) and raw_minigame.get("game_type"):
                active_minigame = raw_minigame

        return TurnResult(
            actor_id=request.actor_id,
            session_id=session_id,
            narration=str(narration),
            state_update=state_update,
            player_state_update=player_state_update,
            summary_update=summary_update,
            xp_awarded=max(xp_after - xp_before, 0),
            image_prompt=image_prompt,
            reasoning=reasoning,
            dice_result=dice_result,
            turn_visibility=turn_visibility,
            notices=notices,
            active_puzzle=active_puzzle,
            active_minigame=active_minigame,
        )

    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult:
        xp_before, session_id = self._pre_turn_setup(campaign_id, request)
        narration = await self._emulator.play_action(
            campaign_id=campaign_id,
            actor_id=request.actor_id,
            action=request.action,
            session_id=session_id,
            manage_claim=True,
        )
        notices = self._emulator.pop_turn_ephemeral_notices(
            campaign_id,
            request.actor_id,
            session_id,
        )

        if narration is None:
            narration = "The world shifts, but nothing clear emerges."

        return self._build_turn_result(campaign_id, request, narration, notices, xp_before, session_id)

    async def submit_turn_stream(self, campaign_id: str, request: TurnRequest):
        """Async generator yielding SSE event dicts for streaming turn resolution."""
        yield {"event": "phase", "data": {"phase": "starting"}}

        xp_before, session_id = self._pre_turn_setup(campaign_id, request)

        yield {"event": "phase", "data": {"phase": "generating"}}

        progress_queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = None

        async def on_progress(phase, detail=None):
            await progress_queue.put({"event": "phase", "data": {"phase": phase, **(detail or {})}})

        result_box: dict = {"narration": None, "error": None}

        async def _run():
            try:
                result_box["narration"] = await self._emulator.play_action(
                    campaign_id=campaign_id,
                    actor_id=request.actor_id,
                    action=request.action,
                    session_id=session_id,
                    manage_claim=True,
                    progress=on_progress,
                )
            except Exception as exc:
                result_box["error"] = exc
            finally:
                await progress_queue.put(_SENTINEL)

        task = asyncio.create_task(_run())

        try:
            while True:
                event = await progress_queue.get()
                if event is _SENTINEL:
                    break
                yield event
        except (GeneratorExit, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

        if result_box["error"] is not None:
            raise result_box["error"]

        narration = result_box["narration"]
        notices = self._emulator.pop_turn_ephemeral_notices(
            campaign_id,
            request.actor_id,
            session_id,
        )

        if narration is None:
            narration = "The world shifts, but nothing clear emerges."

        # Stream narration in chunks for typewriter effect
        yield {"event": "phase", "data": {"phase": "narrating"}}
        CHUNK = 4  # characters per token event
        for i in range(0, len(narration), CHUNK):
            yield {"event": "token", "data": {"text": narration[i : i + CHUNK]}}

        # Build complete result (DB queries)
        result = self._build_turn_result(campaign_id, request, narration, notices, xp_before, session_id)
        yield {"event": "complete", "data": result.model_dump()}

    async def campaign_export(
        self,
        campaign_id: str,
        *,
        export_type: str = "full",
        raw_format: str = "jsonl",
    ) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        files = await self._emulator.campaign_export(
            campaign_id,
            export_type=export_type,
            raw_format=raw_format,
        )
        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "export_type": str(export_type or "full").strip().lower() or "full",
            "raw_format": str(raw_format or "jsonl").strip().lower() or "jsonl",
            "files": [
                {"filename": filename, "content": content}
                for filename, content in files.items()
            ],
        }

    async def get_map(self, campaign_id: str, actor_id: str) -> str:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

        generated = await self._emulator.generate_map(campaign_id, actor_id=actor_id)
        if generated and generated not in {"Map unavailable.", "Map is foggy. Try again."}:
            return generated

        with self._session_factory() as session:
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                return "Map unavailable."
            pstate = self._parse_json(player.state_json, {})
            title = str(pstate.get("room_title") or pstate.get("location") or "Unknown Room")

            others = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id != actor_id)
                .order_by(Player.actor_id.asc())
                .all()
            )

        lines = [
            "+-----------------------------+",
            f"| {title[:27]:<27} |",
            "|              @              |",
            "+-----------------------------+",
            "",
            "Legend:",
            f"  @ {actor_id}",
        ]
        marker_ord = ord("A")
        for other in others[:8]:
            marker = chr(marker_ord)
            marker_ord += 1
            ostate = self._parse_json(other.state_json, {})
            oloc = str(ostate.get("room_title") or ostate.get("location") or "unknown")
            lines.append(f"  {marker} {other.actor_id} - {oloc}")
        return "\n".join(lines)

    async def get_timers(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            rows = (
                session.query(Timer)
                .filter(Timer.campaign_id == campaign_id)
                .order_by(Timer.created_at.desc())
                .limit(50)
                .all()
            )

        timers = []
        active_count = 0
        for row in rows:
            status = str(row.status or "")
            if status in {"scheduled_unbound", "scheduled_bound"}:
                active_count += 1
            timers.append(
                {
                    "id": row.id,
                    "status": status,
                    "event_text": row.event_text,
                    "interruptible": bool(row.interruptible),
                    "interrupt_action": row.interrupt_action,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                    "fired_at": row.fired_at.isoformat() if row.fired_at else None,
                    "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "meta": self._parse_json(row.meta_json, {}),
                }
            )

        return {
            "active_count": active_count,
            "timers": timers,
        }

    async def get_calendar(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        events = state.get("calendar", [])
        if not isinstance(events, list):
            events = []
        shaped_events: list[dict[str, Any]] = []
        for raw in events:
            if isinstance(raw, dict):
                event = dict(raw)
                target_players = event.get("target_players")
                has_targets = isinstance(target_players, list) and any(
                    str(item or "").strip() for item in target_players
                )
                event.setdefault("scope", "targeted" if has_targets else "global")
                shaped_events.append(event)
            else:
                shaped_events.append({"value": raw, "scope": "global"})

        return {
            "game_time": state.get("game_time", {}),
            "events": shaped_events,
        }

    async def get_roster(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            players = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .order_by(Player.actor_id.asc())
                .all()
            )
            state = self._parse_json(campaign.state_json, {})
            characters = self._parse_json(campaign.characters_json, {})

        rows: list[dict[str, Any]] = []
        for player in players:
            pstate = self._parse_json(player.state_json, {})
            rows.append(
                {
                    "slug": player.actor_id,
                    "name": pstate.get("character_name") or player.actor_id,
                    "location": pstate.get("location") or pstate.get("room_title") or "unknown",
                    "status": pstate.get("current_status") or "active",
                    "player": True,
                }
            )
        if isinstance(characters, dict):
            for slug, payload in characters.items():
                if not isinstance(payload, dict):
                    continue
                if payload.get("remove") is True:
                    continue
                rows.append(
                    {
                        "slug": slug,
                        "name": payload.get("name") or slug,
                        "location": payload.get("location") or "unknown",
                        "status": payload.get("current_status") or "active",
                        "player": False,
                    }
                )

        currently_attentive = state.get("currently_attentive_players", []) if isinstance(state, dict) else []
        return {
            "characters": rows,
            "currently_attentive_players": currently_attentive,
        }

    async def upsert_roster_character(
        self,
        campaign_id: str,
        *,
        slug: str,
        name: str | None = None,
        location: str | None = None,
        status: str | None = None,
        player: bool = False,
        fields: dict | None = None,
    ) -> dict:
        slug_clean = str(slug or "").strip()
        if not slug_clean:
            raise ValueError("slug is required")
        fields_dict = fields if isinstance(fields, dict) else {}

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

            player_row = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == slug_clean)
                .first()
            )
            if bool(player) or player_row is not None:
                if player_row is None:
                    raise KeyError(f"Unknown player in campaign: {slug_clean}")
                pstate = self._parse_json(player_row.state_json, {})
                if not isinstance(pstate, dict):
                    pstate = {}
                if isinstance(name, str) and name.strip():
                    pstate["character_name"] = name.strip()
                if isinstance(location, str) and location.strip():
                    pstate["location"] = location.strip()
                if isinstance(status, str) and status.strip():
                    pstate["current_status"] = status.strip()
                for key, value in fields_dict.items():
                    if key in {"name", "slug"}:
                        continue
                    pstate[key] = value
                player_row.state_json = json.dumps(pstate, ensure_ascii=True)
                player_row.updated_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()
                return {
                    "ok": True,
                    "character": {
                        "slug": player_row.actor_id,
                        "name": pstate.get("character_name") or player_row.actor_id,
                        "location": pstate.get("location") or pstate.get("room_title") or "unknown",
                        "status": pstate.get("current_status") or "active",
                        "player": True,
                    },
                }

            characters = self._parse_json(campaign.characters_json, {})
            if not isinstance(characters, dict):
                characters = {}
            resolved_slug = self._resolve_roster_slug(characters, slug_clean)
            row = characters.get(resolved_slug, {})
            if not isinstance(row, dict):
                row = {}
            updated = dict(row)
            updated.update(fields_dict)
            if isinstance(name, str) and name.strip():
                updated["name"] = name.strip()
            if isinstance(location, str) and location.strip():
                updated["location"] = location.strip()
            if isinstance(status, str) and status.strip():
                updated["current_status"] = status.strip()
            updated.pop("remove", None)
            characters[resolved_slug] = updated

            campaign.characters_json = json.dumps(characters, ensure_ascii=True)
            campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
            return {
                "ok": True,
                "character": {
                    "slug": resolved_slug,
                    "name": updated.get("name") or resolved_slug,
                    "location": updated.get("location") or "unknown",
                    "status": updated.get("current_status") or "active",
                    "player": False,
                },
            }

    async def remove_roster_character(self, campaign_id: str, slug: str, *, player: bool = False) -> dict:
        slug_clean = str(slug or "").strip()
        if not slug_clean:
            raise ValueError("slug is required")

        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            if slug_clean == str(campaign.created_by_actor_id or ""):
                return {"ok": False, "removed": False, "slug": slug_clean, "message": "Cannot remove lead actor."}

            player_row = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == slug_clean)
                .first()
            )
            if bool(player):
                if player_row is None:
                    return {"ok": False, "removed": False, "slug": slug_clean, "player": True}
                session.delete(player_row)
                campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()
                return {"ok": True, "removed": True, "slug": slug_clean, "player": True}

            characters = self._parse_json(campaign.characters_json, {})
            if not isinstance(characters, dict):
                characters = {}
            resolved_slug = self._resolve_roster_slug(characters, slug_clean)
            removed = characters.pop(resolved_slug, None)
            if removed is not None:
                campaign.characters_json = json.dumps(characters, ensure_ascii=True)
                campaign.updated_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()
                return {"ok": True, "removed": True, "slug": resolved_slug, "player": False}

            if player_row is not None:
                return {
                    "ok": False,
                    "removed": False,
                    "slug": slug_clean,
                    "player": True,
                    "message": "Target is a player. Set player=true to remove player entries.",
                }
            return {"ok": False, "removed": False, "slug": slug_clean, "player": False}

    async def get_player_state(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")

        state = self._parse_json(player.state_json, {})
        if not isinstance(state, dict):
            state = {}
        # Normalise character_name if it was stored as a dict
        _cn = state.get("character_name")
        if isinstance(_cn, dict):
            state["character_name"] = str(_cn.get("name") or "").strip() or str(_cn)
        inventory = state.get("inventory", [])
        if not isinstance(inventory, list):
            inventory = []
        return {
            "actor_id": player.actor_id,
            "level": int(player.level or 1),
            "xp": int(player.xp or 0),
            "last_active_at": player.last_active_at.isoformat() if player.last_active_at else None,
            "state": state,
            "inventory": inventory,
        }

    async def get_media(self, campaign_id: str, actor_id: str | None = None) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

            players_query = session.query(Player).filter(Player.campaign_id == campaign_id)
            if actor_id:
                players_query = players_query.filter(Player.actor_id == actor_id)
            players = players_query.order_by(Player.actor_id.asc()).all()
            if actor_id and not players:
                raise KeyError(f"Unknown player in campaign: {actor_id}")

            media_ref_query = session.query(MediaRef).filter(MediaRef.campaign_id == campaign_id)
            if players:
                player_ids = [player.id for player in players]
                media_refs = (
                    media_ref_query
                    .filter((MediaRef.player_id.is_(None)) | (MediaRef.player_id.in_(player_ids)))
                    .order_by(MediaRef.created_at.desc())
                    .limit(80)
                    .all()
                )
            else:
                media_refs = media_ref_query.order_by(MediaRef.created_at.desc()).limit(80).all()

            outbox_query = (
                session.query(OutboxEvent)
                .filter(OutboxEvent.campaign_id == campaign_id)
                .filter(OutboxEvent.event_type == "scene_image_requested")
                .order_by(OutboxEvent.created_at.desc())
                .limit(60)
            )
            scene_requests = outbox_query.all()

        campaign_state = self._parse_json(campaign.state_json, {})
        room_scene_images = {}
        if isinstance(campaign_state, dict):
            row = campaign_state.get("room_scene_images", {})
            if isinstance(row, dict):
                room_scene_images = row

        scene_images: list[dict[str, Any]] = []
        avatar_images: list[dict[str, Any]] = []
        for ref in media_refs:
            payload = {
                "id": ref.id,
                "ref_type": ref.ref_type,
                "player_id": ref.player_id,
                "room_key": ref.room_key,
                "url": ref.url,
                "prompt": ref.prompt,
                "metadata": self._parse_json(ref.metadata_json, {}),
                "created_at": ref.created_at.isoformat() if ref.created_at else None,
            }
            ref_type = str(ref.ref_type or "").lower()
            if "avatar" in ref_type:
                avatar_images.append(payload)
            else:
                scene_images.append(payload)

        pending_scene_requests: list[dict[str, Any]] = []
        for event in scene_requests:
            payload = self._parse_json(event.payload_json, {})
            if not isinstance(payload, dict):
                payload = {}
            pending_scene_requests.append(
                {
                    "id": event.id,
                    "status": event.status,
                    "attempts": int(event.attempts or 0),
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                    "next_attempt_at": event.next_attempt_at.isoformat() if event.next_attempt_at else None,
                    "turn_id": payload.get("turn_id"),
                    "actor_id": payload.get("actor_id"),
                    "room_key": payload.get("room_key"),
                    "scene_image_prompt": payload.get("scene_image_prompt"),
                }
            )

        player_avatar_state: list[dict[str, Any]] = []
        player_lookup = {player.id: player.actor_id for player in players}
        for player in players:
            state = self._parse_json(player.state_json, {})
            if not isinstance(state, dict):
                state = {}
            player_avatar_state.append(
                {
                    "actor_id": player.actor_id,
                    "avatar_url": state.get("avatar_url"),
                    "pending_avatar_url": state.get("pending_avatar_url"),
                    "pending_avatar_prompt": state.get("pending_avatar_prompt"),
                    "pending_avatar_generated_at": state.get("pending_avatar_generated_at"),
                }
            )

        for row in scene_images:
            player_id = row.get("player_id")
            if player_id in player_lookup:
                row["actor_id"] = player_lookup[player_id]
        for row in avatar_images:
            player_id = row.get("player_id")
            if player_id in player_lookup:
                row["actor_id"] = player_lookup[player_id]

        normalized_room_scene_images = []
        for room_key, value in room_scene_images.items():
            if not isinstance(value, dict):
                continue
            normalized_room_scene_images.append(
                {
                    "room_key": room_key,
                    "url": value.get("url"),
                    "prompt": value.get("prompt"),
                    "updated_at": value.get("updated_at"),
                }
            )

        latest_prompt = pending_scene_requests[0]["scene_image_prompt"] if pending_scene_requests else None
        return {
            "scene": {
                "latest_prompt": latest_prompt,
                "request_count": len(pending_scene_requests),
                "requests": pending_scene_requests,
                "images": scene_images[:40],
                "room_scene_images": normalized_room_scene_images[:40],
            },
            "avatars": {
                "images": avatar_images[:40],
                "player_state": player_avatar_state,
            },
        }

    async def record_pending_avatar(self, campaign_id: str, actor_id: str, image_url: str, prompt: str | None = None) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")

        ok = self._emulator.record_pending_avatar_image_for_campaign(
            campaign_id, actor_id, image_url, avatar_prompt=prompt,
        )
        return {
            "ok": bool(ok),
            "message": "Pending avatar recorded." if ok else "Failed to record pending avatar.",
            "actor_id": actor_id,
        }

    async def accept_pending_avatar(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")

        ok, message = self._emulator.accept_pending_avatar(campaign_id, actor_id)
        player_state = await self.get_player_state(campaign_id, actor_id)
        return {
            "ok": bool(ok),
            "message": message,
            "actor_id": actor_id,
            "player_state": player_state,
        }

    async def decline_pending_avatar(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")

        ok, message = self._emulator.decline_pending_avatar(campaign_id, actor_id)
        player_state = await self.get_player_state(campaign_id, actor_id)
        return {
            "ok": bool(ok),
            "message": message,
            "actor_id": actor_id,
            "player_state": player_state,
        }

    async def memory_search(self, campaign_id: str, queries: list[str], category: str | None) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

        terms = [q.strip() for q in queries if q and q.strip()]
        if not terms:
            return {"hits": []}

        hits: list[dict[str, Any]] = []
        for query in terms:
            curated = self._emulator.search_curated_memories(query=query, campaign_id=campaign_id, category=category, top_k=8)
            for term, memory, score in curated:
                hits.append(
                    {
                        "source": "curated",
                        "query": query,
                        "term": term,
                        "memory": memory,
                        "score": score,
                    }
                )

        if not hits:
            fallback = self._fallback_memory_state(campaign_id)
            for entry in fallback:
                if category and entry.get("category") != category:
                    continue
                hay = str(entry.get("memory") or "").lower()
                if any(q.lower() in hay for q in terms):
                    hits.append(entry)

        return {"hits": hits[:20]}

    async def memory_terms(self, campaign_id: str, wildcard: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

        wildcard_value = wildcard or "%"
        wildcard_sql = wildcard_value.replace("*", "%")
        terms = self._emulator.list_memory_terms(campaign_id, wildcard=wildcard_sql, limit=200)
        if terms:
            if wildcard_value and wildcard_value not in {"*", "%"}:
                filtered = []
                for row in terms:
                    if isinstance(row, dict):
                        probe = str(row.get("term") or row.get("category") or "")
                    else:
                        probe = str(row)
                    if fnmatch(probe, wildcard_value):
                        filtered.append(row)
            else:
                filtered = terms
            return {"terms": filtered}

        fallback = self._fallback_memory_state(campaign_id)
        values = sorted({str(entry.get("term") or "") for entry in fallback if entry.get("term")})
        if wildcard and wildcard not in {"*", "%"}:
            values = [value for value in values if fnmatch(value, wildcard)]
        return {"terms": values}

    async def memory_turn(self, campaign_id: str, turn_id: int) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .filter(Turn.id == turn_id)
                .first()
            )
            if turn is None:
                return {"turn": None}
            return {
                "turn": {
                    "id": int(turn.id),
                    "kind": turn.kind,
                    "actor_id": turn.actor_id,
                    "content": turn.content,
                    "meta": self._parse_json(turn.meta_json, {}),
                    "created_at": turn.created_at.isoformat() if turn.created_at else None,
                }
            }

    async def memory_store(self, campaign_id: str, payload: MemoryStoreRequest) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")

        ok, reason = self._emulator.store_memory(
            campaign_id,
            category=payload.category,
            term=payload.term,
            memory=payload.memory,
        )
        if ok:
            return {"stored": True, "provider": "memory_port", "reason": reason}

        entries = self._fallback_memory_state(campaign_id)
        entry = {
            "id": len(entries) + 1,
            "category": payload.category,
            "term": payload.term,
            "memory": payload.memory,
            "created_at": datetime.now(UTC).isoformat(),
            "source": "webui_fallback",
        }
        entries.append(entry)
        self._persist_fallback_memory_state(campaign_id, entries)
        return {"stored": True, "provider": "webui_fallback", "entry": entry}

    async def sms_list(self, campaign_id: str, wildcard: str) -> dict:
        rows = self._emulator.list_sms_threads(campaign_id, wildcard=wildcard or "*", limit=200)
        return {"threads": rows}

    async def sms_read(self, campaign_id: str, thread: str, limit: int, viewer_actor_id: str | None = None) -> dict:
        canonical, matched, messages = self._emulator.read_sms_thread(campaign_id, thread, limit=limit, viewer_actor_id=viewer_actor_id)
        return {
            "thread": canonical or thread,
            "matched": matched,
            "messages": messages,
        }

    async def sms_write(self, campaign_id: str, thread: str, sender: str, recipient: str, message: str) -> dict:
        with self._session_factory() as session:
            latest_turn = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .order_by(Turn.id.desc())
                .first()
            )
            turn_id = int(latest_turn.id) if latest_turn is not None else 0

        ok, reason = self._emulator.write_sms_thread(
            campaign_id,
            thread=thread,
            sender=sender,
            recipient=recipient,
            message=message,
            turn_id=turn_id,
        )
        return {
            "stored": bool(ok),
            "thread": thread,
            "reason": reason,
            "message": {
                "sender": sender,
                "recipient": recipient,
                "message": message,
                "created_at": datetime.now(UTC).isoformat(),
            },
        }

    async def debug_snapshot(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            players = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .order_by(Player.actor_id.asc())
                .all()
            )
            turns = (
                session.query(Turn)
                .filter(Turn.campaign_id == campaign_id)
                .order_by(Turn.id.desc())
                .limit(40)
                .all()
            )
            turns.reverse()
            timers = (
                session.query(Timer)
                .filter(Timer.campaign_id == campaign_id)
                .order_by(Timer.created_at.desc())
                .limit(20)
                .all()
            )

        campaign_state = self._parse_json(campaign.state_json, {})
        campaign_characters = self._parse_json(campaign.characters_json, {})

        player_rows = []
        for player in players:
            player_rows.append(
                {
                    "id": player.id,
                    "actor_id": player.actor_id,
                    "level": player.level,
                    "xp": player.xp,
                    "state": self._parse_json(player.state_json, {}),
                    "last_active_at": player.last_active_at.isoformat() if player.last_active_at else None,
                }
            )

        turn_rows = []
        for turn in turns:
            turn_rows.append(
                {
                    "id": int(turn.id),
                    "kind": turn.kind,
                    "actor_id": turn.actor_id,
                    "content": turn.content,
                    "meta": self._parse_json(turn.meta_json, {}),
                    "created_at": turn.created_at.isoformat() if turn.created_at else None,
                }
            )

        timer_rows = []
        for timer in timers:
            timer_rows.append(
                {
                    "id": timer.id,
                    "status": timer.status,
                    "event_text": timer.event_text,
                    "due_at": timer.due_at.isoformat() if timer.due_at else None,
                    "interruptible": timer.interruptible,
                    "interrupt_action": timer.interrupt_action,
                    "meta": self._parse_json(timer.meta_json, {}),
                }
            )

        return {
            "campaign": {
                "id": campaign.id,
                "namespace": campaign.namespace,
                "name": campaign.name,
                "summary": campaign.summary,
                "last_narration": campaign.last_narration,
                "state": campaign_state,
                "characters": campaign_characters,
            },
            "players": player_rows,
            "turns": turn_rows,
            "timers": timer_rows,
        }

    async def get_campaign_flags(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        emulator = self._emulator
        return {
            "guardrails": emulator.is_guardrails_enabled(campaign),
            "on_rails": emulator.is_on_rails(campaign),
            "timed_events": emulator.is_timed_events_enabled(campaign),
            "difficulty": emulator.get_difficulty(campaign),
            "speed_multiplier": emulator.get_speed_multiplier(campaign),
        }

    async def update_campaign_flags(
        self,
        campaign_id: str,
        *,
        guardrails: bool | None = None,
        on_rails: bool | None = None,
        timed_events: bool | None = None,
        difficulty: str | None = None,
        speed_multiplier: float | None = None,
    ) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        emulator = self._emulator
        changed: list[str] = []
        if guardrails is not None:
            emulator.set_guardrails_enabled(campaign, guardrails)
            changed.append("guardrails")
        if on_rails is not None:
            emulator.set_on_rails(campaign, on_rails)
            changed.append("on_rails")
        if timed_events is not None:
            emulator.set_timed_events_enabled(campaign, timed_events)
            changed.append("timed_events")
        if difficulty is not None:
            emulator.set_difficulty(campaign, difficulty)
            changed.append("difficulty")
        if speed_multiplier is not None:
            emulator.set_speed_multiplier(campaign, max(0.1, min(10.0, speed_multiplier)))
            changed.append("speed_multiplier")
        return {"ok": True, "changed": changed}

    async def get_source_materials(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        docs = self._emulator.list_source_material_documents(campaign_id, limit=20)
        return {"documents": docs}

    async def ingest_source_material(self, campaign_id: str, payload) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        chunks_stored, document_key = self._emulator.ingest_source_material_text(
            campaign_id,
            text=payload.text,
            document_label=payload.document_label or "source-material",
            source_format=payload.format,
            replace_document=payload.replace_document,
        )
        return {"ok": True, "chunks_stored": chunks_stored, "document_key": document_key}

    async def get_campaign_rules(self, campaign_id: str, key: str | None = None) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        if key:
            return {
                "document_key": self._emulator.AUTO_RULEBOOK_DOCUMENT_LABEL,
                "rule": self._emulator.get_campaign_rule(campaign_id, key),
            }
        return {
            "document_key": self._emulator.AUTO_RULEBOOK_DOCUMENT_LABEL,
            "rules": self._emulator.list_campaign_rules(campaign_id),
        }

    async def update_campaign_rule(self, campaign_id: str, payload) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        result = self._emulator.put_campaign_rule(
            campaign_id,
            rule_key=payload.key,
            rule_text=payload.value,
            upsert=payload.upsert,
        )
        return result if isinstance(result, dict) else {"ok": True}

    async def rewind_to_turn(self, campaign_id: str, target_turn_id: int) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        result = self._game_engine.rewind_to_turn(campaign_id, target_turn_id)
        ok = result.status == "ok" if hasattr(result, "status") else True
        return {
            "ok": ok,
            "target_turn_id": target_turn_id,
            "note": str(result),
            "detail": str(result),
        }

    async def cancel_pending_timer(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        cancelled = self._emulator.cancel_pending_timer(campaign_id)
        if cancelled is not None:
            event = cancelled.get("event", "unknown event")
            return {"ok": True, "cancelled_event": event}
        return {"ok": False, "note": "No pending timer to cancel."}

    async def get_player_statistics(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")
        stats = self._emulator.get_player_statistics(player)
        stats["actor_id"] = actor_id
        return stats

    async def get_player_attributes(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")
        attrs = self._emulator.get_player_attributes(player)
        level = int(player.level or 1)
        total = self._emulator.total_points_for_level(level)
        spent = self._emulator.points_spent(attrs)
        return {
            "actor_id": actor_id,
            "level": level,
            "xp": int(player.xp or 0),
            "attributes": attrs,
            "total_points": total,
            "points_spent": spent,
            "points_available": total - spent,
            "xp_needed_for_next": self._emulator.xp_needed_for_level(level),
            "max_attribute_value": self._emulator.MAX_ATTRIBUTE_VALUE,
        }

    async def set_player_attribute(self, campaign_id: str, actor_id: str, attribute: str, value: int) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")
        ok, message = self._emulator.set_attribute(player, attribute, value)
        return {"ok": ok, "message": message}

    async def rename_player_character(self, campaign_id: str, actor_id: str, name: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")
        return self._emulator.rename_player_character(campaign_id, actor_id, name)

    async def level_up_player(self, campaign_id: str, actor_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            player = (
                session.query(Player)
                .filter(Player.campaign_id == campaign_id)
                .filter(Player.actor_id == actor_id)
                .first()
            )
            if player is None:
                raise KeyError(f"Unknown player in campaign: {actor_id}")
        ok, message = self._emulator.level_up(player)
        return {"ok": ok, "message": message}

    async def get_recent_turns(self, campaign_id: str, limit: int = 30) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        turns = self._emulator.get_recent_turns(campaign_id, limit=limit)
        rows = []
        for turn in turns:
            meta = self._parse_json(turn.meta_json, {})
            rows.append({
                "id": turn.id,
                "kind": turn.kind,
                "actor_id": turn.actor_id,
                "session_id": turn.session_id,
                "content": turn.content,
                "meta": meta,
                "created_at": turn.created_at.isoformat() if turn.created_at else None,
            })
        return {"turns": rows, "count": len(rows)}

    async def get_campaign_persona(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        persona = self._emulator.get_campaign_default_persona(campaign, state)
        stored = state.get("default_persona")
        return {
            "persona": persona,
            "source": "custom" if isinstance(stored, str) and stored.strip() else "default",
        }

    async def set_campaign_persona(self, campaign_id: str, persona: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
            state["default_persona"] = persona.strip()[:140]
            campaign.state_json = json.dumps(state, ensure_ascii=False)
            session.commit()
        return {"ok": True, "persona": state["default_persona"]}

    async def get_puzzle_hint(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("_active_puzzle")
        if not isinstance(raw, dict):
            return {"hint": None, "note": "No active puzzle."}

        try:
            from text_game_engine.core.puzzles import PuzzleEngine, PuzzleState
            ps = PuzzleState(**{k: v for k, v in raw.items() if k in PuzzleState.__dataclass_fields__})
            hint = PuzzleEngine.get_hint(ps)
            if hint is None:
                return {"hint": None, "note": "No more hints available.", "hints_used": ps.hints_used}
            # Persist updated hints_used
            ps.hints_used += 1
            from dataclasses import asdict
            state["_active_puzzle"] = asdict(ps)
            with self._session_factory() as sess2:
                c2 = sess2.get(Campaign, campaign_id)
                if c2 is not None:
                    c2.state_json = json.dumps(state, ensure_ascii=False)
                    sess2.commit()
            return {"hint": hint, "hints_used": ps.hints_used, "hints_total": len(ps.hints)}
        except Exception as exc:
            return {"hint": None, "error": str(exc)}

    async def submit_puzzle_answer(self, campaign_id: str, answer: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("_active_puzzle")
        if not isinstance(raw, dict):
            return {"correct": False, "feedback": "No active puzzle.", "solved": False}

        try:
            from text_game_engine.core.puzzles import PuzzleEngine, PuzzleState
            from dataclasses import asdict
            ps = PuzzleState(**{k: v for k, v in raw.items() if k in PuzzleState.__dataclass_fields__})
            correct, feedback = PuzzleEngine.validate_answer(ps, answer)
            result = {
                "correct": correct,
                "feedback": feedback,
                "solved": ps.solved,
                "failed": ps.failed,
                "attempts": ps.attempts,
                "max_attempts": ps.max_attempts,
            }
            # Persist updated puzzle state
            state["_active_puzzle"] = asdict(ps)
            state["_puzzle_result"] = {
                "correct": correct,
                "feedback": feedback,
                "solved": ps.solved,
                "failed": ps.failed,
            }
            with self._session_factory() as sess2:
                c2 = sess2.get(Campaign, campaign_id)
                if c2 is not None:
                    c2.state_json = json.dumps(state, ensure_ascii=False)
                    sess2.commit()
            return result
        except Exception as exc:
            return {"correct": False, "feedback": str(exc), "solved": False}

    async def submit_minigame_move(self, campaign_id: str, move: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("_active_minigame")
        if not isinstance(raw, dict):
            return {"valid": False, "message": "No active minigame.", "finished": False}

        try:
            from text_game_engine.core.minigames import MinigameEngine, MinigameState
            from dataclasses import asdict
            ms = MinigameState(**{k: v for k, v in raw.items() if k in MinigameState.__dataclass_fields__})
            valid, message = MinigameEngine.player_move(ms, move)
            finished = MinigameEngine.is_finished(ms)
            board = MinigameEngine.render_board(ms)
            result = {
                "valid": valid,
                "message": message,
                "finished": finished,
                "board": board,
                "status": ms.status,
                "turn_count": ms.turn_count,
            }
            # Persist updated minigame state
            state["_active_minigame"] = asdict(ms)
            state["_minigame_result"] = {
                "valid": valid,
                "message": message,
                "finished": finished,
                "board": board,
            }
            with self._session_factory() as sess2:
                c2 = sess2.get(Campaign, campaign_id)
                if c2 is not None:
                    c2.state_json = json.dumps(state, ensure_ascii=False)
                    sess2.commit()
            return result
        except Exception as exc:
            return {"valid": False, "message": str(exc), "finished": False}

    async def get_minigame_board(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("_active_minigame")
        if not isinstance(raw, dict):
            return {"board": None, "note": "No active minigame."}

        try:
            from text_game_engine.core.minigames import MinigameEngine, MinigameState
            ms = MinigameState(**{k: v for k, v in raw.items() if k in MinigameState.__dataclass_fields__})
            board = MinigameEngine.render_board(ms)
            return {
                "board": board,
                "game_type": ms.game_type,
                "status": ms.status,
                "turn_count": ms.turn_count,
                "finished": MinigameEngine.is_finished(ms),
            }
        except Exception as exc:
            return {"board": None, "error": str(exc)}

    async def is_in_setup_mode(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        in_setup = self._emulator.is_in_setup_mode(campaign)
        state = self._parse_json(campaign.state_json, {})
        phase = str(state.get("setup_phase") or "").strip() if isinstance(state, dict) else ""
        setup_data = state.get("setup_data", {}) if isinstance(state, dict) else {}
        return {
            "in_setup": in_setup,
            "setup_phase": phase if in_setup else None,
            "setup_data_keys": list(setup_data.keys()) if isinstance(setup_data, dict) else [],
        }

    async def start_campaign_setup(
        self,
        campaign_id: str,
        *,
        actor_id: str | None = None,
        on_rails: bool = False,
        attachment_text: str | None = None,
    ) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            campaign_name = campaign.name
        try:
            message = await self._emulator.start_campaign_setup(
                campaign_id,
                actor_id=actor_id,
                raw_name=campaign_name,
                on_rails=on_rails,
                attachment_text=attachment_text,
                ingest_source_material=bool(attachment_text),
            )
            return {"ok": True, "message": str(message or ""), "setup_phase": "classify_confirm"}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "setup_phase": None}

    async def handle_setup_message(self, campaign_id: str, actor_id: str, message: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        try:
            response = await self._emulator.handle_setup_message(
                campaign_id,
                actor_id,
                message,
            )
            # Check current phase after handling
            with self._session_factory() as session:
                campaign = session.get(Campaign, campaign_id)
                state = self._parse_json(campaign.state_json, {}) if campaign else {}
            phase = str(state.get("setup_phase") or "").strip() if isinstance(state, dict) else ""
            return {
                "ok": True,
                "message": str(response or ""),
                "setup_phase": phase if phase and phase != "completed" else None,
                "completed": phase == "completed" or not phase,
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc), "setup_phase": None, "completed": False}

    async def get_scene_images(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("room_scene_images", {})
        images = {}
        if isinstance(raw, dict):
            for room_key, data in raw.items():
                url = None
                if isinstance(data, str):
                    url = data
                elif isinstance(data, dict):
                    url = data.get("url") or data.get("image_url")
                if url:
                    images[room_key] = url
        return {"images": images, "count": len(images)}

    async def get_literary_styles(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        raw = state.get("literary_styles", {})
        if not isinstance(raw, dict):
            raw = {}
        styles = {}
        for key, val in raw.items():
            if isinstance(val, dict):
                styles[key] = {
                    "profile": str(val.get("profile", ""))[:400],
                }
            elif isinstance(val, str):
                styles[key] = {"profile": val[:400]}
        return {"styles": styles, "count": len(styles)}

    async def cancel_sms_deliveries(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        cancelled = self._emulator.cancel_pending_sms_deliveries(campaign_id)
        return {"ok": True, "cancelled": cancelled}

    async def get_story_state(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            state = self._parse_json(campaign.state_json, {})
            if not isinstance(state, dict):
                state = {}
        return {
            "story_outline": state.get("story_outline"),
            "current_chapter": state.get("current_chapter"),
            "current_scene": state.get("current_scene"),
            "plot_threads": state.get("_plot_threads", {}),
            "consequences": state.get("_consequences", {}),
            "chapter_plan": state.get("_chapter_plan", {}),
            "active_puzzle": state.get("_active_puzzle"),
            "active_minigame": state.get("_active_minigame"),
        }

    async def search_source_material(self, campaign_id: str, query: str, *, document_key: str | None = None, top_k: int = 5) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        query_clean = str(query or "").strip()
        if not query_clean:
            return {"results": [], "query": query_clean}
        top_k_clean = max(1, min(int(top_k), 20))
        try:
            raw = self._emulator.search_source_material(
                query_clean,
                campaign_id,
                document_key=document_key,
                top_k=top_k_clean,
            )
        except Exception:
            return {"results": [], "query": query_clean, "error": "Search failed."}
        results = []
        for doc_key, doc_label, chunk_idx, chunk_text, score in raw:
            results.append({
                "document_key": doc_key,
                "document_label": doc_label,
                "chunk_index": chunk_idx,
                "text": str(chunk_text or "")[:1000],
                "score": round(float(score), 4),
            })
        return {"results": results, "query": query_clean}

    async def ingest_source_material_with_digest(self, campaign_id: str, payload) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        text = str(payload.text or "").strip()
        label = str(payload.document_label or "").strip()
        if not text:
            raise ValueError("Source material text is required.")
        if not label:
            raise ValueError("Document label is required.")
        fmt = str(payload.format or "").strip().lower() or None
        replace = bool(payload.replace_document)
        try:
            chunks_stored, document_key, literary_profiles = await self._emulator.ingest_source_material_with_digest(
                campaign_id,
                document_label=label,
                text=text,
                source_format=fmt,
                replace_document=replace,
            )
        except Exception as exc:
            raise ValueError(f"Digest ingest failed: {exc}") from exc
        profiles_clean: dict[str, object] = {}
        if isinstance(literary_profiles, dict):
            for name, profile in literary_profiles.items():
                if isinstance(profile, dict):
                    profiles_clean[str(name)] = {k: str(v)[:400] for k, v in profile.items()}
                elif isinstance(profile, str):
                    profiles_clean[str(name)] = profile[:400]
        return {
            "ok": True,
            "chunks_stored": int(chunks_stored),
            "document_key": str(document_key),
            "literary_profiles": profiles_clean,
        }

    async def browse_source_keys(self, campaign_id: str, *, wildcard: str = "*", document_key: str | None = None) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        try:
            keys = self._emulator.browse_source_keys(
                campaign_id,
                document_key=document_key,
                wildcard=wildcard,
                limit=60,
            )
        except Exception:
            keys = []
        return {"keys": list(keys) if isinstance(keys, list) else []}

    async def record_character_portrait(self, campaign_id: str, character_slug: str, image_url: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        slug = str(character_slug or "").strip()
        url = str(image_url or "").strip()
        if not slug:
            raise ValueError("character_slug is required.")
        if not url:
            raise ValueError("image_url is required.")
        try:
            ok = self._emulator.record_character_portrait_url(campaign_id, slug, url)
        except Exception:
            ok = False
        return {"ok": bool(ok), "character_slug": slug, "image_url": url}

    async def schedule_sms_delivery(self, campaign_id: str, *, thread: str, sender: str, recipient: str, message: str, delay_seconds: int) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
        thread_clean = str(thread or "").strip()
        sender_clean = str(sender or "").strip()
        recipient_clean = str(recipient or "").strip()
        message_clean = str(message or "").strip()
        delay = max(0, min(int(delay_seconds), 86400))
        if not all([thread_clean, sender_clean, recipient_clean, message_clean]):
            raise ValueError("thread, sender, recipient, and message are all required.")
        try:
            ok, reason, actual_delay = self._emulator.schedule_sms_thread_delivery(
                campaign_id,
                thread=thread_clean,
                sender=sender_clean,
                recipient=recipient_clean,
                message=message_clean,
                delay_seconds=delay,
            )
        except Exception as exc:
            return {"ok": False, "reason": str(exc), "delay_seconds": delay}
        return {"ok": bool(ok), "reason": reason, "delay_seconds": actual_delay}

    async def delete_campaign(self, campaign_id: str) -> dict:
        with self._session_factory() as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            name = campaign.name
            # Delete all related data
            session.query(Embedding).filter(Embedding.campaign_id == campaign_id).delete()
            session.query(Snapshot).filter(Snapshot.campaign_id == campaign_id).delete()
            session.query(Turn).filter(Turn.campaign_id == campaign_id).delete()
            session.query(Timer).filter(Timer.campaign_id == campaign_id).delete()
            session.query(InflightTurn).filter(InflightTurn.campaign_id == campaign_id).delete()
            session.query(OutboxEvent).filter(OutboxEvent.campaign_id == campaign_id).delete()
            session.query(GameSession).filter(GameSession.campaign_id == campaign_id).delete()
            session.query(MediaRef).filter(MediaRef.campaign_id == campaign_id).delete()
            session.query(Player).filter(Player.campaign_id == campaign_id).delete()
            session.delete(campaign)
            session.commit()
        return {"ok": True, "deleted_campaign_id": campaign_id, "name": name}

    def set_media_port(self, media_port: object) -> None:
        """Inject a MediaGenerationPort implementation after construction.

        Safe because ZorkEmulator null-checks ``_media_port`` at every
        usage site before calling into it.
        """
        self._emulator._media_port = media_port

    def set_timer_effects_port(self, port: object) -> None:
        """Inject a TimerEffectsPort implementation after construction.

        Safe because ZorkEmulator null-checks ``_timer_effects_port``
        before calling into it.
        """
        self._emulator._timer_effects_port = port
