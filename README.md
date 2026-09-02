# Berline Menfess Web

Versi web-control dari `menfess_wtb.py`.

## Yang tetap sama
- Telegram tetap pusat kerja.
- Menfess tetap masuk ke 3 topic.
- Admin tetap reply `1`–`5` dari topic.
- Akun Telegram admin yang mengirim reply ke base.

## Yang berubah
- `worker.py` berjalan di background server.
- Dashboard punya RUN / STOP / RESTART.
- Wording dan keyword disimpan di `control.sqlite3`.
- FloodWait admin mem-pause akun itu saja; akun lain tetap berjalan.
- Status dan log muncul di dashboard.

## Data penting
Folder `.menfess_relay_data` berisi config + session Telegram. JANGAN taruh folder ini di GitHub publik.

Untuk cloud gunakan persistent volume dan set:
- `MENFESS_DATA_DIR=/data/telegram`
- `MENFESS_CONTROL_DB=/data/control.sqlite3`

Start command:
`uvicorn dashboard:app --host 0.0.0.0 --port $PORT`

## Setup pertama
Project ini sengaja mempertahankan session Telegram lama. Copy folder `.menfess_relay_data`
dari project lama ke persistent storage server. Setelah itu dashboard dapat menjalankan worker
tanpa CMD/VS Code harian.

Catatan: hosting gratis tidak bisa dijamin hidup 24/7 selamanya. Worker Telegram memerlukan
compute yang selalu aktif.
