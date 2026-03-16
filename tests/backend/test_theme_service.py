"""Tests for the ThemeService."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.theme_service import ThemeService, LocalFolderThemeSource, ThemeMetadata


def test_builtins_always_present():
    svc = ThemeService()
    themes = svc.discover_themes()
    assert "light" in themes
    assert "dark" in themes
    assert themes["light"].source == "builtin"
    assert themes["dark"].source == "builtin"


def test_light_has_no_css_path():
    svc = ThemeService()
    light = svc.get_theme("light")
    assert light is not None
    assert light.css_path is None


def test_dark_has_css_path():
    svc = ThemeService()
    dark = svc.get_theme("dark")
    assert dark is not None
    assert dark.css_path is not None
    assert dark.css_path.exists()
    assert dark.css_path.name == "dark.css"


def test_is_valid_theme():
    svc = ThemeService()
    assert svc.is_valid_theme("light") is True
    assert svc.is_valid_theme("dark") is True
    assert svc.is_valid_theme("nonexistent") is False


def test_list_for_ui_shape():
    svc = ThemeService()
    items = svc.list_for_ui()
    assert len(items) >= 2
    for item in items:
        assert "value" in item
        assert "label" in item
        assert "description" in item
        assert "source" in item


def test_invalidate_cache():
    svc = ThemeService()
    svc.discover_themes()
    assert svc._cache is not None
    svc.invalidate_cache()
    assert svc._cache is None


def test_get_nonexistent_theme():
    svc = ThemeService()
    assert svc.get_theme("does-not-exist") is None


def test_local_folder_source_discovers_theme(tmp_path):
    theme_dir = tmp_path / "my-local-theme"
    theme_dir.mkdir()
    (theme_dir / "theme.json").write_text(json.dumps({
        "name": "My Local Theme",
        "description": "A test theme",
        "author": "Tester",
    }))
    (theme_dir / "theme.css").write_text("html[data-theme='my-local-theme'] { --bg: #000; }")

    source = LocalFolderThemeSource(base_dir=tmp_path)
    themes = source.discover()
    assert len(themes) == 1
    assert themes[0].id == "my-local-theme"
    assert themes[0].name == "My Local Theme"
    assert themes[0].source == "local"
    assert themes[0].css_path == theme_dir / "theme.css"


def test_local_folder_source_skips_invalid_dir(tmp_path):
    # Directory with no theme.json
    (tmp_path / "bad-theme").mkdir()
    (tmp_path / "bad-theme" / "theme.css").write_text("")

    source = LocalFolderThemeSource(base_dir=tmp_path)
    themes = source.discover()
    assert len(themes) == 0


def test_local_folder_source_skips_unsafe_names(tmp_path):
    theme_dir = tmp_path / "../escape"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "theme.json").write_text(json.dumps({"name": "escape"}))
    (theme_dir / "theme.css").write_text("")

    source = LocalFolderThemeSource(base_dir=tmp_path)
    themes = source.discover()
    # ../escape shouldn't appear as a valid theme
    assert all(t.id != "../escape" for t in themes)


def test_local_folder_source_empty_when_missing():
    source = LocalFolderThemeSource(base_dir=Path("/nonexistent/path/themes"))
    assert source.discover() == []


def test_local_folder_discovers_assets(tmp_path):
    theme_dir = tmp_path / "asset-theme"
    theme_dir.mkdir()
    (theme_dir / "theme.json").write_text(json.dumps({"name": "Asset Theme"}))
    (theme_dir / "theme.css").write_text("")
    (theme_dir / "assets" / "images").mkdir(parents=True)
    (theme_dir / "assets" / "sounds").mkdir(parents=True)
    (theme_dir / "assets" / "images" / "bg.png").write_bytes(b"\x89PNG")
    (theme_dir / "assets" / "sounds" / "click.mp3").write_bytes(b"\xff\xfb")

    source = LocalFolderThemeSource(base_dir=tmp_path)
    themes = source.discover()
    assert len(themes) == 1
    assert "bg.png" in themes[0].assets.images
    assert "click.mp3" in themes[0].assets.sounds


def test_get_asset_path_validates_name():
    svc = ThemeService()
    # Invalid name with path traversal
    assert svc.get_asset_path("dark", "images", "../../../etc/passwd") is None
    # Valid name but no assets on builtin
    assert svc.get_asset_path("dark", "images", "bg.png") is None
