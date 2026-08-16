"""Robinhood MCP authentication: bearer token or interactive OAuth.

This module never reads another application's credential store. It accepts a
bearer token from the environment or performs the standard MCP OAuth flow and
stores the resulting token data in a user-selected file with restrictive
permissions.
"""

from __future__ import annotations

import json
import os
import stat
import webbrowser
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


class JsonTokenStorage:
    """Minimal file-backed storage compatible with MCP OAuth token payloads."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except ValueError:
            return None

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n")
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    async def get_tokens(self):
        payload = self._read()
        if payload is None:
            return None
        from mcp.shared.auth import OAuthToken

        return OAuthToken(**payload.get("tokens", payload))

    async def set_tokens(self, tokens) -> None:
        payload = self._read() or {}
        payload["tokens"] = tokens.model_dump(mode="json")
        self._write(payload)

    async def get_client_info(self):
        payload = self._read()
        if payload is None or "client_info" not in payload:
            return None
        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull(**payload["client_info"])

    async def set_client_info(self, client_info) -> None:
        payload = self._read() or {}
        payload["client_info"] = client_info.model_dump(mode="json")
        self._write(payload)

    @staticmethod
    def has_tokens(path: str | Path) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        try:
            return bool(json.loads(p.read_text()).get("tokens"))
        except (ValueError, OSError):
            return False


async def _wait_for_callback_file(path: Path, *, timeout_seconds: int = 900) -> str:
    """Poll a callback file until it contains a URL (avoids stdin across processes)."""
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        if path.exists():
            content = path.read_text().strip()
            if content:
                return content
        if loop.time() > deadline:
            raise TimeoutError(f"timed out waiting for callback URL in {path}")
        await asyncio.sleep(2)


def oauth_async_client(
    *,
    server_url: str,
    storage: JsonTokenStorage,
    callback_file: str | Path | None = None,
    client_name: str = "robinhood-mcp-cli",
) -> AsyncIterator[Any]:
    """Yield an httpx2 AsyncClient configured with the OAuth provider.

    When ``callback_file`` is set the redirect handler writes the authorization
    URL to ``<callback_file>.url`` and the callback handler polls the file
    instead of reading stdin, which lets an agent drive the browser step in a
    separate process.
    """
    from contextlib import asynccontextmanager

    from pydantic import AnyUrl

    callback_path = Path(callback_file) if callback_file else None

    @asynccontextmanager
    async def _factory():
        import httpx2
        from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata

        async def redirect_handler(auth_url: str) -> None:
            print(f"Opening Robinhood authorization URL: {auth_url}", flush=True)
            if callback_path is not None:
                write_url = Path(str(callback_path) + ".url")
                write_url.write_text(auth_url + "\n")
                print(f"Authorization URL written to {write_url}", flush=True)
            webbrowser.open(auth_url)

        async def callback_handler() -> AuthorizationCodeResult:
            if callback_path is not None:
                callback_url = await _wait_for_callback_file(callback_path)
            else:
                callback_url = input("Paste the completed Robinhood callback URL: ")
            params = parse_qs(urlparse(callback_url).query)
            return AuthorizationCodeResult(
                code=params["code"][0],
                state=params.get("state", [None])[0],
                iss=params.get("iss", [None])[0],
            )

        oauth = OAuthClientProvider(
            server_url=server_url,
            client_metadata=OAuthClientMetadata(
                client_name=client_name,
                redirect_uris=[AnyUrl("http://localhost:8765/callback")],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="user",
            ),
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        client = httpx2.AsyncClient(auth=oauth, follow_redirects=True)
        try:
            yield client
        finally:
            await client.aclose()

    return _factory()


def bearer_async_client(token: str) -> AsyncIterator[Any]:
    """Yield an httpx2 AsyncClient using a static bearer token."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _factory():
        import httpx2

        client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, follow_redirects=True
        )
        try:
            yield client
        finally:
            await client.aclose()

    return _factory()


def resolve_client_factory(
    *,
    server_url: str,
    token_file: str | Path,
    bearer_token_env: str,
    callback_file: str | Path | None = None,
    client_name: str = "robinhood-mcp-cli",
):
    """Return the httpx2 async-client factory for a Robinhood MCP connection.

    A bearer token from ``bearer_token_env`` short-circuits OAuth. Otherwise an
    OAuth provider is returned which refreshes stored tokens or, when the token
    file holds none, performs the full interactive authorization-code flow.
    """
    token = os.environ.get(bearer_token_env)
    if token:
        return bearer_async_client(token)
    return oauth_async_client(
        server_url=server_url,
        storage=JsonTokenStorage(token_file),
        callback_file=callback_file,
        client_name=client_name,
    )