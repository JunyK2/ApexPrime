from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from .utils import json_safe

log = logging.getLogger("apexprime.db")


class SupabaseREST:
    """Small PostgREST client using the service-role key; worker-side only."""

    def __init__(self, url: str, service_role_key: str, timeout: int = 25):
        if not url or not service_role_key:
            raise ValueError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios")
        self.project_url = url.rstrip("/")
        self.base = self.project_url + "/rest/v1"
        self.storage_base = self.project_url + "/storage/v1"
        self.service_role_key = service_role_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method: str, table: str, *, params: dict[str, Any] | None = None,
                 body: Any = None, prefer: str = "return=representation") -> Any:
        headers = {"Prefer": prefer}
        response = self.session.request(
            method,
            f"{self.base}/{quote(table, safe='')}",
            params=params,
            json=json_safe(body) if body is not None else None,
            headers=headers,
            timeout=self.timeout,
        )
        if not response.ok:
            safe_body = response.text[:900]
            raise RuntimeError(f"Supabase {method} {table} HTTP {response.status_code}: {safe_body}")
        if not response.text.strip():
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def select(self, table: str, filters: dict[str, str] | None = None,
               *, select: str = "*", order: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": select}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        return self._request("GET", table, params=params) or []

    def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self._request("POST", table, body=rows, prefer="return=representation")
        return result or []

    def update(self, table: str, filters: dict[str, str], values: dict[str, Any]) -> list[dict[str, Any]]:
        return self._request("PATCH", table, params=filters, body=values, prefer="return=representation") or []

    def delete(self, table: str, filters: dict[str, str]) -> Any:
        return self._request("DELETE", table, params=filters, prefer="return=minimal")

    def upload_public_image(self, bucket: str, object_path: str, data: bytes,
                            content_type: str) -> str:
        """Upload a market-chart image to a public Storage bucket and return its URL.

        The bucket is intentionally public because these objects contain only public
        market charts. Never upload secrets, account information, or user content here.
        """
        if not bucket or not object_path or not data:
            raise ValueError("Bucket, caminho e imagem são obrigatórios")
        if content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError(f"Tipo de imagem não permitido: {content_type}")

        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        bucket_url = f"{self.storage_base}/bucket/{quote(bucket, safe='')}"
        check = self.session.get(bucket_url, headers=headers, timeout=self.timeout)
        if check.status_code == 404:
            created = self.session.post(
                f"{self.storage_base}/bucket",
                headers=headers,
                json={
                    "id": bucket,
                    "name": bucket,
                    "public": True,
                    "file_size_limit": 10_000_000,
                    "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"],
                },
                timeout=self.timeout,
            )
            if not created.ok and created.status_code != 409:
                raise RuntimeError(
                    f"Supabase Storage create bucket HTTP {created.status_code}: {created.text[:700]}"
                )
        elif not check.ok:
            raise RuntimeError(
                f"Supabase Storage check bucket HTTP {check.status_code}: {check.text[:700]}"
            )

        # Encode each path component separately so slashes remain folder separators.
        encoded_path = "/".join(quote(part, safe="") for part in object_path.strip("/").split("/"))
        upload_url = f"{self.storage_base}/object/{quote(bucket, safe='')}/{encoded_path}"
        upload_headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
            "Cache-Control": "public, max-age=31536000, immutable",
        }
        uploaded = self.session.post(
            upload_url, headers=upload_headers, data=data, timeout=self.timeout
        )
        if not uploaded.ok:
            raise RuntimeError(
                f"Supabase Storage upload HTTP {uploaded.status_code}: {uploaded.text[:700]}"
            )
        return f"{self.storage_base}/object/public/{quote(bucket, safe='')}/{encoded_path}"

    def settings(self) -> dict[str, Any]:
        rows = self.select("apex_settings", {"id": "eq.1"}, limit=1)
        if not rows:
            raise RuntimeError("apex_settings não possui a linha id=1; execute a migration inicial")
        return rows[0]

    def prompts(self) -> dict[str, Any]:
        rows = self.select("apex_prompts", {"id": "eq.1"}, limit=1)
        if not rows:
            raise RuntimeError("apex_prompts não possui a linha id=1; execute a migration inicial")
        return rows[0]

    def active_account(self) -> dict[str, Any]:
        rows = self.select("paper_accounts", {"is_active": "eq.true"}, limit=1)
        if not rows:
            raise RuntimeError("Nenhuma conta virtual ativa em paper_accounts")
        return rows[0]

    def log(self, level: str, component: str, message: str,
            *, run_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        try:
            self.insert("apex_logs", {
                "run_id": run_id,
                "level": level.upper(),
                "component": component,
                "message": message[:1500],
                "details": details or {},
            })
        except Exception:
            log.exception("Falha ao persistir log no Supabase")

    def service_check(self, service: str, status: str, message: str,
                      *, latency_ms: int | None = None, run_id: str | None = None,
                      details: dict[str, Any] | None = None) -> None:
        self.insert("service_checks", {
            "run_id": run_id,
            "service": service,
            "status": status,
            "latency_ms": latency_ms,
            "message": message[:500],
            "details": details or {},
        })
