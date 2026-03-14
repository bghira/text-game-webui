from __future__ import annotations

import base64
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageCacheEntry:
    image_id: str
    filename: str
    prompt: str
    campaign_id: str | None = None
    room_key: str | None = None
    ref_type: str = "scene"  # scene | avatar
    created_at: float = field(default_factory=time.time)
    png_bytes: bytes | None = None  # None when evicted from memory


class ImageCache:
    """In-memory LRU + disk persistence for generated images.

    PNGs are always persisted to *generated_dir*; the LRU only governs
    whether the raw bytes are kept in RAM for fast re-serving.
    """

    def __init__(self, generated_dir: Path, max_entries: int = 50) -> None:
        self._dir = generated_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max = max_entries
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, ImageCacheEntry] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        *,
        png_bytes: bytes,
        prompt: str,
        campaign_id: str | None = None,
        room_key: str | None = None,
        ref_type: str = "scene",
    ) -> ImageCacheEntry:
        image_id = hashlib.sha256(png_bytes).hexdigest()[:16]
        filename = f"{image_id}.png"
        disk_path = self._dir / filename
        disk_path.write_bytes(png_bytes)

        entry = ImageCacheEntry(
            image_id=image_id,
            filename=filename,
            prompt=prompt,
            campaign_id=campaign_id,
            room_key=room_key,
            ref_type=ref_type,
            png_bytes=png_bytes,
        )

        with self._lock:
            self._entries[image_id] = entry
            self._entries.move_to_end(image_id)
            self._evict()

        return entry

    def store_from_base64(
        self,
        *,
        base64_png: str,
        prompt: str,
        campaign_id: str | None = None,
        room_key: str | None = None,
        ref_type: str = "scene",
    ) -> ImageCacheEntry:
        png_bytes = base64.b64decode(base64_png)
        return self.store(
            png_bytes=png_bytes,
            prompt=prompt,
            campaign_id=campaign_id,
            room_key=room_key,
            ref_type=ref_type,
        )

    def get(self, image_id: str) -> ImageCacheEntry | None:
        with self._lock:
            entry = self._entries.get(image_id)
            if entry is not None:
                self._entries.move_to_end(image_id)
            return entry

    @staticmethod
    def url_for(entry: ImageCacheEntry) -> str:
        return f"/generated/{entry.filename}"

    def recent(self, limit: int = 20) -> list[ImageCacheEntry]:
        with self._lock:
            items = list(reversed(self._entries.values()))
        return items[:limit]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict(self) -> None:
        while len(self._entries) > self._max:
            _key, old = self._entries.popitem(last=False)
            old.png_bytes = None  # free memory; disk file stays
