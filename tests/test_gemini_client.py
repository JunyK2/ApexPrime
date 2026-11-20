from apexprime.analysis import GeminiClient


class FakeResponse:
    ok = True

    def json(self):
        return {
            "candidates": [{"content": {"parts": [{"text": "APEX_TABLE ok"}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4, "totalTokenCount": 16},
        }


class FakeSession:
    def __init__(self):
        self.call = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.call = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return FakeResponse()


def test_gemini_client_sends_rest_camelcase_inline_image(monkeypatch):
    client = GeminiClient("test-key", "gemini-4-hydrogen")
    session = FakeSession()
    monkeypatch.setattr(client, "session", session)

    result = client.analyze(
        "Analise esta imagem",
        images=[{"timeframe": "1H", "mime_type": "image/png", "data": b"png-bytes"}],
    )

    part = session.call["json"]["contents"][0]["parts"][2]
    assert "inlineData" in part
    assert part["inlineData"]["mimeType"] == "image/png"
    assert part["inlineData"]["data"] == "cG5nLWJ5dGVz"
    assert "inline_data" not in part
    assert result["text"] == "APEX_TABLE ok"
    assert result["total_tokens"] == 16
