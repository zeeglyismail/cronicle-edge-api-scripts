"""Thin httpx wrapper around the Cronicle (Edge Fork) REST API.

All endpoints are POST {base}/api/app/<endpoint>/v1 with X-API-Key header.
Successful responses have code == 0; anything else raises CronicleAPIError.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import HostConfig


class CronicleAPIError(RuntimeError):
    """Cronicle returned a non-zero `code` in the response body."""

    def __init__(self, code: Any, description: str, endpoint: str):
        self.code = code
        self.description = description
        self.endpoint = endpoint
        super().__init__(f"{endpoint}: code={code!r} — {description}")


class CronicleClient:
    """One client per host. Use as a context manager so the httpx pool closes."""

    def __init__(self, host: HostConfig):
        self._host = host
        self._client = httpx.Client(
            base_url=f"{host.base_url}/api/app",
            headers={
                "X-API-Key": host.api_key,
                "Content-Type": "application/json",
            },
            timeout=host.request_timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CronicleClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _post(self, endpoint: str, body: dict) -> dict:
        # One retry on transient failure (5xx, JSON decode, read errors).
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._client.post(f"/{endpoint}", json=body)
                if 500 <= resp.status_code < 600:
                    last_exc = httpx.HTTPStatusError(
                        f"{endpoint} returned HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
                last_exc = e
                continue
            except ValueError as e:
                # JSON decode failure
                last_exc = e
                continue

            code = data.get("code")
            if code != 0:
                raise CronicleAPIError(
                    code=code,
                    description=str(data.get("description", "(no description)")),
                    endpoint=endpoint,
                )
            return data

        assert last_exc is not None
        raise last_exc

    # ---- endpoint methods -------------------------------------------------

    def list_events(self, limit: int = 5000) -> list[dict]:
        """GET-ish: list all scheduled events (Cronicle returns up to `limit`)."""
        return self._post("get_schedule/v1", {"limit": limit}).get("rows", [])

    def get_event(self, event_id: str) -> dict:
        """Fetch one full event by id. Returns the inner `event` object, not the wrapper."""
        return self._post("get_event/v1", {"id": event_id}).get("event", {})

    def delete_event(self, event_id: str) -> dict:
        """Permanently delete one event. Returns the API response dict."""
        return self._post("delete_event/v1", {"id": event_id})

    def update_event(self, event_id: str, fields: dict) -> dict:
        """Merge-update an event. Cronicle replaces only the fields you send,
        EXCEPT for `params` which is replaced wholesale (GET-then-PUT it).
        """
        return self._post("update_event/v1", {"id": event_id, **fields})

    def create_event(self, payload: dict) -> str:
        """Create a new event. Returns the new event's id."""
        return self._post("create_event/v1", payload).get("id", "")

    # ---- jobs (runtime) ---------------------------------------------------

    def get_active_jobs(self) -> dict[str, dict]:
        """Map of {job_id: job_dict} for currently in-progress jobs.

        Cronicle scrubs the `params` field server-side (may contain secrets).
        Manager privilege required.
        """
        return self._post("get_active_jobs/v1", {}).get("jobs", {})

    def run_event(self, event_id: str) -> list[str]:
        """Fire one event immediately ("Run Now"). Requires run_events privilege.

        Works on disabled events too — Cronicle treats a manual run as
        independent of the enabled flag. Returns the new job id(s).

        Common non-zero codes come back as CronicleAPIError:
          max_children        event already running and concurrency is 1
          no_matching_servers target group's regexp matches no live server
        """
        return self._post("run_event/v1", {"id": event_id}).get("ids", [])

    def abort_job(self, job_id: str) -> dict:
        """Abort one running job by id. Requires manager + abort_events privilege.

        no_rewind=1 is sent server-side (matches Cronicle UI behavior) so the
        next scheduled run still happens at its normal time.
        """
        return self._post("abort_job/v1", {"id": job_id})

    def abort_jobs(self, filter_params: dict, no_rewind: int = 1) -> dict:
        """Bulk abort. filter_params keys: event, category, target, plugin.

        Requires manager + abort_events privilege. Detached jobs are skipped
        server-side. no_rewind=1 (default) preserves cursor; set 0 to allow
        catch_up to re-run aborted occurrences.
        """
        body = dict(filter_params)
        body["no_rewind"] = no_rewind
        return self._post("abort_jobs/v1", body)

    # ---- categories -------------------------------------------------------

    def list_categories(self, limit: int = 1000) -> list[dict]:
        """Returns rows from get_categories/v1. Requires manager privilege."""
        return self._post("get_categories/v1", {"limit": limit}).get("rows", [])

    def create_category(
        self,
        title: str,
        max_children: int = 1,
        description: str | None = None,
        color: str | None = None,
        enabled: int = 1,
    ) -> str:
        """Create a category. Requires admin privilege. Returns the new id."""
        body: dict = {"title": title, "max_children": max_children, "enabled": enabled}
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        return self._post("create_category/v1", body).get("id", "")

    # ---- server groups ----------------------------------------------------

    def create_server_group(self, title: str, regexp: str) -> str:
        """Create a server group. Requires admin privilege. Returns the new id.

        `regexp` is a JS regex that matches server hostnames. Use ".*" to match
        all servers, or "^nomatch$" for a group that no server can satisfy
        (useful for events that should never actually run).
        """
        body = {"title": title, "regexp": regexp}
        return self._post("create_server_group/v1", body).get("id", "")
