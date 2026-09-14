from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REMOTE_APP_PATH = "/"
REMOTE_HTTPS_PORT = 8443


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


@dataclass(frozen=True)
class RemoteStatus:
    installed: bool
    logged_in: bool
    backend_state: str
    serve_active: bool
    serve_url: str
    tailscale_path: str
    detail: str = ""


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "cp932", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def find_tailscale_executable() -> Path | None:
    found = shutil.which("tailscale.exe") or shutil.which("tailscale")
    if found:
        return Path(found).resolve()
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            candidate = Path(base) / "Tailscale" / "tailscale.exe"
            if candidate.is_file():
                return candidate.resolve()
    return None


def run_tailscale(arguments: list[str], timeout: float = 25.0) -> CommandResult:
    executable = find_tailscale_executable()
    if not executable:
        return CommandResult(127, "Tailscale is not installed.")
    try:
        completed = subprocess.run([str(executable), *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=timeout, creationflags=_creation_flags(), check=False)
        return CommandResult(completed.returncode, _decode(completed.stdout or b""))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, _decode(exc.stdout or b"") + "\nCommand timed out.")
    except OSError as exc:
        return CommandResult(126, f"{type(exc).__name__}: {exc}")


def parse_backend_state(status_json: str) -> str:
    try:
        data = json.loads(status_json)
    except json.JSONDecodeError:
        return ""
    return str(data.get("BackendState") or "") if isinstance(data, dict) else ""


def parse_serve_url(text: str) -> str:
    match = re.search(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/)?", text)
    return match.group(0).rstrip("/") if match else ""


def parse_app_serve_url(text: str, https_port: int = REMOTE_HTTPS_PORT) -> str:
    pattern = rf"https://[A-Za-z0-9.-]+:{int(https_port)}(?:/)?"
    match = re.search(pattern, text)
    return match.group(0).rstrip("/") if match else ""


def build_remote_app_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    return cleaned + "/" if cleaned else ""


def get_remote_status() -> RemoteStatus:
    executable = find_tailscale_executable()
    if not executable:
        return RemoteStatus(False, False, "NotInstalled", False, "", "")
    status_result = run_tailscale(["status", "--json"], timeout=12.0)
    backend_state = parse_backend_state(status_result.output)
    logged_in = status_result.returncode == 0 and backend_state.casefold() == "running"
    serve_result = run_tailscale(["serve", "status"], timeout=12.0)
    app_url = build_remote_app_url(parse_app_serve_url(serve_result.output))
    return RemoteStatus(
        True,
        logged_in,
        backend_state or "Unknown",
        serve_result.returncode == 0 and bool(app_url),
        app_url,
        str(executable),
        serve_result.output.strip() if serve_result.returncode else "",
    )


def enable_remote_access(port: int) -> tuple[bool, str, str]:
    status = get_remote_status()
    if not status.installed:
        return False, "", "Tailscaleがインストールされていません。"
    if not status.logged_in:
        return False, "", "Tailscaleへのログインが必要です。"
    result = run_tailscale(
        ["serve", "--yes", "--bg", f"--https={REMOTE_HTTPS_PORT}", str(int(port))],
        timeout=30.0,
    )
    if result.returncode != 0:
        return False, "", result.output.strip() or "Tailscale Serveを有効にできませんでした。"
    current = get_remote_status()
    url = current.serve_url or build_remote_app_url(parse_app_serve_url(result.output))
    return bool(url), url, "外部接続を有効にしました。" if url else "HTTPS URLを取得できませんでした。"


def disable_remote_access() -> CommandResult:
    return run_tailscale(["serve", "--yes", f"--https={REMOTE_HTTPS_PORT}", "off"], timeout=20.0)
