#!/usr/bin/env python3
"""Userbot menfess: 1 relay, 5 admin, 9 base, 3 topic, 5 wording.

Tidak memakai bot Telegram. Akun Amela menjadi relay yang hanya memantau base
dan meneruskan posting. Empat akun admin login dengan sesi terpisah. Abillo + Sail menangani Topic 1
(base general), sedangkan Bear + Geya menangani Topic 2 (base special). Pilihan wording tidak dibatasi per akun;
setiap akun dapat memilih Wording 1 atau Wording 2 pada topic-nya. Manusia kemudian:
  - reply `1` untuk mengirim Wording 1;
  - reply `2` untuk mengirim Wording 2; atau
  - menulis reply lain untuk mengirim teks manual itu sendiri.

Komentar hanya dikirim oleh akun yang dipasangkan ke kelompok base/topic tersebut. Menemukan
keyword tidak pernah langsung membuat komentar.

Perintah:
  python worker.py --setup
  python worker.py             # mode uji; belum komentar ke base
  python worker.py --live      # komentar sungguhan
  python worker.py --self-test

Persiapan:
  - Python 3.10+ dan `python -m pip install Telethon==1.44.0`.
  - Amela dan keempat akun admin menjadi anggota grup private yang memakai
    Topics.
  - Amela mengikuti semua sembilan base; tidak perlu masuk grup komentarnya.
  - Setiap admin mengikuti base yang dipasangkan dengan topic-nya, masuk grup
    komentar base, dan sudah berhasil mencoba komentar manual.
  - Satu api_id/api_hash aplikasi milik sendiri cukup untuk lima sesi pengguna.

Keamanan dan batas:
  - Masukkan API hash, nomor, OTP, dan 2FA hanya di terminal lokal.
  - Jangan bagikan folder .menfess_multi_data atau file .session. Sesi dapat
    dicabut melalui Telegram Settings > Devices.
  - Program hanya memantau posting baru saat aktif. Riwayat/offline/edit tidak
    diproses. Caption teks dapat dicocokkan; teks dalam gambar tidak dibaca.
  - Hanya reply teks. Foto, stiker, voice, dan forward sebagai perintah ditolak.
  - Satu akun hanya melakukan satu percobaan komentar per posting. Kegagalan
    atau status tidak pasti tidak dicoba ulang otomatis agar tidak ganda.
  - Konten terlindungi tidak dipaksa forward. FloodWait pada akun admin hanya mem-pause akun tersebut; akun lain tetap berjalan.
  - Forward relay dikirim tidak silent, tetapi bunyi/badge tetap mengikuti
    pengaturan notifikasi Telegram setiap akun dan topic.
  - Patuhi aturan setiap base. Empat akun dapat mengomentari posting yang sama
    hanya jika manusianya sengaja memilih reply di beberapa topic.
"""

import argparse
import asyncio
import time
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata

from control_db import get_wording as db_get_wording, get_keywords as db_get_keywords, set_status as db_set_status, add_log as db_add_log, init_db as db_init


PROFILE_COUNT = 5
DATA = Path(os.getenv("MENFESS_DATA_DIR", str(Path(__file__).resolve().parent / ".menfess_relay_data")))

KEYWORDS = (
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
    "jasa edit",
    "edit logo",
    "logo",
)

WIB_WTB_BASES = ("basewtb", "basewib")
JOCKEY_MONEY_BASES = ("moneyfess", "jockeyfess")
OTHER_BASES = (
    "berdagangonline", "dagangfess", "swalayan",
    "baselelang", "BukaLapakBA",
)
ALL_BASES = WIB_WTB_BASES + JOCKEY_MONEY_BASES + OTHER_BASES

RESPONDER_PLAN = (
    {"topic_nos": (1, 2, 3), "name": "Abillo", "username": "jencutiey", "session": "admin_abillo"},
    {"topic_nos": (1, 2, 3), "name": "Sail", "username": "paramole", "session": "admin_sail"},
    {"topic_nos": (1, 2, 3), "name": "Bear", "username": "bearlism", "session": "admin_bear"},
    {"topic_nos": (1, 2, 3), "name": "Geya", "username": "geyashy", "session": "admin_geya"},
    {"topic_nos": (1, 2, 3), "name": "Berline", "username": None, "session": "admin_berline"},
)


WORDING_1 = 'HIT @SOTUDY AS SELLER ★ start from 3-25k! Do check @elgaleries for more, avail rush and revisi ⓘ Check @elgatesult for testi & result. 🫀⌨️'
WORDING_2 = 'DO CHECK @Elgaleries start 3k-20k 📚 Di handle admin smt 6 ke atas dan berpengalaman! avail inrush NO AI. katalog & testi @elgatesult.'
WORDING_3 = 'HIT @ SOTUDY AS SELLER ★ start from 3-25k! Do check @elgaleries for more, avail rush and revisi ⓘ Check @elgatesult for testi & result. 🫀⌨️'
WORDING_4 = 'HMU @BERRLINE AS SELLER! Start from 2-25k check @COLLEGLE for testi. Di handle mahasiswi teknik, for result check [berlineporto.vercel.app].'
WORDING_5 = 'Kindly check @Collegle or hit @.Berrline as seller! 📂♥️ Start from 3-25k, avail inrush and revisi. For result check [berlineporto.vercel.app]'

