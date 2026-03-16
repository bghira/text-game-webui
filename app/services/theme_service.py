"""Theme discovery and management service."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

_BUILTIN_THEMES_DIR = Path(__file__).resolve().parent.parent / "static" / "css" / "themes"
_LOCAL_THEMES_DIR = Path.home() / ".text-game-webui" / "themes"
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_ALLOWED_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})
_ALLOWED_SOUND_EXTS = frozenset({".mp3", ".ogg", ".wav", ".flac"})


@dataclass
class ThemeAssets:
    images: dict[str, Path] = field(default_factory=dict)
    sounds: dict[str, Path] = field(default_factory=dict)


@dataclass
class ThemeMetadata:
    id: str
    name: str
    description: str = ""
    author: str = ""
    css_path: Path | None = None
    source: str = "builtin"  # builtin | entrypoint | local
    theme_dir: Path | None = None
    assets: ThemeAssets = field(default_factory=ThemeAssets)


class EntryPointThemeSource:
    """Discover themes installed as pip packages via entry points."""

    GROUP = "text_game_webui.themes"

    def discover(self) -> list[ThemeMetadata]:
        themes: list[ThemeMetadata] = []
        eps = entry_points()
        group = eps.get(self.GROUP, []) if isinstance(eps, dict) else eps.select(group=self.GROUP)
        for ep in group:
            try:
                theme_cls = ep.load()
                meta = self._extract_metadata(ep.name, theme_cls)
                if meta:
                    themes.append(meta)
            except Exception:
                continue
        return themes

    @staticmethod
    def _extract_metadata(name: str, theme_cls: Any) -> ThemeMetadata | None:
        obj = theme_cls() if callable(theme_cls) else theme_cls
        css_path = None
        theme_dir = None
        assets = ThemeAssets()

        if hasattr(obj, "css_path"):
            css_path = Path(obj.css_path)
        elif hasattr(obj, "__file__"):
            pkg_dir = Path(obj.__file__).parent
            candidate = pkg_dir / "theme.css"
            if candidate.exists():
                css_path = candidate
            theme_dir = pkg_dir

        if theme_dir:
            assets = _scan_assets(theme_dir)

        return ThemeMetadata(
            id=name,
            name=getattr(obj, "name", name.replace("-", " ").replace("_", " ").title()),
            description=getattr(obj, "description", ""),
            author=getattr(obj, "author", ""),
            css_path=css_path,
            source="entrypoint",
            theme_dir=theme_dir,
            assets=assets,
        )


class LocalFolderThemeSource:
    """Discover themes placed in ~/.text-game-webui/themes/{id}/."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or _LOCAL_THEMES_DIR

    def discover(self) -> list[ThemeMetadata]:
        themes: list[ThemeMetadata] = []
        if not self._base.is_dir():
            return themes
        for child in sorted(self._base.iterdir()):
            if not child.is_dir():
                continue
            meta = self._load_theme(child)
            if meta:
                themes.append(meta)
        return themes

    @staticmethod
    def _load_theme(theme_dir: Path) -> ThemeMetadata | None:
        manifest = theme_dir / "theme.json"
        css_file = theme_dir / "theme.css"
        if not manifest.exists() or not css_file.exists():
            return None
        try:
            data = json.loads(manifest.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        theme_id = theme_dir.name
        if not _SAFE_NAME_RE.match(theme_id):
            return None
        return ThemeMetadata(
            id=theme_id,
            name=data.get("name", theme_id),
            description=data.get("description", ""),
            author=data.get("author", ""),
            css_path=css_file,
            source="local",
            theme_dir=theme_dir,
            assets=_scan_assets(theme_dir),
        )


def _scan_assets(theme_dir: Path) -> ThemeAssets:
    assets = ThemeAssets()
    images_dir = theme_dir / "assets" / "images"
    sounds_dir = theme_dir / "assets" / "sounds"
    if images_dir.is_dir():
        for f in images_dir.iterdir():
            if f.is_file() and f.suffix.lower() in _ALLOWED_IMAGE_EXTS:
                assets.images[f.name] = f
    if sounds_dir.is_dir():
        for f in sounds_dir.iterdir():
            if f.is_file() and f.suffix.lower() in _ALLOWED_SOUND_EXTS:
                assets.sounds[f.name] = f
    return assets


class ThemeService:
    """Singleton service for theme discovery and management."""

    def __init__(self) -> None:
        self._cache: dict[str, ThemeMetadata] | None = None
        self._sources = [
            EntryPointThemeSource(),
            LocalFolderThemeSource(),
        ]

    # -- Built-in themes ---------------------------------------------------

    @staticmethod
    def _builtins() -> list[ThemeMetadata]:
        return [
            ThemeMetadata(
                id="light",
                name="Light",
                description="Default light theme",
                source="builtin",
            ),
            ThemeMetadata(
                id="dark",
                name="Dark",
                description="Built-in dark theme",
                css_path=_BUILTIN_THEMES_DIR / "dark.css",
                source="builtin",
            ),
        ]

    # -- Public API --------------------------------------------------------

    def discover_themes(self) -> dict[str, ThemeMetadata]:
        if self._cache is not None:
            return self._cache
        themes: dict[str, ThemeMetadata] = {}
        for builtin in self._builtins():
            themes[builtin.id] = builtin
        for source in self._sources:
            for theme in source.discover():
                if theme.id not in themes:
                    themes[theme.id] = theme
        self._cache = themes
        return themes

    def get_theme(self, theme_id: str) -> ThemeMetadata | None:
        return self.discover_themes().get(theme_id)

    def is_valid_theme(self, theme_id: str) -> bool:
        return theme_id in self.discover_themes()

    def list_for_ui(self) -> list[dict[str, str]]:
        items = []
        for t in self.discover_themes().values():
            items.append({
                "value": t.id,
                "label": t.name,
                "description": t.description,
                "source": t.source,
            })
        return items

    def get_asset_path(self, theme_id: str, kind: str, name: str) -> Path | None:
        """Return the filesystem path for a theme asset, with security checks."""
        if not _SAFE_NAME_RE.match(name):
            return None
        theme = self.get_theme(theme_id)
        if not theme:
            return None
        bucket = theme.assets.images if kind == "images" else theme.assets.sounds
        path = bucket.get(name)
        if path and theme.theme_dir:
            # Path traversal prevention
            try:
                path.resolve().relative_to(theme.theme_dir.resolve())
            except ValueError:
                return None
        return path

    def invalidate_cache(self) -> None:
        self._cache = None
