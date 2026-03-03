from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.settings import Settings
from app.services.schemas import CampaignSummary, MemoryStoreRequest, TurnRequest, TurnResult

from .engine_gateway import EngineGateway

try:
    from text_game_engine.core.engine import GameEngine
    from text_game_engine.core.types import GiveItemInstruction, LLMTurnOutput, TimerInstruction
    from text_game_engine.persistence.sqlalchemy import (
        SQLAlchemyUnitOfWork,
        build_engine,
        build_session_factory,
        create_schema,
    )
    from text_game_engine.persistence.sqlalchemy.models import (
        Campaign,
        MediaRef,
        OutboxEvent,
        Player,
        Session as GameSession,
        Timer,
        Turn,
    )
    from text_game_engine.zork_emulator import ZorkEmulator
except Exception as exc:  # pragma: no cover - import guarded at runtime
    raise RuntimeError(
        "text-game-engine backend selected but package is unavailable. "
        "Install it with: pip install -e ../text-game-engine"
    ) from exc


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

    async def complete_turn(self, context) -> LLMTurnOutput:
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

    def __init__(
        self,
        *,
        session_factory,
        completion_port: OpenAICompatibleCompletionPort,
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

        state_update, player_state_update = emulator._split_room_state(state_update, player_state_update)  # noqa: SLF001

        summary_update = payload.get("summary_update")
        if not isinstance(summary_update, str) or not summary_update.strip():
            summary_update = None

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
            state_update=state_update,
            summary_update=summary_update,
            xp_awarded=xp_awarded,
            player_state_update=player_state_update,
            scene_image_prompt=scene_image_prompt,
            timer_instruction=timer_instruction,
            character_updates=character_updates,
            give_item=give_item,
        )

    def _tool_memory_search(self, campaign_id: str, payload: dict[str, Any]) -> str:
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
        if not queries:
            return "MEMORY_RECALL: No queries provided."

        curated_hits: list[tuple[str, str, float]] = []
        if self._emulator is not None:
            for query in queries[:4]:
                curated_hits.extend(
                    self._emulator.search_curated_memories(
                        query=query,
                        campaign_id=campaign_id,
                        category=category,
                        top_k=5,
                    )
                )

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

        for query in queries[:4]:
            q = query.lower().strip()
            parts = [token for token in re.split(r"\W+", q) if token]
            for turn in turns:
                content = str(turn.content or "")
                if not content:
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
                    }

        ordered_narrator = sorted(
            narrator_hits.values(),
            key=lambda row: (float(row.get("score", 0.0)), int(row.get("turn_id", 0))),
            reverse=True,
        )[:5]

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
                    f"- [narrator turn {hit['turn_id']}, relevance {float(hit['score']):.2f}]: {snippet}"
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

        lines.extend(
            [
                "MEMORY_RECALL_NEXT_ACTIONS:",
                "- To retrieve FULL text for a specific hit turn number:",
                '  {"tool_call": "memory_turn", "turn_id": 1234}',
                "- To discover curated memory categories/terms before narrowing search:",
                '  {"tool_call": "memory_terms", "wildcard": "char:*"}',
                "- To search inside one curated category after term discovery:",
                '  {"tool_call": "memory_search", "category": "char:character-slug", "queries": ["keyword1", "keyword2"]}',
                "- To inspect off-scene SMS communications:",
                '  {"tool_call": "sms_list", "wildcard": "*"}',
                '  {"tool_call": "sms_read", "thread": "contact-slug", "limit": 20}',
            ]
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

    def _tool_memory_turn(self, campaign_id: str, payload: dict[str, Any]) -> str:
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
        if turn is None:
            return f"MEMORY_TURN: no turn found for turn_id={turn_id}"

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
            ]
        )
        return "\n".join(lines)

    def _tool_sms_read(self, campaign_id: str, payload: dict[str, Any]) -> str:
        thread_raw = payload.get("thread")
        limit_raw = payload.get("limit", 20)
        thread = thread_raw.strip() if isinstance(thread_raw, str) and thread_raw.strip() else ""
        try:
            limit = max(1, min(40, int(limit_raw)))
        except Exception:
            limit = 20

        if not thread:
            return "SMS_READ_RESULT: invalid thread"

        canonical, matched, messages = self._emulator.read_sms_thread(campaign_id, thread, limit=limit) if self._emulator else (None, None, [])
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

    def _execute_tool_call(self, campaign_id: str, payload: dict[str, Any]) -> str:
        tool = payload.get("tool_call")
        if not isinstance(tool, str):
            return "TOOL_ERROR: missing tool_call"
        name = tool.strip().lower()

        if name == "memory_search":
            return self._tool_memory_search(campaign_id, payload)
        if name == "memory_terms":
            return self._tool_memory_terms(campaign_id, payload)
        if name == "memory_turn":
            return self._tool_memory_turn(campaign_id, payload)
        if name == "memory_store":
            return self._tool_memory_store(campaign_id, payload)
        if name == "sms_list":
            return self._tool_sms_list(campaign_id, payload)
        if name == "sms_read":
            return self._tool_sms_read(campaign_id, payload)
        if name == "sms_write":
            return self._tool_sms_write(campaign_id, payload)
        if name == "story_outline":
            return self._tool_story_outline(campaign_id, payload)
        return f"TOOL_ERROR: unsupported tool_call '{name}'"

    async def _resolve_payload(self, campaign_id: str, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
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
        for _ in range(max(0, self._max_tool_rounds)):
            emulator = self._emulator
            if emulator is None:
                return None
            if not emulator._is_tool_call(payload):  # noqa: SLF001
                return payload
            tool_result = self._execute_tool_call(campaign_id, payload)
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

        emulator = self._emulator
        if emulator is None:
            return None
        if emulator._is_tool_call(payload):  # noqa: SLF001
            return None
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
            system_prompt, user_prompt = emulator.build_prompt(campaign, player, context.action, turns)
            payload = await self._resolve_payload(context.campaign_id, system_prompt, user_prompt)
            if payload is None:
                return await self._fallback.complete_turn(context)
            return self._payload_to_output(payload)
        except Exception:
            return await self._fallback.complete_turn(context)


class TextGameEngineGateway(EngineGateway):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._completion_mode = (settings.tge_completion_mode or "deterministic").strip().lower()

        engine = build_engine(settings.tge_database_url)
        create_schema(engine)
        self._session_factory = build_session_factory(engine)

        def _uow_factory():
            return SQLAlchemyUnitOfWork(self._session_factory)

        completion_port: OpenAICompatibleCompletionPort | None = None
        if self._completion_mode == "openai":
            completion_port = OpenAICompatibleCompletionPort(
                base_url=settings.tge_llm_base_url,
                api_key=settings.tge_llm_api_key,
                model=settings.tge_llm_model,
                timeout_seconds=settings.tge_llm_timeout_seconds,
            )
            llm = ZorkToolAwareLLM(
                session_factory=self._session_factory,
                completion_port=completion_port,
                temperature=settings.tge_llm_temperature,
                max_tokens=settings.tge_llm_max_tokens,
            )
        elif self._completion_mode == "deterministic":
            llm = DeterministicLLM()
        else:
            raise ValueError(f"Unsupported tge completion mode: {self._completion_mode}")

        game_engine = GameEngine(uow_factory=_uow_factory, llm=llm)
        self._emulator = ZorkEmulator(
            game_engine=game_engine,
            session_factory=self._session_factory,
            completion_port=completion_port,
            map_completion_port=completion_port,
            memory_port=None,
            imdb_port=None,
            media_port=None,
        )
        self._completion_port = completion_port
        self._probe_timeout_seconds = max(int(settings.tge_runtime_probe_timeout_seconds or 8), 1)
        if isinstance(llm, ZorkToolAwareLLM):
            llm.bind_emulator(self._emulator)

    @property
    def completion_mode(self) -> str:
        return self._completion_mode

    async def runtime_checks(self, probe_llm: bool = False) -> dict:
        database_ok = True
        database_detail = "Connected."
        try:
            with self._session_factory() as session:
                _ = session.query(Campaign).limit(1).all()
        except Exception as exc:
            database_ok = False
            database_detail = f"{exc.__class__.__name__}: {exc}"

        llm_configured = self._completion_mode == "openai" and self._completion_port is not None
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

    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult:
        xp_before = 0
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

        self._emulator.get_or_create_player(campaign_id, request.actor_id)
        narration = await self._emulator.play_action(
            campaign_id=campaign_id,
            actor_id=request.actor_id,
            action=request.action,
            manage_claim=True,
        )

        if narration is None:
            narration = "The world shifts, but nothing clear emerges."

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

        return TurnResult(
            narration=str(narration),
            state_update=state_update,
            player_state_update=player_state_update,
            summary_update=summary_update,
            xp_awarded=max(xp_after - xp_before, 0),
            image_prompt=None,
        )

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

        return {
            "game_time": state.get("game_time", {}),
            "events": state.get("calendar", []),
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

    async def sms_read(self, campaign_id: str, thread: str, limit: int) -> dict:
        canonical, matched, messages = self._emulator.read_sms_thread(campaign_id, thread, limit=limit)
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