UNIVERSAL_WORDING = {
    "1": WORDING_1,
    "2": WORDING_2,
    "3": WORDING_3,
    "4": WORDING_4,
    "5": WORDING_5,
}

TOPIC_CONFIG = {
    1: {
        "expected": "WIB WTB ONLY",
        "bases": WIB_WTB_BASES,
        "wording": UNIVERSAL_WORDING,
    },
    2: {
        "expected": "JOCKEY MONEY",
        "bases": JOCKEY_MONEY_BASES,
        "wording": UNIVERSAL_WORDING,
    },
    3: {
        "expected": "OTHER BASE",
        "bases": OTHER_BASES,
        "wording": UNIVERSAL_WORDING,
    },
}

def normalized(text):
    return unicodedata.normalize("NFKC", text or "").casefold()


def topic_name_key(text):
    return re.sub(r"[^a-z0-9]", "", normalized(text))


def matching_keywords(text):
    value = normalized(text)
    keywords = tuple(db_get_keywords() or KEYWORDS)
    found = []
    for keyword in keywords:
        pattern = re.compile(r"(?<!\w)" + re.escape(normalized(keyword)) + r"(?!\w)")
        if pattern.search(value):
            found.append(keyword)
    return tuple(found)


def matches(text):
    return bool(matching_keywords(text))


def targets_for_base(username):
    key = normalized(username).lstrip("@")
    targets = []
    for topic_no, config in TOPIC_CONFIG.items():
        keys = {normalized(base).lstrip("@") for base in config["bases"]}
        if key in keys:
            targets.append(topic_no)
    return tuple(targets)



def selected_text(reply_text):
    """Reply angka 1-5 mengambil wording terbaru dari database web."""
    stripped = (reply_text or "").strip()
    if stripped in UNIVERSAL_WORDING:
        fallback = UNIVERSAL_WORDING[stripped]
        return db_get_wording(stripped, fallback), stripped
    return reply_text or "", "manual"


def event_topic_id(message):
    header = getattr(message, "reply_to", None)
    if not header:
        return None
    return getattr(header, "reply_to_top_id", None) or (
        getattr(header, "reply_to_msg_id", None)
        if getattr(header, "forum_topic", False) else None)


def eligible_reply(event, account_id, group_id, topic_id):
    message = event.message
    return (
        event.chat_id == group_id
        and event.sender_id == account_id
        and bool(event.reply_to_msg_id)
        and event_topic_id(message) == topic_id
        and not getattr(message, "fwd_from", None)
        and not getattr(message, "via_bot_id", None)
        and not getattr(message, "action", None)
    )


