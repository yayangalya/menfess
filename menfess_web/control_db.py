
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.getenv(
    "MENFESS_CONTROL_DB",
    str(Path(__file__).resolve().parent / "control.sqlite3")
))

DEFAULT_WORDINGS = {
    "1": "HIT @SOTUDY AS SELLER ★ start from 3-25k! Do check @elgaleries for more, avail rush and revisi ⓘ Check @elgatesult for testi & result. 🫀⌨️",
    "2": "DO CHECK @Elgaleries start 3k-20k 📚 Di handle admin smt 6 ke atas dan berpengalaman! avail inrush NO AI. katalog & testi @elgatesult.",
    "3": "HIT @ SOTUDY AS SELLER ★ start from 3-25k! Do check @elgaleries for more, avail rush and revisi ⓘ Check @elgatesult for testi & result. 🫀⌨️",
    "4": "HMU @BERRLINE AS SELLER! Start from 2-25k check @COLLEGLE for testi. Di handle mahasiswi teknik, for result check [berlineporto.vercel.app].",
    "5": "Kindly check @Collegle or hit @.Berrline as seller! 📂♥️ Start from 3-25k, avail inrush and revisi. For result check [berlineporto.vercel.app]",
}

DEFAULT_KEYWORDS = [
    "joktug", "joki tugas", "makalah", "infografis", "poster",
    "edit video", "edit vid", "spss", "kimia", "biologi", "fisika",
    "banner", "jasa ketik", "jastik", "jasa tulis", "jastul",
    "joki coding", "bimbel", "akuntansi", "olah data", "parafrase",
    "turnitin", "ppt", "mindmap", "mind mapping", "edit feeds ig",
    "video animasi", "animasi ai", "cari jurnal", "essai", "essay",
    "artikel", "laporan", "joki artikel", "joki laporan", "proposal",
    "joki proposal", "ebook", "cerpen", "puisi", "naskah drama",
    "resume", "resume materi", "formatting", "revisi makalah",
    "revisi proposal", "review jurnal", "daftar isi", "daftar pustaka",
    "nomor halaman", "no halaman", "cv ats", "cv kreatif", "visi misi",
    "organisasi", "famplet", "skripsi", "joki skripsi", "laprak",
    "laporan praktikum", "studi kasus", "literature review", "ui/ux",
    "mendeley", "ai detector", "logo kelas", "logo 2d", "logo 3d",
    "jasa edit", "edit logo", "logo",
]

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS wordings (
            trigger TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS keywords (
            keyword TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS runtime_status (
            name TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            detail TEXT,
            flood_until REAL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            level TEXT NOT NULL,
            source TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        now = time.time()
        for trigger, text in DEFAULT_WORDINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO wordings(trigger,text,updated_at) VALUES(?,?,?)",
                (trigger, text, now)
            )
        for kw in DEFAULT_KEYWORDS:
            db.execute(
                "INSERT OR IGNORE INTO keywords(keyword,enabled) VALUES(?,1)",
                (kw,)
            )
        db.execute(
            "INSERT OR IGNORE INTO app_settings(key,value) VALUES('auto_start','1')"
        )

def get_wording(trigger, fallback=""):
    init_db()
    with _connect() as db:
        row = db.execute(
            "SELECT text FROM wordings WHERE trigger=?", (str(trigger),)
        ).fetchone()
        return row["text"] if row else fallback

def get_wordings():
    init_db()
    with _connect() as db:
        return {
            row["trigger"]: row["text"]
            for row in db.execute(
                "SELECT trigger,text FROM wordings ORDER BY CAST(trigger AS INTEGER)"
            )
        }

def set_wording(trigger, text):
    if str(trigger) not in {"1","2","3","4","5"}:
        raise ValueError("Trigger wording harus 1-5.")
    with _connect() as db:
        db.execute(
            """INSERT INTO wordings(trigger,text,updated_at) VALUES(?,?,?)
               ON CONFLICT(trigger) DO UPDATE SET text=excluded.text,
               updated_at=excluded.updated_at""",
            (str(trigger), text, time.time())
        )

def get_keywords():
    init_db()
    with _connect() as db:
        return [
            row["keyword"] for row in db.execute(
                "SELECT keyword FROM keywords WHERE enabled=1 ORDER BY rowid"
            )
        ]

def replace_keywords(items):
    clean = []
    seen = set()
    for item in items:
        kw = " ".join(str(item).strip().split())
        key = kw.casefold()
        if kw and key not in seen:
            clean.append(kw)
            seen.add(key)
    with _connect() as db:
        db.execute("DELETE FROM keywords")
        db.executemany(
            "INSERT INTO keywords(keyword,enabled) VALUES(?,1)",
            [(kw,) for kw in clean]
        )
    return clean

def set_status(name, state, detail="", flood_until=None):
    init_db()
    now = time.time()
    with _connect() as db:
        db.execute(
            """INSERT INTO runtime_status(name,state,detail,flood_until,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 state=excluded.state,
                 detail=excluded.detail,
                 flood_until=excluded.flood_until,
                 updated_at=excluded.updated_at""",
            (name, state, detail, flood_until, now)
        )

def get_statuses():
    init_db()
    with _connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT name,state,detail,flood_until,updated_at FROM runtime_status ORDER BY name"
        )]

def add_log(message, level="INFO", source="worker"):
    init_db()
    with _connect() as db:
        db.execute(
            "INSERT INTO logs(created_at,level,source,message) VALUES(?,?,?,?)",
            (time.time(), level, source, str(message)[:3000])
        )

def get_logs(limit=150):
    init_db()
    with _connect() as db:
        rows = db.execute(
            "SELECT id,created_at,level,source,message FROM logs ORDER BY id DESC LIMIT ?",
            (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]

def get_setting(key, default=None):
    init_db()
    with _connect() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key, value):
    with _connect() as db:
        db.execute(
            """INSERT INTO app_settings(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, str(value))
        )
