from apexprime.analysis import ChartImgClient, OpenRouterClient


class ImageResponse:
    ok = True
    headers = {"Content-Type": "image/png"}
    content = b"x" * 2048
    text = ""


class ChatResponse:
    ok = True

    def json(self):
        return {
            "model": "free/test-vision-model",
            "choices": [{"message": {"content": "[APEX_TABLE] {\"signal\":\"NO_TRADE\"} [/APEX_TABLE]"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


class CaptureSession:
    def __init__(self, response):
        self.response = response
        self.call = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.call = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return self.response


def test_chart_img_free_resolution_is_exactly_800_by_600(monkeypatch):
    client = ChartImgClient("test-key")
    session = CaptureSession(ImageResponse())
    monkeypatch.setattr(client, "session", session)

    data, mime = client.get_chart("1h", symbol="BINANCE:BTCUSDT.P")

    assert len(data) == 2048
    assert mime == "image/png"
    body = session.call["json"]
    assert body["width"] == 800
    assert body["height"] == 600
    assert body["symbol"] == "BINANCE:BTCUSDT.P"


def test_openrouter_encodes_chart_as_openai_compatible_data_uri(monkeypatch):
    client = OpenRouterClient("test-key", "openrouter/free")
    session = CaptureSession(ChatResponse())
    monkeypatch.setattr(client, "session", session)

    result = client.analyze(
        "Analise o gráfico",
        images=[{"timeframe": "1H", "mime_type": "image/png", "data": b"png-bytes"}],
    )

    content = session.call["json"]["messages"][1]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"] == "data:image/png;base64,cG5nLWJ5dGVz"
    assert session.call["json"]["model"] == "openrouter/free"
    assert result["model"] == "free/test-vision-model"
    assert result["total_tokens"] == 15
