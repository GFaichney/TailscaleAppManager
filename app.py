from __future__ import annotations

import atexit
import os
import platform
import shutil
import signal
import subprocess
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "apps_config.yaml"
INSTALLED_APPS_DIR = BASE_DIR / "installed_apps"
LOG_LIMIT = 300
EVENT_LOGS: deque[dict[str, Any]] = deque(maxlen=LOG_LIMIT)

app = Flask(__name__)
_shutdown_done = False


def wrapper_port() -> int:
    return int(os.getenv("WRAPPER_PORT", "8080"))


def log_event(level: str, message: str, app_name: str | None = None, details: dict[str, Any] | None = None) -> None:
    EVENT_LOGS.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "app_name": app_name,
            "details": details or {},
        }
    )


def restart_app_entry(app_entry: dict[str, Any]) -> None:
    app_folder = app_entry.get("application_folder")
    executable = app_entry.get("executable") or "./run.sh"
    web_path = app_entry.get("web_path")
    app_port = app_entry.get("application_port")
    app_name = app_entry.get("application_name", "unknown")

    if not app_folder or not web_path or not isinstance(app_port, int):
        raise RuntimeError("Missing application_folder, web_path, or valid application_port")

    folder_path = Path(app_folder).expanduser().resolve()
    if not folder_path.exists() or not folder_path.is_dir():
        raise FileNotFoundError(f"Application folder does not exist: {folder_path}")

    pid = app_entry.get("pid")
    if isinstance(pid, int):
        stop_process(pid)
        log_event("info", "Stopped existing process before restart.", app_name, {"pid": pid})

    proc = launch_application(folder_path, executable)
    app_entry["pid"] = proc.pid
    tailscale_set_path(web_path, app_port)
    log_event("info", "Application started and mapped with tailscale serve.", app_name, {"pid": proc.pid, "web_path": web_path, "port": app_port})


