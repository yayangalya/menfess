
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from control_db import (
    init_db, get_wordings, set_wording, get_keywords, replace_keywords,
    get_statuses, get_logs, set_status, add_log, get_setting
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MENFESS_DATA_DIR", str(ROOT / ".menfess_relay_data")))
CONTROL_DB = os.getenv("MENFESS_CONTROL_DB", str(ROOT / "control.sqlite3"))
WORKER = ROOT / "worker.py"

app = FastAPI(title="Berline Menfess Control")
worker_process = None
worker_log_task = None

class WordingPayload(BaseModel):
    text: str

class KeywordPayload(BaseModel):
    keywords: list[str]

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
    if get_setting("auto_start", "1") == "1":
        await start_worker()

@app.on_event("shutdown")
async def shutdown():
    await stop_worker()

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
    if trigger not in {"1","2","3","4","5"}:
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
