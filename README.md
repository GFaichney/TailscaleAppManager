# Tailscale Multi-Server Wrapper

A Python web application that manages multiple local web apps and exposes each one on its own Tailscale Serve path.

## What This App Does

This project provides a single dashboard and API to:

- Add and remove managed applications.
- Clone an app from GitHub or use an existing local folder.
- Run each app's setup script.
- Start each app in the background and track its PID.
- Publish each app behind Tailscale Serve using a unique URL path.
- Persist configuration in YAML.
- Relaunch configured apps on wrapper startup.
- Stop managed apps on wrapper shutdown.

## Managed App Model

Each managed application can include:

- `application_name` (required)
- `application_port` (required)
- `web_path` (required)
- `application_folder` (optional)
- `github_location` (optional)
- `executable` (optional, default `./run.sh`)
- `setup_executable` (optional, default `./setup.sh`)

Rules:

- Exactly one of `application_folder` or `github_location` must be provided.
- `application_port` cannot conflict with another managed app.
- `application_port` cannot conflict with the wrapper app port.

## Project Structure

- `app.py`: Flask backend and process/tailscale lifecycle logic
- `templates/index.html`: Web UI markup
- `static/style.css`: Responsive styling
- `static/app.js`: UI behavior and API calls
- `apps_config.yaml`: Persistent app configuration
- `setup.ps1`, `setup.sh`: Environment setup scripts
- `run.ps1`, `run.sh`: Wrapper run scripts

## Prerequisites

- Python 3.10+ (Python 3.12 tested)
- Git (for GitHub clone workflow)
- Tailscale CLI installed and authenticated (`tailscale` command available)

## Setup

### Windows (PowerShell)

```powershell
.\setup.ps1
```

### Linux/macOS (bash)

```bash
chmod +x setup.sh run.sh
./setup.sh
```

The setup scripts create `.venv` if needed, upgrade `pip`, and install packages from `requirements.txt`.

## Run

### Windows (PowerShell)

```powershell
.\run.ps1
```

### Linux/macOS (bash)

```bash
./run.sh
```

By default, the wrapper runs on port `8080`.

Open:

- `http://127.0.0.1:8080`

## Environment Variables

You can change wrapper settings with these environment variables:

- `WRAPPER_PORT` (default `8080`)
- `WRAPPER_WEB_PATH` (default `wrapper`) used by `run.ps1` and `run.sh` when setting Tailscale Serve for the wrapper itself

Windows example:

```powershell
$env:WRAPPER_PORT = "8090"
$env:WRAPPER_WEB_PATH = "multi"
.\run.ps1
```

Linux example:

```bash
WRAPPER_PORT=8090 WRAPPER_WEB_PATH=multi ./run.sh
```

## How Add/Delete Works

### Add application

1. Validate input and port conflicts.
2. If `github_location` is provided, clone into `installed_apps`.
3. Run setup script (`setup_executable` or default).
4. Launch app script (`executable` or default) in the background.
5. Save PID and app metadata to `apps_config.yaml`.
6. Run:

```text
tailscale serve --bg --set-path /<web_path> http://127.0.0.1:<application_port>
```

### Delete application

1. Drain Tailscale Serve.
2. Kill the saved PID (Windows uses process tree termination).
3. Remove the app entry from `apps_config.yaml`.

## API Endpoints

- `GET /api/apps`: list configured apps
- `POST /api/apps`: add an app
- `DELETE /api/apps/<app_id>`: delete an app

## Troubleshooting

### `run.ps1` exits with code 1

Common causes:

- `.venv` not created yet. Run `./setup.ps1` first.
- `tailscale` command unavailable or not authenticated.
- `WRAPPER_PORT` already in use.

Quick checks:

```powershell
Get-Command tailscale
Test-Path .\.venv\Scripts\python.exe
```

### App deletes but process stays alive on Windows

The backend uses `taskkill /T /F` for tree termination. If a child process still remains, verify the stored PID in `apps_config.yaml` and check if the target app spawns detached services outside the process tree.

## Development

Install dependencies directly (optional if you already used setup scripts):

```bash
pip install -r requirements.txt
```

List Flask routes:

```bash
python -m flask --app app.py routes
```
