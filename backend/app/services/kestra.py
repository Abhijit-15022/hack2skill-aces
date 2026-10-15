"""Thin client for the Kestra REST API (Kestra 2.x, OSS tenant "main")."""
import logging
import os
import re
from pathlib import Path

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=f"{settings.kestra_url}/api/v1/{settings.kestra_tenant}",
        auth=(settings.kestra_user, settings.kestra_password),
        timeout=20,
    )


def is_up() -> bool:
    try:
        r = httpx.get(f"{settings.kestra_url}/ping", timeout=3)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


def _render_flow(source: str) -> str:
    return (source
            .replace("__RELAY_API__", settings.api_internal_url)
            .replace("__RELAY_TOKEN__", settings.relay_ingest_token))


def deploy_flow(source: str) -> str:
    source = _render_flow(source)
    ns = re.search(r"^namespace:\s*(\S+)", source, re.M).group(1)
    fid = re.search(r"^id:\s*(\S+)", source, re.M).group(1)
    headers = {"Content-Type": "application/x-yaml"}
    with _client() as c:
        r = c.get(f"/flows/{ns}/{fid}")
        if r.status_code == 200:
            r = c.put(f"/flows/{ns}/{fid}", content=source, headers=headers)
        else:
            r = c.post("/flows", content=source, headers=headers)
        r.raise_for_status()
    return f"{ns}.{fid}"


def deploy_all_flows() -> list[str]:
    deployed = []
    root = Path(settings.kestra_flows_dir)
    for path in sorted(root.rglob("*.yml")):
        try:
            deployed.append(deploy_flow(path.read_text()))
        except httpx.HTTPError as exc:
            log.error("Could not deploy Kestra flow %s: %s", path.name, getattr(exc, "response", None) and exc.response.text)
    return deployed


def get_flow_source(namespace: str, flow_id: str) -> str | None:
    with _client() as c:
        r = c.get(f"/flows/{namespace}/{flow_id}", params={"source": "true"})
        if r.status_code != 200:
            return None
        return r.json().get("source")


def get_execution(execution_id: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/executions/{execution_id}")
        return r.json() if r.status_code == 200 else None


def get_logs(execution_id: str) -> list[dict]:
    with _client() as c:
        r = c.get(f"/logs/{execution_id}")
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else data.get("results", [])


def run_flow(namespace: str, flow_id: str) -> str | None:
    with _client() as c:
        r = c.post(f"/executions/{namespace}/{flow_id}")
        if r.status_code >= 300:
            log.error("Kestra run %s.%s failed: %s %s", namespace, flow_id, r.status_code, r.text[:300])
            return None
        return r.json().get("id")


def ui_execution_url(namespace: str, flow_id: str, execution_id: str) -> str:
    public = os.environ.get("KESTRA_PUBLIC_URL", "http://localhost:8080")
    return f"{public}/ui/{settings.kestra_tenant}/executions/{namespace}/{flow_id}/{execution_id}"
