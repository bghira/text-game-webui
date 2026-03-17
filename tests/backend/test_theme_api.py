"""Tests for the theme API endpoints."""
from __future__ import annotations


def test_list_themes(client):
    res = client.get("/api/themes")
    assert res.status_code == 200
    themes = res.json()
    assert isinstance(themes, list)
    assert len(themes) >= 2
    values = [t["value"] for t in themes]
    assert "light" in values
    assert "dark" in values


def test_get_theme_metadata(client):
    res = client.get("/api/themes/dark")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "dark"
    assert body["name"] == "Dark"
    assert body["source"] == "builtin"


def test_get_nonexistent_theme_404(client):
    res = client.get("/api/themes/nonexistent-theme")
    assert res.status_code == 404


def test_builtin_theme_css_404(client):
    # Built-in themes serve CSS via static assets, not this endpoint
    res = client.get("/api/themes/dark/theme.css")
    assert res.status_code == 404


def test_get_theme_manifest(client):
    res = client.get("/api/themes/light/manifest")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "light"
    assert "images" in body
    assert "sounds" in body


def test_refresh_themes(client):
    res = client.post("/api/themes/refresh")
    assert res.status_code == 200
    themes = res.json()
    assert isinstance(themes, list)
    assert len(themes) >= 2


def test_get_theme_setting(client):
    # Ensure clean state regardless of test ordering
    client.post("/api/settings/theme", json={"theme": "light"})
    res = client.get("/api/settings/theme")
    assert res.status_code == 200
    body = res.json()
    assert "theme" in body
    assert body["theme"] == "light"


def test_set_theme_setting(client):
    res = client.post("/api/settings/theme", json={"theme": "dark"})
    assert res.status_code == 200
    assert res.json()["theme"] == "dark"

    # Verify it persisted in settings object
    res2 = client.get("/api/settings/theme")
    assert res2.json()["theme"] == "dark"

    # Reset to default so other tests aren't affected by ordering
    client.post("/api/settings/theme", json={"theme": "light"})


def test_set_invalid_theme_returns_400(client):
    res = client.post("/api/settings/theme", json={"theme": "nonexistent"})
    assert res.status_code == 400


def test_theme_asset_404_for_builtin(client):
    res = client.get("/api/themes/dark/assets/images/bg.png")
    assert res.status_code == 404

    res = client.get("/api/themes/dark/assets/sounds/click.mp3")
    assert res.status_code == 404


def test_ui_index_includes_theme_context(client):
    res = client.get("/")
    assert res.status_code == 200
    # The HTML should contain data-theme attribute
    assert 'data-theme="' in res.text
