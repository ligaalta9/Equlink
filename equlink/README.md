# EQUILINK
Sistem Edukasi Keadilan Penggunaan Energi dan Air berbasis IoT + AI.

## Struktur
- app.py: Flask API, database, MQTT subscriber/publisher, Gemini proxy
- templates/index.html: dashboard
- static/style.css: UI
- static/app.js: frontend logic
- esp32/equilink_esp32.ino: firmware dasar

## Local
1. Python 3.12+
2. `python -m venv .venv`
3. Windows: `.venv\\Scripts\\activate`; Linux: `source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. copy `.env.example` -> `.env` dan isi variabel
6. `python app.py`
7. buka http://localhost:5000

## Production
Gunakan Render untuk Flask + Supabase PostgreSQL + EMQX Cloud + Gemini API. Jangan taruh API key Gemini di frontend.

## MQTT topics sesuai proposal
`equilink/room1/sensor`
`equilink/room2/sensor`
`equilink/water/sensor`
`equilink/room1/relay`
`equilink/room2/relay`
`equilink/water/pump`
