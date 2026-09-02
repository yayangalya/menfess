import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from control_db import (
    init_db, get_wordings, set_wording, get_keywords, replace_keywords,
    get_statuses, get_logs, set_status, add_log
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MENFESS_DATA_DIR", str(ROOT / ".menfess_relay_data")))
CONTROL_DB = os.getenv("MENFESS_CONTROL_DB", str(ROOT / "control.sqlite3"))
WORKER = ROOT / "worker.py"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
AUTO_START = os.getenv("MENFESS_AUTO_START", "0") == "1"
COOKIE_NAME = "menfess_dashboard_auth"
COOKIE_MAX_AGE = 60 * 60 * 12  # 12 jam

app = FastAPI(title="Berline Menfess Control")
worker_process = None
worker_log_task = None


class WordingPayload(BaseModel):
    text: str


class KeywordPayload(BaseModel):
    keywords: list[str]


class LoginPayload(BaseModel):
    password: str


def _expected_cookie() -> str:
    """Token cookie diturunkan dari password; password tidak pernah dikirim ke browser lagi."""
    return hmac.new(
        DASHBOARD_PASSWORD.encode("utf-8"),
        b"berline-menfess-dashboard-v1",
        hashlib.sha256,
    ).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not DASHBOARD_PASSWORD:
        return False
    supplied = request.cookies.get(COOKIE_NAME, "")
    return bool(supplied) and hmac.compare_digest(supplied, _expected_cookie())


@app.middleware("http")
async def protect_dashboard(request: Request, call_next):
    path = request.url.path
    public_paths = {"/login", "/api/login", "/health"}

    if path in public_paths:
        return await call_next(request)

    if not DASHBOARD_PASSWORD:
        return HTMLResponse(
            "<h2>Dashboard belum dikunci</h2>"
            "<p>Tambahkan variable <b>DASHBOARD_PASSWORD</b> di Railway lalu deploy ulang.</p>",
            status_code=503,
        )

    if not _is_authenticated(request):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    return await call_next(request)


def worker_alive():
    global worker_process
    return worker_process is not None and worker_process.poll() is None


async def capture_stdout(proc):
    while proc and proc.stdout:
        line = await asyncio.to_thread(proc.stdout.readline)
        if not line:
            break
        line = line.rstrip()
        if line:
            add_log(line, "INFO", "process")


async def start_worker():
    global worker_process, worker_log_task
    if worker_alive():
        return False

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MENFESS_DATA_DIR"] = str(DATA_DIR)
    env["MENFESS_CONTROL_DB"] = CONTROL_DB

    worker_process = subprocess.Popen(
        [sys.executable, str(WORKER)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    set_status("WORKER", "STARTING", f"PID {worker_process.pid}")
    add_log(f"Worker dijalankan. PID {worker_process.pid}", "INFO", "dashboard")
    worker_log_task = asyncio.create_task(capture_stdout(worker_process))
    return True


async def stop_worker():
    global worker_process
    if not worker_alive():
        set_status("WORKER", "OFFLINE", "Worker tidak sedang berjalan")
        return False

    pid = worker_process.pid
    add_log(f"Meminta worker PID {pid} berhenti.", "INFO", "dashboard")
    worker_process.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(worker_process.wait), timeout=12)
    except asyncio.TimeoutError:
        worker_process.kill()
        await asyncio.to_thread(worker_process.wait)

    set_status("WORKER", "OFFLINE", "Dihentikan dari dashboard")
    return True


async def restart_worker():
    await stop_worker()
    await asyncio.sleep(1)
    return await start_worker()


@app.on_event("startup")
async def startup():
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Aman secara default: deploy/restart Railway TIDAK otomatis menyalakan Telegram.
    # Worker hanya auto-start kalau MENFESS_AUTO_START=1 sengaja ditambahkan.
    if AUTO_START:
        await start_worker()
    else:
        set_status("WORKER", "OFFLINE", "Menunggu tombol RUN dari dashboard")


@app.on_event("shutdown")
async def shutdown():
    await stop_worker()


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if DASHBOARD_PASSWORD and _is_authenticated(request):
        return RedirectResponse("/", status_code=303)

    return HTMLResponse("""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login • Menfess Control</title>
<style>
:root{--navy:#11233f;--orange:#ff8a24;--bg:#f6f7fb;--line:#e6e8ef;--red:#d83b49}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);font-family:Inter,Arial,sans-serif;color:#1f2937;padding:20px}
.card{width:min(420px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px;box-shadow:0 16px 40px rgba(17,35,63,.10)}
h1{margin:0 0 6px;color:var(--navy);font-size:24px}.sub{margin:0 0 22px;color:#6b7280;font-size:13px}
label{display:block;font-size:13px;font-weight:700;margin-bottom:7px}input{width:100%;border:1px solid #d9dde7;border-radius:11px;padding:12px 13px;font:inherit;outline:none}input:focus{border-color:var(--orange);box-shadow:0 0 0 3px rgba(255,138,36,.12)}
button{width:100%;margin-top:13px;border:0;border-radius:11px;padding:12px 14px;background:var(--navy);color:#fff;font-weight:800;cursor:pointer}.error{min-height:20px;margin-top:10px;color:var(--red);font-size:12px}
</style>
</head>
<body>
<div class="card">
  <h1>Berline's Menfess Control</h1>
  <p class="sub">Masukkan password dashboard untuk lanjut.</p>
  <form id="loginForm">
    <label for="password">Password</label>
    <input id="password" type="password" autocomplete="current-password" autofocus required>
    <button type="submit">LOGIN</button>
    <div id="error" class="error"></div>
  </form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('error');
  err.textContent = '';
  const r = await fetch('/api/login', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('password').value})
  });
  if (r.ok) location.href = '/';
  else err.textContent = 'Password salah.';
});
</script>
</body>
</html>
""")


@app.post("/api/login")
async def api_login(payload: LoginPayload):
    if not DASHBOARD_PASSWORD:
        raise HTTPException(503, "DASHBOARD_PASSWORD belum diatur")

    if not hmac.compare_digest(payload.password, DASHBOARD_PASSWORD):
        raise HTTPException(401, "Password salah")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        _expected_cookie(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/logout")
async def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
async def home():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def api_status():
    statuses = get_statuses()
    now = time.time()
    for item in statuses:
        until = item.get("flood_until")
        item["remaining"] = max(0, int(until - now)) if until else 0
    return {
        "worker_alive": worker_alive(),
        "pid": worker_process.pid if worker_alive() else None,
        "statuses": statuses,
    }


@app.post("/api/worker/run")
async def api_run():
    changed = await start_worker()
    return {"ok": True, "started": changed}


@app.post("/api/worker/stop")
async def api_stop():
    changed = await stop_worker()
    return {"ok": True, "stopped": changed}


@app.post("/api/worker/restart")
async def api_restart():
    await restart_worker()
    return {"ok": True}


@app.get("/api/wordings")
async def api_wordings():
    return get_wordings()


@app.put("/api/wordings/{trigger}")
async def api_wording_update(trigger: str, payload: WordingPayload):
    if trigger not in {"1", "2", "3", "4", "5"}:
        raise HTTPException(400, "Trigger harus 1-5")
    set_wording(trigger, payload.text)
    add_log(f"Wording {trigger} diperbarui dari web.", "INFO", "dashboard")
    return {"ok": True}


@app.get("/api/keywords")
async def api_keywords():
    return {"keywords": get_keywords()}


@app.put("/api/keywords")
async def api_keywords_update(payload: KeywordPayload):
    items = replace_keywords(payload.keywords)
    add_log(f"Keywords diperbarui dari web: {len(items)} aktif.", "INFO", "dashboard")
    return {"ok": True, "count": len(items)}


@app.get("/api/logs")
async def api_logs(limit: int = 120):
    return {"logs": get_logs(min(max(limit, 10), 300))}
import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from control_db import (
    init_db, get_wordings, set_wording, get_keywords, replace_keywords,
    get_statuses, get_logs, set_status, add_log
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MENFESS_DATA_DIR", str(ROOT / ".menfess_relay_data")))
CONTROL_DB = os.getenv("MENFESS_CONTROL_DB", str(ROOT / "control.sqlite3"))
WORKER = ROOT / "worker.py"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
AUTO_START = os.getenv("MENFESS_AUTO_START", "0") == "1"
COOKIE_NAME = "menfess_dashboard_auth"
COOKIE_MAX_AGE = 60 * 60 * 12  # 12 jam

app = FastAPI(title="Berline Menfess Control")
worker_process = None
worker_log_task = None


class WordingPayload(BaseModel):
    text: str


class KeywordPayload(BaseModel):
    keywords: list[str]


class LoginPayload(BaseModel):
    password: str


def _expected_cookie() -> str:
    """Token cookie diturunkan dari password; password tidak pernah dikirim ke browser lagi."""
    return hmac.new(
        DASHBOARD_PASSWORD.encode("utf-8"),
        b"berline-menfess-dashboard-v1",
        hashlib.sha256,
    ).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not DASHBOARD_PASSWORD:
        return False
    supplied = request.cookies.get(COOKIE_NAME, "")
    return bool(supplied) and hmac.compare_digest(supplied, _expected_cookie())


@app.middleware("http")
async def protect_dashboard(request: Request, call_next):
    path = request.url.path
    public_paths = {"/login", "/api/login", "/health"}

    if path in public_paths:
        return await call_next(request)

    if not DASHBOARD_PASSWORD:
        return HTMLResponse(
            "<h2>Dashboard belum dikunci</h2>"
            "<p>Tambahkan variable <b>DASHBOARD_PASSWORD</b> di Railway lalu deploy ulang.</p>",
            status_code=503,
        )

    if not _is_authenticated(request):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    return await call_next(request)


def worker_alive():
    global worker_process
    return worker_process is not None and worker_process.poll() is None


async def capture_stdout(proc):
    while proc and proc.stdout:
        line = await asyncio.to_thread(proc.stdout.readline)
        if not line:
            break
        line = line.rstrip()
        if line:
            add_log(line, "INFO", "process")


async def start_worker():
    global worker_process, worker_log_task
    if worker_alive():
        return False

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MENFESS_DATA_DIR"] = str(DATA_DIR)
    env["MENFESS_CONTROL_DB"] = CONTROL_DB

    worker_process = subprocess.Popen(
        [sys.executable, str(WORKER)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    set_status("WORKER", "STARTING", f"PID {worker_process.pid}")
    add_log(f"Worker dijalankan. PID {worker_process.pid}", "INFO", "dashboard")
    worker_log_task = asyncio.create_task(capture_stdout(worker_process))
    return True


async def stop_worker():
    global worker_process
    if not worker_alive():
        set_status("WORKER", "OFFLINE", "Worker tidak sedang berjalan")
        return False

    pid = worker_process.pid
    add_log(f"Meminta worker PID {pid} berhenti.", "INFO", "dashboard")
    worker_process.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(worker_process.wait), timeout=12)
    except asyncio.TimeoutError:
        worker_process.kill()
        await asyncio.to_thread(worker_process.wait)

    set_status("WORKER", "OFFLINE", "Dihentikan dari dashboard")
    return True


async def restart_worker():
    await stop_worker()
    await asyncio.sleep(1)
    return await start_worker()


@app.on_event("startup")
async def startup():
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Aman secara default: deploy/restart Railway TIDAK otomatis menyalakan Telegram.
    # Worker hanya auto-start kalau MENFESS_AUTO_START=1 sengaja ditambahkan.
    if AUTO_START:
        await start_worker()
    else:
        set_status("WORKER", "OFFLINE", "Menunggu tombol RUN dari dashboard")


@app.on_event("shutdown")
async def shutdown():
    await stop_worker()


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if DASHBOARD_PASSWORD and _is_authenticated(request):
        return RedirectResponse("/", status_code=303)

    return HTMLResponse("""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login • Menfess Control</title>
<style>
:root{--navy:#11233f;--orange:#ff8a24;--bg:#f6f7fb;--line:#e6e8ef;--red:#d83b49}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);font-family:Inter,Arial,sans-serif;color:#1f2937;padding:20px}
.card{width:min(420px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px;box-shadow:0 16px 40px rgba(17,35,63,.10)}
h1{margin:0 0 6px;color:var(--navy);font-size:24px}.sub{margin:0 0 22px;color:#6b7280;font-size:13px}
label{display:block;font-size:13px;font-weight:700;margin-bottom:7px}input{width:100%;border:1px solid #d9dde7;border-radius:11px;padding:12px 13px;font:inherit;outline:none}input:focus{border-color:var(--orange);box-shadow:0 0 0 3px rgba(255,138,36,.12)}
button{width:100%;margin-top:13px;border:0;border-radius:11px;padding:12px 14px;background:var(--navy);color:#fff;font-weight:800;cursor:pointer}.error{min-height:20px;margin-top:10px;color:var(--red);font-size:12px}
</style>
</head>
<body>
<div class="card">
  <h1>Berline's Menfess Control</h1>
  <p class="sub">Masukkan password dashboard untuk lanjut.</p>
  <form id="loginForm">
    <label for="password">Password</label>
    <input id="password" type="password" autocomplete="current-password" autofocus required>
    <button type="submit">LOGIN</button>
    <div id="error" class="error"></div>
  </form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('error');
  err.textContent = '';
  const r = await fetch('/api/login', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('password').value})
  });
  if (r.ok) location.href = '/';
  else err.textContent = 'Password salah.';
});
</script>
</body>
</html>
""")


@app.post("/api/login")
async def api_login(payload: LoginPayload):
    if not DASHBOARD_PASSWORD:
        raise HTTPException(503, "DASHBOARD_PASSWORD belum diatur")

    if not hmac.compare_digest(payload.password, DASHBOARD_PASSWORD):
        raise HTTPException(401, "Password salah")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        _expected_cookie(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/logout")
async def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
async def home():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def api_status():
    statuses = get_statuses()
    now = time.time()
    for item in statuses:
        until = item.get("flood_until")
        item["remaining"] = max(0, int(until - now)) if until else 0
    return {
        "worker_alive": worker_alive(),
        "pid": worker_process.pid if worker_alive() else None,
        "statuses": statuses,
    }


@app.post("/api/worker/run")
async def api_run():
    changed = await start_worker()
    return {"ok": True, "started": changed}


@app.post("/api/worker/stop")
async def api_stop():
    changed = await stop_worker()
    return {"ok": True, "stopped": changed}


@app.post("/api/worker/restart")
async def api_restart():
    await restart_worker()
    return {"ok": True}


@app.get("/api/wordings")
async def api_wordings():
    return get_wordings()


@app.put("/api/wordings/{trigger}")
async def api_wording_update(trigger: str, payload: WordingPayload):
    if trigger not in {"1", "2", "3", "4", "5"}:
        raise HTTPException(400, "Trigger harus 1-5")
    set_wording(trigger, payload.text)
    add_log(f"Wording {trigger} diperbarui dari web.", "INFO", "dashboard")
    return {"ok": True}


@app.get("/api/keywords")
async def api_keywords():
    return {"keywords": get_keywords()}


@app.put("/api/keywords")
async def api_keywords_update(payload: KeywordPayload):
    items = replace_keywords(payload.keywords)
    add_log(f"Keywords diperbarui dari web: {len(items)} aktif.", "INFO", "dashboard")
    return {"ok": True, "count": len(items)}


@app.get("/api/logs")
async def api_logs(limit: int = 120):
    return {"logs": get_logs(min(max(limit, 10), 300))}
import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from control_db import (
    init_db, get_wordings, set_wording, get_keywords, replace_keywords,
    get_statuses, get_logs, set_status, add_log
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MENFESS_DATA_DIR", str(ROOT / ".menfess_relay_data")))
CONTROL_DB = os.getenv("MENFESS_CONTROL_DB", str(ROOT / "control.sqlite3"))
WORKER = ROOT / "worker.py"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
AUTO_START = os.getenv("MENFESS_AUTO_START", "0") == "1"
COOKIE_NAME = "menfess_dashboard_auth"
COOKIE_MAX_AGE = 60 * 60 * 12  # 12 jam

app = FastAPI(title="Berline Menfess Control")
worker_process = None
worker_log_task = None


class WordingPayload(BaseModel):
    text: str


class KeywordPayload(BaseModel):
    keywords: list[str]


class LoginPayload(BaseModel):
    password: str


def _expected_cookie() -> str:
    """Token cookie diturunkan dari password; password tidak pernah dikirim ke browser lagi."""
    return hmac.new(
        DASHBOARD_PASSWORD.encode("utf-8"),
        b"berline-menfess-dashboard-v1",
        hashlib.sha256,
    ).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not DASHBOARD_PASSWORD:
        return False
    supplied = request.cookies.get(COOKIE_NAME, "")
    return bool(supplied) and hmac.compare_digest(supplied, _expected_cookie())


@app.middleware("http")
async def protect_dashboard(request: Request, call_next):
    path = request.url.path
    public_paths = {"/login", "/api/login", "/health"}

    if path in public_paths:
        return await call_next(request)

    if not DASHBOARD_PASSWORD:
        return HTMLResponse(
            "<h2>Dashboard belum dikunci</h2>"
            "<p>Tambahkan variable <b>DASHBOARD_PASSWORD</b> di Railway lalu deploy ulang.</p>",
            status_code=503,
        )

    if not _is_authenticated(request):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    return await call_next(request)


def worker_alive():
    global worker_process
    return worker_process is not None and worker_process.poll() is None


async def capture_stdout(proc):
    while proc and proc.stdout:
        line = await asyncio.to_thread(proc.stdout.readline)
        if not line:
            break
        line = line.rstrip()
        if line:
            add_log(line, "INFO", "process")


async def start_worker():
    global worker_process, worker_log_task
    if worker_alive():
        return False

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MENFESS_DATA_DIR"] = str(DATA_DIR)
    env["MENFESS_CONTROL_DB"] = CONTROL_DB

    worker_process = subprocess.Popen(
        [sys.executable, str(WORKER)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    set_status("WORKER", "STARTING", f"PID {worker_process.pid}")
    add_log(f"Worker dijalankan. PID {worker_process.pid}", "INFO", "dashboard")
    worker_log_task = asyncio.create_task(capture_stdout(worker_process))
    return True


async def stop_worker():
    global worker_process
    if not worker_alive():
        set_status("WORKER", "OFFLINE", "Worker tidak sedang berjalan")
        return False

    pid = worker_process.pid
    add_log(f"Meminta worker PID {pid} berhenti.", "INFO", "dashboard")
    worker_process.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(worker_process.wait), timeout=12)
    except asyncio.TimeoutError:
        worker_process.kill()
        await asyncio.to_thread(worker_process.wait)

    set_status("WORKER", "OFFLINE", "Dihentikan dari dashboard")
    return True


async def restart_worker():
    await stop_worker()
    await asyncio.sleep(1)
    return await start_worker()


@app.on_event("startup")
async def startup():
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Aman secara default: deploy/restart Railway TIDAK otomatis menyalakan Telegram.
    # Worker hanya auto-start kalau MENFESS_AUTO_START=1 sengaja ditambahkan.
    if AUTO_START:
        await start_worker()
    else:
        set_status("WORKER", "OFFLINE", "Menunggu tombol RUN dari dashboard")


@app.on_event("shutdown")
async def shutdown():
    await stop_worker()


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if DASHBOARD_PASSWORD and _is_authenticated(request):
        return RedirectResponse("/", status_code=303)

    return HTMLResponse("""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login • Menfess Control</title>
<style>
:root{--navy:#11233f;--orange:#ff8a24;--bg:#f6f7fb;--line:#e6e8ef;--red:#d83b49}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);font-family:Inter,Arial,sans-serif;color:#1f2937;padding:20px}
.card{width:min(420px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px;box-shadow:0 16px 40px rgba(17,35,63,.10)}
h1{margin:0 0 6px;color:var(--navy);font-size:24px}.sub{margin:0 0 22px;color:#6b7280;font-size:13px}
label{display:block;font-size:13px;font-weight:700;margin-bottom:7px}input{width:100%;border:1px solid #d9dde7;border-radius:11px;padding:12px 13px;font:inherit;outline:none}input:focus{border-color:var(--orange);box-shadow:0 0 0 3px rgba(255,138,36,.12)}
button{width:100%;margin-top:13px;border:0;border-radius:11px;padding:12px 14px;background:var(--navy);color:#fff;font-weight:800;cursor:pointer}.error{min-height:20px;margin-top:10px;color:var(--red);font-size:12px}
</style>
</head>
<body>
<div class="card">
  <h1>Berline's Menfess Control</h1>
  <p class="sub">Masukkan password dashboard untuk lanjut.</p>
  <form id="loginForm">
    <label for="password">Password</label>
    <input id="password" type="password" autocomplete="current-password" autofocus required>
    <button type="submit">LOGIN</button>
    <div id="error" class="error"></div>
  </form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('error');
  err.textContent = '';
  const r = await fetch('/api/login', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('password').value})
  });
  if (r.ok) location.href = '/';
  else err.textContent = 'Password salah.';
});
</script>
</body>
</html>
""")


@app.post("/api/login")
async def api_login(payload: LoginPayload):
    if not DASHBOARD_PASSWORD:
        raise HTTPException(503, "DASHBOARD_PASSWORD belum diatur")

    if not hmac.compare_digest(payload.password, DASHBOARD_PASSWORD):
        raise HTTPException(401, "Password salah")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        _expected_cookie(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/logout")
async def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
async def home():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def api_status():
    statuses = get_statuses()
    now = time.time()
    for item in statuses:
        until = item.get("flood_until")
        item["remaining"] = max(0, int(until - now)) if until else 0
    return {
        "worker_alive": worker_alive(),
        "pid": worker_process.pid if worker_alive() else None,
        "statuses": statuses,
    }


@app.post("/api/worker/run")
async def api_run():
    changed = await start_worker()
    return {"ok": True, "started": changed}


@app.post("/api/worker/stop")
async def api_stop():
    changed = await stop_worker()
    return {"ok": True, "stopped": changed}


@app.post("/api/worker/restart")
async def api_restart():
    await restart_worker()
    return {"ok": True}


@app.get("/api/wordings")
async def api_wordings():
    return get_wordings()


@app.put("/api/wordings/{trigger}")
async def api_wording_update(trigger: str, payload: WordingPayload):
    if trigger not in {"1", "2", "3", "4", "5"}:
        raise HTTPException(400, "Trigger harus 1-5")
    set_wording(trigger, payload.text)
    add_log(f"Wording {trigger} diperbarui dari web.", "INFO", "dashboard")
    return {"ok": True}


@app.get("/api/keywords")
async def api_keywords():
    return {"keywords": get_keywords()}


@app.put("/api/keywords")
async def api_keywords_update(payload: KeywordPayload):
    items = replace_keywords(payload.keywords)
    add_log(f"Keywords diperbarui dari web: {len(items)} aktif.", "INFO", "dashboard")
    return {"ok": True, "count": len(items)}


@app.get("/api/logs")
async def api_logs(limit: int = 120):
    return {"logs": get_logs(min(max(limit, 10), 300))}
