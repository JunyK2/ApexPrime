from __future__ import annotations

import logging
import requests

log = logging.getLogger("apexprime.telegram")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            return False
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message[:3900], "disable_web_page_preview": True},
                timeout=20,
            )
        except requests.RequestException as exc:
            # requests may include the bot-token URL in exception text; do not log it.
            log.warning("Telegram indisponível (%s)", type(exc).__name__)
            return False
        if not response.ok:
            log.warning("Telegram falhou HTTP %s: %s", response.status_code, response.text[:400])
            return False
        try:
            return bool(response.json().get("ok"))
        except ValueError:
            log.warning("Telegram retornou resposta que não é JSON")
            return False

    def send_long(self, message: str, chunk_size: int = 3600) -> bool:
        """Send long trade-review text in Telegram-safe chunks."""
        text = str(message or "")
        if len(text) <= chunk_size:
            return self.send(text)
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= chunk_size:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, chunk_size)
            if split_at < chunk_size // 2:
                split_at = chunk_size
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        ok = True
        total = len(chunks)
        for index, chunk in enumerate(chunks, 1):
            if total > 1:
                chunk = f"[{index}/{total}]\n" + chunk
            ok = self.send(chunk) and ok
        return ok
