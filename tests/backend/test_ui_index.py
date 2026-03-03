def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    text = res.text
    assert "text-game-webui" in text
    assert "Turn Stream" in text
    assert "Sessions" in text
    assert "Timers" in text
    assert "Runtime" in text
    assert "Player" in text
    assert "Media" in text
    assert "Accept Pending Avatar" in text
    assert "DB Check:" in text
    assert "LLM Check:" in text
    assert "Run LLM Probe" in text
    assert "Connection Diagnostics" in text
    assert "Copy Diagnostics Bundle" in text
    assert "Available Features" in text
