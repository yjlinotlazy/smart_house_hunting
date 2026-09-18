"""ASGI request telemetry for Smart House Hunting."""
from __future__ import annotations
import json, re, time
from datetime import datetime
from pathlib import Path

_INTEGER_PATH = re.compile(r"/\d+(?=/|$)")
def _route(path: str) -> str:
    if path.startswith("/assets/"): return "/assets/:path"
    if path.startswith("/api/"):
        parts = path.split("/"); return "/".join(parts[:3]) + ("/:path" if len(parts) > 3 else "")
    return _INTEGER_PATH.sub("/:id", path or "/")
class RequestLogger:
    def __init__(self, root: Path, app_id: str) -> None: self.directory = root / "server_logs" / app_id / "raw"
    def record(self, *, path: str, method: str, status: int, request_size: int, response_size: int, started_at: float) -> None:
        if path == "/favicon.ico" or path.startswith(("/assets/", "/static/")): return
        event = {"timestamp": datetime.fromtimestamp(started_at).astimezone().isoformat(), "method": method, "route": _route(path), "status": int(status), "request_bytes": int(request_size), "response_bytes": int(response_size), "latency_ms": round(max(0.0, (time.time() - started_at) * 1000), 3)}
        try:
            self.directory.mkdir(parents=True, exist_ok=True); file = self.directory / f"{datetime.fromtimestamp(started_at).date().isoformat()}.jsonl"
            with file.open("a", encoding="utf-8") as stream: stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception: pass
class TelemetryMiddleware:
    def __init__(self, app): self.app, self.logger = app, RequestLogger(Path(__file__).resolve().parents[2], "smart_house_hunting")
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http": return await self.app(scope, receive, send)
        started_at = time.time(); status = 500; response_size = 0; headers = dict(scope.get("headers", []))
        try: request_size = int(headers.get(b"content-length", b"0") or 0)
        except (TypeError, ValueError): request_size = 0
        async def send_wrapped(message):
            nonlocal status, response_size
            if message.get("type") == "http.response.start": status = int(message.get("status", 500))
            if message.get("type") == "http.response.body": response_size += len(message.get("body", b""))
            await send(message)
        try: await self.app(scope, receive, send_wrapped)
        finally: self.logger.record(path=scope.get("path", "/"), method=scope.get("method", "UNKNOWN"), status=status, request_size=request_size, response_size=response_size, started_at=started_at)