class Store:
    """Menyimpan ID dan status; tidak menyimpan isi menfess atau reply."""

    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY(source_chat_id, source_message_id)
            );
            CREATE TABLE IF NOT EXISTS routes (
                topic_no INTEGER NOT NULL,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                inbox_message_id INTEGER,
                state TEXT NOT NULL,
                PRIMARY KEY(topic_no, source_chat_id, source_message_id),
                UNIQUE(topic_no, inbox_message_id)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                account_id INTEGER NOT NULL,
                topic_no INTEGER NOT NULL,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                reply_message_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                remote_message_id INTEGER,
                PRIMARY KEY(account_id, reply_message_id)
            );
        """)

    def reserve_post(self, source_chat_id, source_message_id, target_topics):
        with self.db:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO posts VALUES (?, ?, 'sending')",
                (source_chat_id, source_message_id),
            ).rowcount == 1
            if inserted:
                self.db.executemany(
                    "INSERT INTO routes VALUES (?, ?, ?, NULL, 'pending')",
                    [(topic_no, source_chat_id, source_message_id)
                     for topic_no in target_topics],
                )
            return inserted

    def set_route(self, topic_no, source_chat_id, source_message_id,
                  inbox_message_id, state="ready"):
        with self.db:
            self.db.execute(
                "UPDATE routes SET inbox_message_id=?, state=? WHERE "
                "topic_no=? AND source_chat_id=? AND source_message_id=?",
                (inbox_message_id, state, topic_no,
                 source_chat_id, source_message_id),
            )

    def finish_post(self, source_chat_id, source_message_id):
        with self.db:
            self.db.execute(
                "UPDATE posts SET state='done' WHERE source_chat_id=? "
                "AND source_message_id=?",
                (source_chat_id, source_message_id),
            )

    def source_for_reply(self, topic_no, inbox_message_id):
        row = self.db.execute(
            "SELECT source_chat_id, source_message_id FROM routes WHERE "
            "topic_no=? AND inbox_message_id=? AND state='ready'",
            (topic_no, inbox_message_id),
        ).fetchone()
        return tuple(row) if row else None

    def claim_reply(self, account_id, topic_no, source_chat_id, source_message_id,
                    reply_message_id, live):
        with self.db:
            return self.db.execute(
                "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (account_id, topic_no, source_chat_id, source_message_id,
                 reply_message_id, "sending" if live else "test"),
            ).rowcount == 1

    def finish_job(self, account_id, reply_message_id,
                   status, remote_message_id=None):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status=?, remote_message_id=? WHERE "
                "account_id=? AND reply_message_id=?",
                (status, remote_message_id, account_id, reply_message_id),
            )

    def close(self):
        self.db.close()


@contextmanager
def single_instance(path):
    handle = open(path, "a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Program lain masih berjalan. Tutup dulu agar tidak ganda.")
    try:
        yield
    finally:
        handle.close()


def display_name(utils, user):
    name = utils.get_display_name(user).strip() or f"User {user.id}"
    username = getattr(user, "username", None)
    return f"{name} (@{username})" if username else name


def username_dialog_map(dialogs):
    result = {}
    for dialog in dialogs:
        entity = dialog.entity
        primary = getattr(entity, "username", None)
        if primary:
            result[normalized(primary)] = dialog
        for item in getattr(entity, "usernames", None) or ():
            if getattr(item, "active", True) and getattr(item, "username", None):
                result[normalized(item.username)] = dialog
    return result


async def resolve_sources(client, dialogs, configured_bases, utils):
    """Resolve base dari dialog, alias username, lalu pencarian @username."""
    by_username = username_dialog_map(dialogs)
    sources = {}
    source_id_to_name = {}
    unresolved = []
    for configured in configured_bases:
        key = normalized(configured)
        dialog = by_username.get(key)
        entity = dialog.entity if dialog else None
        peer_id = dialog.id if dialog else None
        if entity is None:
            try:
                entity = await client.get_entity("@" + configured)
                peer_id = utils.get_peer_id(entity)
            except Exception:
                unresolved.append("@" + configured)
                continue
        if not getattr(entity, "title", None):
            unresolved.append("@" + configured)
            continue
        sources[key] = entity
        source_id_to_name[peer_id] = key
    return sources, source_id_to_name, unresolved


async def get_topics(client, functions, types, group):
    result = await client(functions.messages.GetForumTopicsRequest(
        peer=group, offset_date=None, offset_id=0, offset_topic=0,
        limit=100, q=""))
    return [topic for topic in result.topics if isinstance(topic, types.ForumTopic)]


def required_topics(found_topics):
    by_key = {topic_name_key(topic.title): topic for topic in found_topics}
    return {
        topic_no: by_key.get(topic_name_key(config["expected"]))
        for topic_no, config in TOPIC_CONFIG.items()
    }


async def run_setup(TelegramClient, functions, types, utils):
    config_path = DATA / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("version") == 10:
            print("Setup relay + empat admin versi 1-topic sudah ada:")
            relay = config.get("relay", {})
            if relay:
                print(f"- Relay: {relay.get('label', 'Amela')}")
            for profile in config.get("profiles", []):
                topic_names = " + ".join(
                    f"Topic {item['topic_no']} ({item['topic_title']})"
                    for item in profile.get("topics", []))
                print(f"- {profile['label']} → {topic_names}")
            print("Jalankan tanpa --setup untuk langsung mode LIVE.")
            return
        print("Config lama terdeteksi. Setup ulang untuk versi 1-topic akan dimulai.")

    try:
        api_id = int(input(
            "api_id aplikasi milikmu (cukup satu, misalnya milik Amela): "
        ).strip())
    except ValueError:
        raise RuntimeError("api_id harus berupa angka.")
    api_hash = getpass.getpass("api_hash aplikasi (tersembunyi): ").strip()
    if api_id <= 0 or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise RuntimeError("Format api_id/api_hash tidak valid.")

    profiles = []
    used_account_ids = set()
    group_id = None
    group_title = None

    async def login(session, role_label):
        client = TelegramClient(
            str(DATA / session), api_id, api_hash,
            request_retries=0, flood_sleep_threshold=0, catch_up=False)
        try:
            await client.start(
                phone=lambda: input(
                    f"Nomor Telegram {role_label} (contoh +628...): ").strip(),
                code_callback=lambda: getpass.getpass(
                    f"OTP {role_label} (tersembunyi): ").strip(),
                password=lambda: getpass.getpass(
                    f"Password 2FA {role_label} (jika diminta): "),
            )
            me = await client.get_me()
            if me.bot:
                raise RuntimeError("Akun bot tidak boleh digunakan.")
            if me.id in used_account_ids:
                raise RuntimeError("Akun yang sama dipakai dua kali.")
            used_account_ids.add(me.id)
            label = display_name(utils, me)
            print(f"Login berhasil: {label}")
            return client, me, await client.get_dialogs(), label
        except Exception:
            await client.disconnect()

            raise

    print("\n=== LOGIN RELAY: AMELA ===")
    relay_client, relay_me, relay_dialogs, relay_label = await login("relay_amela", "Amela")
    try:
        groups = [dialog for dialog in relay_dialogs
                  if dialog.is_group
                  and getattr(dialog.entity, "forum", False)
                  and not getattr(dialog.entity, "username", None)
                  and not getattr(dialog.entity, "usernames", None)]
        if not groups:
            raise RuntimeError(
                "Amela belum berada di grup private yang memakai Topics.")
        print("\nPilih grup forum PRIVATE tujuan:")
        for index, dialog in enumerate(groups, 1):
            print(f"{index}. {dialog.name} ({dialog.id})")
        try:
            choice = int(input("Nomor grup: ")) - 1
        except ValueError:
            raise RuntimeError("Nomor grup harus berupa angka.")
        if not 0 <= choice < len(groups):
            raise RuntimeError("Pilihan grup tidak valid.")
        group = groups[choice].entity
        group_id = utils.get_peer_id(group)
        group_title = getattr(group, "title", groups[choice].name)

        topic_map = required_topics(await get_topics(
            relay_client, functions, types, group))
        missing_topics = [TOPIC_CONFIG[number]["expected"]
                          for number, topic in topic_map.items() if topic is None]
        if missing_topics:
            raise RuntimeError(
                "Topic berikut tidak ditemukan: " + ", ".join(missing_topics))

        relay_sources, _, missing_bases = await resolve_sources(
            relay_client, relay_dialogs, ALL_BASES, utils)
        if missing_bases:
            raise RuntimeError(
                "Base berikut tidak dapat ditemukan dari akun Amela: "
                + ", ".join(missing_bases))
        relay = {
            "session": "relay_amela",
            "account_id": relay_me.id,
            "label": relay_label,
            "source_ids": {
                key: utils.get_peer_id(entity)
                for key, entity in relay_sources.items()
            },
        }
        print(f"Relay berhasil: {relay_label} → semua 9 base")
    finally:
        await relay_client.disconnect()

    for slot, plan in enumerate(RESPONDER_PLAN, 1):
        topic_nos = tuple(plan["topic_nos"])
        topic_label = " + ".join(f"Topic {number}" for number in topic_nos)
        username_label = f" (@{plan['username']})" if plan.get("username") else ""
        role_label = f"{plan['name']} / {topic_label}{username_label}"
        print(f"\n=== LOGIN ADMIN {slot} DARI {PROFILE_COUNT}: {role_label} ===")
        client, me, dialogs, label = await login(plan["session"], role_label)
        try:
            if plan.get("username"):
                actual_username = normalized(getattr(me, "username", ""))
                if actual_username != normalized(plan["username"]):
                    shown = f"@{getattr(me, 'username', '')}" if actual_username else "tanpa username"
                    raise RuntimeError(
                        f"{plan['name']} harus login @{plan['username']}, tetapi yang "
                        f"terbaca {shown}.")

            group_dialog = next((item for item in dialogs if item.id == group_id), None)
            if group_dialog is None:
                raise RuntimeError(f"{label} belum menjadi anggota grup {group_title}.")
            group = group_dialog.entity
            if not getattr(group, "forum", False):
                raise RuntimeError("Topics pada grup sedang nonaktif.")

            topic_map = required_topics(await get_topics(client, functions, types, group))
            missing = [TOPIC_CONFIG[number]["expected"] for number in topic_nos
                       if topic_map.get(number) is None]
            if missing:
                raise RuntimeError("Topic berikut tidak ditemukan: " + ", ".join(missing))

            assigned_bases = tuple(dict.fromkeys(
                base for number in topic_nos for base in TOPIC_CONFIG[number]["bases"]))
            sources, _, missing_bases = await resolve_sources(
                client, dialogs, assigned_bases, utils)
            if missing_bases:
                raise RuntimeError(
                    f"Base berikut tidak dapat ditemukan untuk {label}: "
                    + ", ".join(missing_bases))

            topics = [{
                "topic_no": number,
                "topic_id": topic_map[number].id,
                "topic_title": topic_map[number].title,
            } for number in topic_nos]

            profiles.append({
                "slot": slot,
                "session": plan["session"],
                "account_id": me.id,
                "label": label,
                "name": plan["name"],
                "topic_nos": list(topic_nos),
                "topics": topics,
                "source_ids": {
                    key: utils.get_peer_id(entity)
                    for key, entity in sources.items()
                },
            })
            print(f"Pasangan berhasil: {label} ↔ {topic_label}")
        finally:
            await client.disconnect()

    print(f"\nGrup: {group_title}")
    print(f"Relay: {relay['label']} → semua 9 base")
    for profile in profiles:
        topic_label = " + ".join(f"Topic {n}" for n in profile["topic_nos"])
        bases = ", ".join("@" + base for base in profile["source_ids"])
        print(f"{profile['label']} → {topic_label} → {bases}")
    if input("\nPastikan semua pasangan benar. Ketik SETUJU: ").strip() != "SETUJU":
        print("Dibatalkan; konfigurasi belum disimpan.")
        return
    config = {
        "version": 10,
        "api_id": api_id,
        "api_hash": api_hash,
        "group_id": group_id,
        "group_title": group_title,
        "relay": relay,
        "profiles": profiles,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.chmod(config_path, 0o600)
    print("Setup 1 relay + 5 admin + 3 topic selesai. Jalankan tanpa --live untuk mode uji.")


async def connect_relay_runtime(config, TelegramClient, utils):
    relay = config["relay"]
    client = TelegramClient(
        str(DATA / relay["session"]), config["api_id"], config["api_hash"],
        request_retries=0, flood_sleep_threshold=0, catch_up=False)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(f"Sesi relay {relay['label']} sudah tidak aktif.")
    me = await client.get_me()
    if me.id != relay["account_id"]:
        await client.disconnect()
        raise RuntimeError(f"Sesi akun berbeda untuk relay {relay['label']}.")

    dialogs = await client.get_dialogs()
    group_dialog = next((dialog for dialog in dialogs
                         if dialog.id == config["group_id"]), None)
    if group_dialog is None or not getattr(group_dialog.entity, "forum", False):
        await client.disconnect()
        raise RuntimeError(f"Relay {relay['label']} tidak dapat membuka grup tujuan.")

    sources, source_id_to_name, unresolved = await resolve_sources(
        client, dialogs, ALL_BASES, utils)
    if unresolved:
        await client.disconnect()
        raise RuntimeError(
            f"Relay {relay['label']} tidak dapat menemukan: " + ", ".join(unresolved))

    group = group_dialog.entity
    return {
        "relay": relay,
        "client": client,
        "me": me,
        "group": group,
        "group_input": await client.get_input_entity(group),
        "sources": sources,
        "source_id_to_name": source_id_to_name,
    }


async def connect_runtime(config, profile, TelegramClient, functions, types, utils):
    client = TelegramClient(
        str(DATA / profile["session"]), config["api_id"], config["api_hash"],
        request_retries=0, flood_sleep_threshold=0, catch_up=False)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(f"Sesi {profile['label']} sudah tidak aktif.")
    me = await client.get_me()
    if me.id != profile["account_id"]:
        await client.disconnect()
        raise RuntimeError(f"Sesi akun berbeda untuk {profile['label']}.")

    dialogs = await client.get_dialogs()
    group_dialog = next((dialog for dialog in dialogs
                         if dialog.id == config["group_id"]), None)
    if group_dialog is None or not getattr(group_dialog.entity, "forum", False):
        await client.disconnect()
        raise RuntimeError(f"{profile['label']} tidak dapat membuka grup forum tujuan.")
    group = group_dialog.entity

    wanted_ids = [item["topic_id"] for item in profile["topics"]]
    topic_result = await client(functions.messages.GetForumTopicsByIDRequest(
        peer=group, topics=wanted_ids))
    active_by_id = {
        topic.id: topic for topic in topic_result.topics
        if isinstance(topic, types.ForumTopic)
    }
    missing_topics = [item["topic_title"] for item in profile["topics"]
                      if item["topic_id"] not in active_by_id]
    if missing_topics:
        await client.disconnect()
        raise RuntimeError(
            f"Topic tidak tersedia untuk {profile['label']}: " + ", ".join(missing_topics))

    assigned_bases = tuple(profile["source_ids"].keys())
    sources, source_id_to_name, unresolved = await resolve_sources(
        client, dialogs, assigned_bases, utils)
    if unresolved:
        await client.disconnect()
        raise RuntimeError(
            f"{profile['label']} tidak dapat menemukan: " + ", ".join(unresolved))

    return {
        "profile": profile,
        "client": client,
        "me": me,
        "group": group,
        "group_input": await client.get_input_entity(group),
        "sources": sources,
        "source_id_to_name": source_id_to_name,
        "topic_ids": {item["topic_no"]: item["topic_id"] for item in profile["topics"]},
        "topic_titles": {item["topic_no"]: active_by_id[item["topic_id"]].title
                         for item in profile["topics"]},
    }


def forwarded_message_from(result, group_id, types, utils):
    messages = [
        update.message for update in getattr(result, "updates", [])
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage))
        and utils.get_peer_id(update.message.peer_id) == group_id
    ]
    if len(messages) != 1:
        raise RuntimeError("Telegram tidak mengembalikan satu hasil forward yang pasti.")
    return messages[0]


async def run_service(args, TelegramClient, events, errors,
                      functions, helpers, types, utils):
    config_path = DATA / "config.json"
    if not config_path.exists():
        raise RuntimeError("Jalankan dulu: python worker.py --setup")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (config.get("version") != 10 or not config.get("relay")
            or len(config.get("profiles", [])) != 5):
        raise RuntimeError("Konfigurasi bukan versi relay Amela + 5 admin / 3 topic.")

    runtimes = []
    all_runtimes = []
    store = None
    stopping = False
    lock = asyncio.Lock()
    last_send_by_account = {}
    reply_locks = {}

    def status(name, state, detail="", flood_until=None):
        try:
            db_set_status(name, state, detail, flood_until)
        except Exception:
            pass

    def log(message, level="INFO", source="worker"):
        print(message)
        try:
            db_add_log(message, level, source)
        except Exception:
            pass

    async def account_floodwait(runtime, seconds):
        name = runtime["profile"]["name"]
        until = time.time() + max(0, int(seconds))
        status(name, "FLOODWAIT", f"Tunggu {int(seconds)} detik", until)
        log(f"{name} FloodWait {int(seconds)} detik.", "WARN", name)
        await asyncio.sleep(max(0, int(seconds)))
        status(name, "READY", "Siap mengirim")

    async def shutdown():
        nonlocal stopping
        if stopping:
            return
        stopping = True
        status("WORKER", "STOPPING", "Worker sedang berhenti")
        await asyncio.gather(
            *(runtime["client"].disconnect() for runtime in all_runtimes),
            return_exceptions=True)
        for runtime in runtimes:
            status(runtime["profile"]["name"], "OFFLINE", "Worker berhenti")
        status("Amela", "OFFLINE", "Worker berhenti")
        status("WORKER", "OFFLINE", "Worker berhenti")

    try:
        relay_runtime = await connect_relay_runtime(config, TelegramClient, utils)
        all_runtimes.append(relay_runtime)
        for profile in config["profiles"]:
            runtime = await connect_runtime(
                config, profile, TelegramClient, functions, types, utils)
            runtimes.append(runtime)
            all_runtimes.append(runtime)
        topic_ids = {}
        for runtime in runtimes:
            for topic_no, topic_id in runtime["topic_ids"].items():
                topic_ids.setdefault(topic_no, topic_id)
        group_id = config["group_id"]
        reply_locks = {
            runtime["profile"]["account_id"]: asyncio.Lock()
            for runtime in runtimes
        }
        store = Store(DATA / "routes_v10.sqlite3")
        db_init()
        status("WORKER", "RUNNING", "Telegram worker aktif")
        status("Amela", "READY", "Relay aktif")
        for runtime in runtimes:
            status(runtime["profile"]["name"], "READY", "Siap mengirim")
        mode = "KIRIM AKTIF" if args.live else "UJI — belum mengirim komentar"

        async def report(runtime, reply_message_id, text):
            try:
                await runtime["client"].send_message(
                    runtime["group"], text, reply_to=reply_message_id,
                    parse_mode=None, link_preview=False)
            except errors.FloodWaitError as exc:
                await account_floodwait(runtime, exc.seconds)
            except Exception:
                print(f"Status {runtime['profile']['label']} gagal dikirim.")

        async def distribute(base_key, event):
            found = matching_keywords(event.raw_text)
            if not found:
                return
            target_topics = targets_for_base(base_key)
            if not store.reserve_post(event.chat_id, event.id, target_topics):
                return
            if (getattr(event.message, "noforwards", False)
                    or getattr(relay_runtime["sources"][base_key], "noforwards", False)):
                print(f"@{base_key} #{event.id} dilindungi; tidak diteruskan.")
                for topic_no in target_topics:
                    store.set_route(topic_no, event.chat_id, event.id, None, "protected")
                store.finish_post(event.chat_id, event.id)
                return

            source_input = await relay_runtime["client"].get_input_entity(
                relay_runtime["sources"][base_key])
            for index, topic_no in enumerate(target_topics):
                topic_id = topic_ids[topic_no]
                try:
                    request = functions.messages.ForwardMessagesRequest(
                        from_peer=source_input, id=[event.id],
                        to_peer=relay_runtime["group_input"],
                        random_id=[helpers.generate_random_long()],
                        top_msg_id=topic_id,
                        silent=False)
                    result = await relay_runtime["client"](request)
                    forwarded = forwarded_message_from(result, group_id, types, utils)
                    store.set_route(topic_no, event.chat_id, event.id, forwarded.id)
                    print(f"@{base_key} #{event.id} → Topic {topic_no}; "
                          f"keyword: {', '.join(found)}")
                except errors.FloodWaitError:
                    store.set_route(topic_no, event.chat_id, event.id, None, "failed")
                    raise
                except Exception as exc:
                    store.set_route(topic_no, event.chat_id, event.id, None, "failed")
                    print(f"Forward ke Topic {topic_no} gagal ({type(exc).__name__}).")
                if index < len(target_topics) - 1:
                    await asyncio.sleep(1.5)
            store.finish_post(event.chat_id, event.id)

        async def process_reply(runtime, event):
            profile = runtime["profile"]
            incoming_topic_id = event_topic_id(event.message)
            topic_no = next(
                (number for number, topic_id in runtime["topic_ids"].items()
                 if topic_id == incoming_topic_id),
                None)
            if topic_no is None:
                return
            if not eligible_reply(
                    event, profile["account_id"], group_id,
                    runtime["topic_ids"][topic_no]):
                return
            source = store.source_for_reply(topic_no, event.reply_to_msg_id)
            if source is None:
                return
            source_chat_id, source_message_id = source
            base_key = runtime["source_id_to_name"].get(source_chat_id)
            if base_key is None:
                await report(runtime, event.id,
                             "Tidak dikirim: akun ini tidak memiliki akses ke base sumber.")
                return
            raw_reply = event.raw_text or ""
            text, choice = selected_text(raw_reply)
            # Pengaman: reply "1"/"2"/"3"/"4" wajib sudah berubah menjadi wording.
            if choice in ("1", "2", "3", "4", "5") and text.strip() == choice:
                await report(runtime, event.id,
                             "GAGAL INTERNAL: angka pilihan belum berubah menjadi wording.")
                return

            media = event.message.media
            if not text.strip() or (media and not isinstance(media, types.MessageMediaWebPage)):
                await report(runtime, event.id,
                             "Tidak dikirim: hanya reply teks atau angka 1 sampai 4.")
                return
            if len(text.encode("utf-16-le")) // 2 > 4096:
                await report(runtime, event.id, "Tidak dikirim: wording terlalu panjang.")
                return
            if not store.claim_reply(
                    profile["account_id"], topic_no, source_chat_id,
                    source_message_id, event.id, args.live):
                return
            if not args.live:
                label = f"Wording {choice}" if choice in ("1", "2", "3", "4", "5") else "teks manual"
                await report(
                    runtime, event.id,
                    f"UJI BERHASIL — {profile['label']} memilih {label} untuk "
                    f"@{base_key} #{source_message_id}. Belum dikirim ke base.")
                return

            source_entity = runtime["sources"][base_key]
            try:
                formatting = event.message.entities if choice == "manual" else None

                # FAST SEND:
                # Pengiriman pertama langsung. Jeda 1 detik hanya berlaku jika
                # akun yang SAMA baru saja mengirim komentar sebelumnya.
                account_id = profile["account_id"]
                previous = last_send_by_account.get(account_id, 0.0)
                elapsed = time.monotonic() - previous
                if elapsed < 1.0:
                    await asyncio.sleep(1.0 - elapsed)

                sent = await runtime["client"].send_message(
                    source_entity, text, comment_to=source_message_id,
                    parse_mode=None, formatting_entities=formatting,
                    link_preview=False)
                last_send_by_account[account_id] = time.monotonic()
                store.finish_job(
                    profile["account_id"], event.id, "sent", sent.id)
                log(
                    f"{profile['name']} berhasil kirim Wording {choice} ke @{base_key} "
                    f"#{source_message_id}.",
                    "INFO", profile["name"]
                )

                actual_username = getattr(runtime.get("me"), "username", None)
                account_text = (
                    f"{profile['name']} @{actual_username}"
                    if actual_username else profile["name"]
                )
                try:
                    await event.edit(
                        f"{choice} | {account_text} berhasil kirim ke base @{base_key}"
                    )
                except Exception as edit_exc:
                    print(
                        f"Status reply {profile['name']} tidak bisa diedit "
                        f"({type(edit_exc).__name__}), tetapi komentar sudah terkirim."
                    )

            except errors.FloodWaitError as exc:
                store.finish_job(profile["account_id"], event.id, "failed")
                try:
                    await event.edit(
                        f"{choice} | FLOODWAIT {exc.seconds}s — coba lagi setelah selesai"
                    )
                except Exception:
                    pass
                await account_floodwait(runtime, exc.seconds)
                return
            except errors.RPCError:
                store.finish_job(profile["account_id"], event.id, "failed")
                try:
                    await event.edit(f"{choice} | GAGAL KIRIM")
                except Exception:
                    pass
                return
            except Exception:
                store.finish_job(profile["account_id"], event.id, "uncertain")
                try:
                    await event.edit(f"{choice} | GAGAL KIRIM")
                except Exception:
                    pass
                return

        def collector_handler():
            async def safe(event):
                async with lock:
                    try:
                        base_key = relay_runtime["source_id_to_name"].get(event.chat_id)
                        if base_key:
                            await distribute(base_key, event)
                    except errors.FloodWaitError as exc:
                        until = time.time() + int(exc.seconds)
                        status("Amela", "FLOODWAIT", f"Tunggu {exc.seconds} detik", until)
                        log(f"Amela FloodWait {exc.seconds} detik.", "WARN", "Amela")
                        await asyncio.sleep(int(exc.seconds))
                        status("Amela", "READY", "Relay aktif")
                    except Exception as exc:
                        print(f"Posting tidak selesai ({type(exc).__name__}).")
            return safe

        def reply_handler(runtime):
            async def safe(event):
                account_id = runtime["profile"]["account_id"]
                async with reply_locks[account_id]:
                    try:
                        await process_reply(runtime, event)
                    except errors.FloodWaitError as exc:
                        await account_floodwait(runtime, exc.seconds)
                    except Exception as exc:
                        print(f"Reply {runtime['profile']['label']} gagal "
                              f"({type(exc).__name__}).")
            return safe

        relay_runtime["client"].add_event_handler(
            collector_handler(),
            events.NewMessage(chats=list(relay_runtime["sources"].values())))
        for runtime in runtimes:
            runtime["client"].add_event_handler(
                reply_handler(runtime), events.NewMessage(chats=[runtime["group"]]))

        active_keywords = len(db_get_keywords() or KEYWORDS)
        log(
            f"{mode}. Relay Amela + 5 admin, 3 topic, 9 base, "
            f"5 wording dan {active_keywords} keyword aktif."
        )
        await asyncio.gather(
            *(runtime["client"].run_until_disconnected()
              for runtime in all_runtimes))
    finally:
        await shutdown()
        if store:
            store.close()


def self_test():
    import tempfile
    import unittest
    from types import SimpleNamespace as NS

    class Tests(unittest.TestCase):
        def test_configuration(self):
            self.assertEqual(len(KEYWORDS), 71)
            self.assertEqual(len(set(KEYWORDS)), 71)
            self.assertEqual(set(targets_for_base("@basewtb")), {1})
            self.assertEqual(set(targets_for_base("@basewib")), {1})
            self.assertEqual(set(targets_for_base("moneyfess")), {2})
            self.assertEqual(set(targets_for_base("jockeyfess")), {2})
            self.assertEqual(set(targets_for_base("dagangfess")), {3})
            self.assertEqual(set(targets_for_base("BukaLapakBA")), {3})
            self.assertEqual(len(set(normalized(x) for x in ALL_BASES)), 9)
            self.assertEqual(PROFILE_COUNT, 5)
            self.assertTrue(all(plan["topic_nos"] == (1, 2, 3) for plan in RESPONDER_PLAN))

        def test_dialog_username_aliases(self):
            entity = NS(
                username="nama_utama",
                usernames=(NS(username="basewtb", active=True),
                           NS(username="alias_lama", active=False)),
            )
            dialog = NS(entity=entity)
            mapped = username_dialog_map([dialog])
            self.assertIs(mapped["nama_utama"], dialog)
            self.assertIs(mapped["basewtb"], dialog)
            self.assertNotIn("alias_lama", mapped)

        def test_matching(self):
            self.assertTrue(matches("Butuh JOKI TUGAS dan PPT"))
            self.assertEqual(matching_keywords("butuh edit video dan poster"),
                             ("poster", "edit video"))
            self.assertTrue(matches("jasa UI/UX"))
            self.assertFalse(matches("posterior dan laporanmu"))
            self.assertFalse(matches("tidak relevan"))

        def test_wording_trigger(self):
            self.assertEqual(selected_text(" 1 "), (WORDING_1, "1"))
            self.assertEqual(selected_text("2"), (WORDING_2, "2"))
            self.assertEqual(selected_text("3"), (WORDING_3, "3"))
            self.assertEqual(selected_text("4"), (WORDING_4, "4"))
            self.assertEqual(selected_text("5"), (WORDING_5, "5"))
            self.assertEqual(selected_text("5"), (WORDING_5, "5"))
            self.assertEqual(selected_text("Halo seller"), ("Halo seller", "manual"))
            for n in ("1", "2", "3", "4", "5"):
                self.assertNotEqual(selected_text(n)[0], n)

        def test_reply_identity_topic(self):
            header = NS(reply_to_top_id=77, reply_to_msg_id=500, forum_topic=True)
            message = NS(reply_to=header, fwd_from=None, via_bot_id=None, action=None)
            event = NS(chat_id=-100, sender_id=10, reply_to_msg_id=500,
                       message=message)
            self.assertTrue(eligible_reply(event, 10, -100, 77))
            self.assertFalse(eligible_reply(event, 11, -100, 77))
            self.assertFalse(eligible_reply(event, 10, -100, 78))

        def test_routes_and_one_attempt_per_account(self):
            with tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "state.sqlite3")
                self.assertTrue(store.reserve_post(-101, 5, (1,)))
                self.assertFalse(store.reserve_post(-101, 5, (1,)))
                store.set_route(1, -101, 5, 1001)
                self.assertEqual(store.source_for_reply(1, 1001), (-101, 5))
                self.assertTrue(store.claim_reply(10, 1, -101, 5, 2001, True))
                self.assertTrue(store.claim_reply(10, 1, -101, 5, 2002, True))
                self.assertFalse(store.claim_reply(10, 1, -101, 5, 2001, True))
                self.assertTrue(store.claim_reply(11, 1, -101, 5, 2003, True))
                store.close()

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    raise SystemExit(0 if result.wasSuccessful() else 1)


async def async_main(args):
    try:
        from telethon import TelegramClient, events, errors, functions, helpers, types, utils
    except ImportError:
        raise RuntimeError("Install dulu: python -m pip install Telethon==1.44.0")
    if args.setup:
        await run_setup(TelegramClient, functions, types, utils)
    else:
        await run_service(
            args, TelegramClient, events, errors, functions, helpers, types, utils)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--setup", action="store_true",
                       help="Login relay Amela dan 4 admin; 2 akun terakhir bisa General + Special.")
    modes.add_argument("--live", action="store_true",
                       help="Izinkan reply baru menjadi komentar sungguhan.")
    modes.add_argument("--self-test", action="store_true",
                       help="Uji logika lokal tanpa Telegram.")
    args = parser.parse_args()
    if not getattr(args, "setup", False) and not getattr(args, "self_test", False):
        args.live = True
    if args.self_test:
        self_test()
    os.umask(0o077)
    DATA.mkdir(mode=0o700, exist_ok=True)
    db_init()
    try:
        with single_instance(DATA / "run.lock"):
            asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nDihentikan.")
    except (RuntimeError, ValueError) as exc:
        print(f"Berhenti: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"Berhenti ({type(exc).__name__}). Periksa koneksi/konfigurasi. "
              "Jangan bagikan sesi, API hash, atau OTP.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
