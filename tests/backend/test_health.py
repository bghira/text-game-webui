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