def get_current_branch(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to detect current branch: {result.stderr.strip()}")
    return result.stdout.strip()


def get_behind_commit_count(repo_path: Path, branch: str) -> int:
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch_result.returncode != 0:
        raise RuntimeError(f"git fetch failed: {fetch_result.stderr.strip()}")

    count_result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if count_result.returncode != 0:
        raise RuntimeError(f"Unable to compare revisions: {count_result.stderr.strip()}")

    try:
        return int(count_result.stdout.strip() or "0")
    except ValueError as exc:
        raise RuntimeError("Invalid revision count returned by git.") from exc


def pull_latest(repo_path: Path, branch: str) -> None:
    result = subprocess.run(
        ["git", "pull", "origin", branch],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git pull failed: {result.stderr.strip()}")


def update_github_status_for_app(app_entry: dict[str, Any]) -> bool:
    github_location = app_entry.get("github_location")
    if not github_location:
        app_entry["update_available"] = False
        app_entry["pending_commits"] = 0
        return False

    folder = app_entry.get("application_folder")
    app_name = app_entry.get("application_name", "unknown")
    if not folder:
        app_entry["update_available"] = False
        app_entry["pending_commits"] = 0
        log_event("error", "Cannot check GitHub updates because application_folder is missing.", app_name)
        return False

    repo_path = Path(folder).expanduser().resolve()
    if not repo_path.exists() or not (repo_path / ".git").exists():
        app_entry["update_available"] = False
        app_entry["pending_commits"] = 0
        log_event("error", "Cannot check GitHub updates because application folder is not a git repository.", app_name)
        return False

    try:
        branch = get_current_branch(repo_path)
        behind_count = get_behind_commit_count(repo_path, branch)
        app_entry["update_available"] = behind_count > 0
        app_entry["pending_commits"] = behind_count
        log_event(
            "info",
            "Checked GitHub update status.",
            app_name,
            {"update_available": behind_count > 0, "pending_commits": behind_count},
        )
        return True
    except Exception as exc:
        app_entry["update_available"] = False
        app_entry["pending_commits"] = 0
        log_event("error", f"GitHub update status check failed: {exc}", app_name)
        return False


def ensure_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("apps: []\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    ensure_config()
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("apps", [])
    return data


def save_config(data: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def validate_app_input(payload: dict[str, Any]) -> tuple[bool, str | None]:
    required_fields = ["application_name", "application_port", "web_path"]
    for field in required_fields:
        if not payload.get(field):
            return False, f"Missing required field: {field}"

    folder = payload.get("application_folder")
    github = payload.get("github_location")

    if not folder and not github:
        return False, "Either application_folder or github_location is required."

    if folder and github:
        return False, "application_folder and github_location are mutually exclusive."

    try:
        port = int(payload["application_port"])
        if port < 1 or port > 65535:
            raise ValueError
    except ValueError:
        return False, "application_port must be an integer between 1 and 65535."

    return True, None


def validate_port_conflict(payload: dict[str, Any], apps: list[dict[str, Any]]) -> tuple[bool, str | None]:
    requested_port = int(payload["application_port"])

    if requested_port == wrapper_port():
        return False, "application_port conflicts with the wrapper application's port."

    if any(item.get("application_port") == requested_port for item in apps):
        return False, "application_port conflicts with an existing managed application."

    return True, None


def command_for_script(script_path: Path) -> list[str]:
    suffix = script_path.suffix.lower()
    system = platform.system().lower()

    if suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]

    if suffix == ".sh":
        shell = shutil.which("bash") or shutil.which("sh")
        if shell:
            return [shell, str(script_path)]

    if system == "windows" and suffix in {".bat", ".cmd"}:
        return [str(script_path)]

    return [str(script_path)]


def run_setup_script(app_folder: Path, setup_executable: str) -> None:
    setup_path = (app_folder / setup_executable).resolve()
    if not setup_path.exists():
        raise FileNotFoundError(f"Setup executable not found: {setup_path}")

    cmd = command_for_script(setup_path)
    result = subprocess.run(
        cmd,
        cwd=str(app_folder),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Setup script failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


def launch_application(app_folder: Path, app_executable: str) -> subprocess.Popen[Any]:
    run_path = (app_folder / app_executable).resolve()
    if not run_path.exists():
        raise FileNotFoundError(f"Run executable not found: {run_path}")

    cmd = command_for_script(run_path)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(app_folder),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if platform.system().lower() == "windows":
        # Create a new process group so cleanup can terminate the whole tree.
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(
        cmd,
        **popen_kwargs,
    )


def tailscale_set_path(web_path: str, port: int) -> None:
    cmd = [
        "tailscale",
        "serve",
        "--bg",
        "--set-path",
        f"/{web_path}",
        f"http://127.0.0.1:{port}",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=False)


def tailscale_drain() -> None:
    subprocess.run(["tailscale", "serve", "drain"], capture_output=True, text=True, check=False)


def clone_repository(github_location: str) -> Path:
    INSTALLED_APPS_DIR.mkdir(parents=True, exist_ok=True)

    repo_name = github_location.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    target = INSTALLED_APPS_DIR / repo_name
    if target.exists():
        target = INSTALLED_APPS_DIR / f"{repo_name}-{uuid.uuid4().hex[:8]}"

    result = subprocess.run(
        ["git", "clone", github_location, str(target)],
        cwd=str(INSTALLED_APPS_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Git clone failed.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    return target


def stop_process(pid: int) -> None:
    if platform.system().lower() == "windows":
        # taskkill with /T ensures child processes created by script wrappers are also stopped.
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return

    try:
        if platform.system().lower() != "windows":
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return


def launch_all_configured_apps() -> None:
    data = load_config()
    updated = False

    for app_entry in data.get("apps", []):
        app_folder = app_entry.get("application_folder")
        executable = app_entry.get("executable") or "./run.sh"
        web_path = app_entry.get("web_path")
        app_port = app_entry.get("application_port")

        if not app_folder or not web_path or not isinstance(app_port, int):
            continue

        folder_path = Path(app_folder).expanduser().resolve()
        if not folder_path.exists() or not folder_path.is_dir():
            continue

        try:
            restart_app_entry(app_entry)
            updated = True
        except Exception:
            # Continue launching remaining apps even if one fails.
            log_event("error", "Failed to launch application during wrapper startup.", app_entry.get("application_name", "unknown"))
            continue

        if app_entry.get("github_location"):
            if update_github_status_for_app(app_entry):
                updated = True

    if updated:
        save_config(data)
        log_event("info", "Wrapper startup completed and application state was updated.")


def stop_all_configured_apps() -> None:
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    data = load_config()
    changed = False

    tailscale_drain()

    for app_entry in data.get("apps", []):
        pid = app_entry.get("pid")
        if isinstance(pid, int):
            stop_process(pid)
            log_event("info", "Stopped managed application during wrapper shutdown.", app_entry.get("application_name", "unknown"), {"pid": pid})
            app_entry["pid"] = None
            changed = True

    if changed:
        save_config(data)

    log_event("info", "Wrapper shutdown completed.")


def _handle_shutdown_signal(*_: Any) -> None:
    stop_all_configured_apps()
    raise SystemExit(0)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/apps")
def get_apps() -> Any:
    return jsonify(load_config()["apps"])


@app.get("/api/logs")
def get_logs() -> Any:
    return jsonify(list(EVENT_LOGS))


@app.post("/api/apps")
def add_app() -> Any:
    payload = request.get_json(silent=True) or {}
    ok, error = validate_app_input(payload)
    if not ok:
        log_event("error", f"Add application validation failed: {error}")
        return jsonify({"error": error}), 400

    data = load_config()

    ok, error = validate_port_conflict(payload, data["apps"])
    if not ok:
        log_event("error", f"Add application rejected due to port conflict: {error}", payload.get("application_name"))
        return jsonify({"error": error}), 409

    app_folder: Path
    cloned_from_github = False

    try:
        if payload.get("github_location"):
            app_folder = clone_repository(payload["github_location"])
            cloned_from_github = True
        else:
            app_folder = Path(payload["application_folder"]).expanduser().resolve()
            if not app_folder.exists() or not app_folder.is_dir():
                return jsonify({"error": "application_folder does not exist."}), 400

        setup_executable = payload.get("setup_executable") or "./setup.sh"
        executable = payload.get("executable") or "./run.sh"

        run_setup_script(app_folder, setup_executable)
        proc = launch_application(app_folder, executable)
        tailscale_set_path(payload["web_path"], int(payload["application_port"]))

        app_record = {
            "id": str(uuid.uuid4()),
            "application_name": payload["application_name"],
            "application_port": int(payload["application_port"]),
            "web_path": payload["web_path"],
            "executable": executable,
            "setup_executable": setup_executable,
            "application_folder": str(app_folder),
            "github_location": payload.get("github_location"),
            "pid": proc.pid,
            "cloned_from_github": cloned_from_github,
            "update_available": False,
            "pending_commits": 0,
        }

        if app_record["github_location"]:
            update_github_status_for_app(app_record)

        data["apps"].append(app_record)
        save_config(data)
        log_event("info", "Application added and started.", app_record["application_name"], {"pid": proc.pid, "web_path": app_record["web_path"], "port": app_record["application_port"]})

        return jsonify(app_record), 201
    except Exception as exc:
        log_event("error", f"Failed to add application: {exc}", payload.get("application_name"))
        return jsonify({"error": str(exc)}), 500


@app.delete("/api/apps/<app_id>")
def delete_app(app_id: str) -> Any:
    data = load_config()
    apps = data.get("apps", [])

    app_entry = next((item for item in apps if item.get("id") == app_id), None)
    if not app_entry:
        log_event("error", "Delete failed because application was not found.", details={"app_id": app_id})
        return jsonify({"error": "Application not found."}), 404

    tailscale_drain()

    pid = app_entry.get("pid")
    if isinstance(pid, int):
        stop_process(pid)
        log_event("info", "Stopped application process during delete.", app_entry.get("application_name", "unknown"), {"pid": pid})

    data["apps"] = [item for item in apps if item.get("id") != app_id]
    save_config(data)
    log_event("info", "Application deleted.", app_entry.get("application_name", "unknown"), {"app_id": app_id})

    return jsonify({"deleted": app_id})


@app.post("/api/apps/check-updates")
def check_updates() -> Any:
    data = load_config()
    results: list[dict[str, Any]] = []
    changed = False

    for app_entry in data.get("apps", []):
        app_name = app_entry.get("application_name", "unknown")
        github_location = app_entry.get("github_location")

        if not github_location:
            continue

        folder = app_entry.get("application_folder")
        if not folder:
            results.append({"application_name": app_name, "status": "error", "message": "Missing application_folder"})
            log_event("error", "Update check failed due to missing application_folder.", app_name)
            continue

        repo_path = Path(folder).expanduser().resolve()
        if not repo_path.exists() or not (repo_path / ".git").exists():
            results.append({"application_name": app_name, "status": "error", "message": "Application folder is not a git repository"})
            log_event("error", "Update check failed because application folder is not a git repository.", app_name)
            continue

        try:
            branch = get_current_branch(repo_path)
            behind_count = get_behind_commit_count(repo_path, branch)
            if behind_count <= 0:
                app_entry["update_available"] = False
                app_entry["pending_commits"] = 0
                changed = True
                results.append({"application_name": app_name, "status": "up-to-date", "message": "No updates found"})
                log_event("info", "Update check found no new commits.", app_name)
                continue

            pull_latest(repo_path, branch)
            restart_app_entry(app_entry)
            app_entry["update_available"] = False
            app_entry["pending_commits"] = 0
            changed = True
            results.append(
                {
                    "application_name": app_name,
                    "status": "updated",
                    "message": f"Pulled {behind_count} commit(s) and restarted application",
                }
            )
            log_event("info", "Application updated from GitHub and restarted.", app_name, {"commits": behind_count})
        except Exception as exc:
            results.append({"application_name": app_name, "status": "error", "message": str(exc)})
            log_event("error", f"Update check failed: {exc}", app_name)

    if changed:
        save_config(data)

    return jsonify({"results": results})


if __name__ == "__main__":
    ensure_config()
    log_event("info", "Wrapper startup initiated.")

    launch_all_configured_apps()
    atexit.register(stop_all_configured_apps)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    app.run(host="0.0.0.0", port=wrapper_port(), debug=False)
