def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    text = res.text
    assert "text-game-webui" in text
    assert "Feature Surface" in text
