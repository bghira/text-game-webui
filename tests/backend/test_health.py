def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_feature_list(client):
    res = client.get("/api/features")
    assert res.status_code == 200
    body = res.json()
    assert "features" in body
    assert "memory_search" in body["features"]
    assert "sms_write" in body["features"]
    assert "debug_snapshot" in body["features"]
    assert "player_state" in body["features"]
    assert "media_status" in body["features"]


def test_runtime_endpoint(client):
    res = client.get("/api/runtime")
    assert res.status_code == 200
    body = res.json()
    assert body["gateway_backend"] == "inmemory"


def test_runtime_checks_endpoint(client):
    res = client.get("/api/runtime/checks")
    assert res.status_code == 200
    body = res.json()
    assert "generated_at" in body
    assert body["probe_llm"] is False
    assert "checks" in body
    assert body["checks"]["backend"] == "inmemory"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["engine"]["ok"] is True
    assert body["checks"]["llm"]["configured"] is False


def test_runtime_checks_probe_query_override(client):
    seen: dict[str, bool] = {}

    async def fake_checks(probe_llm: bool = False) -> dict:
        seen["probe_llm"] = probe_llm
        return {
            "backend": "inmemory",
            "database": {"ok": True, "detail": "ok"},
            "engine": {"ok": True, "detail": "ok"},
            "llm": {"configured": False, "probe_attempted": probe_llm, "ok": None, "detail": "n/a"},
        }

    client.app.state.gateway.runtime_checks = fake_checks
    res = client.get("/api/runtime/checks", params={"probe_llm": "true"})
    assert res.status_code == 200
    assert seen["probe_llm"] is True
    assert res.json()["probe_llm"] is True


def test_diagnostics_bundle_endpoint_without_campaign(client):
    res = client.get("/api/diagnostics/bundle")
    assert res.status_code == 200
    body = res.json()
    assert "generated_at" in body
    assert "runtime" in body
    assert "runtime_checks" in body
    assert "features" in body
    assert body["runtime"]["gateway_backend"] == "inmemory"
    assert "checks" in body["runtime_checks"]
