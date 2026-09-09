import os
import json
import threading
import secrets
import hashlib
import time

from datetime import datetime, timezone
from functools import wraps

import requests
import paho.mqtt.client as mqtt

from flask import Flask, jsonify, request, session, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_proto=1,
    x_host=1
)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///equlink.db"
)

DATABASE_URL = DATABASE_URL.replace(
    "postgres://",
    "postgresql://"
)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# CONFIGURATION
# ============================================================

ELECTRICITY_TARIFF = float(
    os.getenv("ELECTRICITY_TARIFF", "1444.70")
)

# Untuk sementara tarif air dapat diatur melalui ENV.
# Jangan menganggap HC-SR04 sebagai flow meter.
WATER_TARIFF_PER_LITER = float(
    os.getenv("WATER_TARIFF_PER_LITER", "0")
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
)

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)

MQTT_HOST = os.getenv(
    "MQTT_HOST",
    "broker.emqx.io"
)

MQTT_PORT = int(
    os.getenv("MQTT_PORT", "1883")
)

MQTT_USERNAME = os.getenv(
    "MQTT_USERNAME",
    ""
)

MQTT_PASSWORD = os.getenv(
    "MQTT_PASSWORD",
    ""
)

MQTT_TLS = (
    os.getenv("MQTT_TLS", "false").lower()
    == "true"
)


# ============================================================
# MQTT TOPICS
# ============================================================

TOPICS = {

    # SENSOR
    "r1_sensor": "equilink/r1/elec",
    "r2_sensor": "equilink/r2/elec",
    "water_sensor": "equilink/water",

    # RELAY COMMAND
    "r1_lamp": "equilink/r1/lamp",
    "r1_power": "equilink/r1/power",

    "r2_lamp": "equilink/r2/lamp",
    "r2_power": "equilink/r2/power",

    "water_pump": "equilink/water/pump",

    # STATUS
    "r1_status": "equilink/r1/status",
    "r2_status": "equilink/r2/status",
    "water_status": "equilink/water/status"
}


# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(128),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        nullable=False
    )

    room = db.Column(
        db.Integer,
        nullable=True
    )


class SensorReading(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    room_id = db.Column(
        db.Integer,
        nullable=False,
        index=True
    )

    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    voltage = db.Column(
        db.Float,
        default=0
    )

    current = db.Column(
        db.Float,
        default=0
    )

    power = db.Column(
        db.Float,
        default=0
    )

    # INI ADALAH ENERGY KUMULATIF DARI PZEM
    energy_kwh = db.Column(
        db.Float,
        default=0
    )


class WaterReading(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    distance_cm = db.Column(
        db.Float,
        default=0
    )

    level_percent = db.Column(
        db.Float,
        default=0
    )

    pump_on = db.Column(
        db.Boolean,
        default=False
    )


class RelayState(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    room_id = db.Column(
        db.Integer,
        nullable=False
    )

    device = db.Column(
        db.String(30),
        nullable=False
    )

    state = db.Column(
        db.Boolean,
        default=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


class BillingPeriod(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(80),
        nullable=False
    )

    started_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    ended_at = db.Column(
        db.DateTime
    )

    status = db.Column(
        db.String(20),
        default="active"
    )


class Bill(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    period_id = db.Column(
        db.Integer,
        nullable=False
    )

    room_id = db.Column(
        db.Integer,
        nullable=False
    )

    energy_kwh = db.Column(
        db.Float,
        default=0
    )

    energy_cost = db.Column(
        db.Float,
        default=0
    )

    water_cost = db.Column(
        db.Float,
        default=0
    )

    total_cost = db.Column(
        db.Float,
        default=0
    )

    paid_amount = db.Column(
        db.Float,
        default=0
    )


class Payment(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    room_id = db.Column(
        db.Integer,
        nullable=False
    )

    period_id = db.Column(
        db.Integer,
        nullable=False
    )

    amount = db.Column(
        db.Float,
        nullable=False
    )

    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    note = db.Column(
        db.String(255)
    )


# ============================================================
# HELPER
# ============================================================

def hash_password(password):

    return hashlib.sha256(
        password.encode()
    ).hexdigest()


def now_utc():

    return datetime.now(timezone.utc)


# ============================================================
# SEED DATABASE
# ============================================================

def seed_database():

    db.create_all()

    users = [
        (
            "admin",
            "admin123",
            "admin",
            None
        ),
        (
            "user1",
            "user123",
            "user",
            1
        ),
        (
            "user2",
            "user123",
            "user",
            2
        )
    ]

    for username, password, role, room in users:

        existing = User.query.filter_by(
            username=username
        ).first()

        if not existing:

            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    room=room
                )
            )

    if not BillingPeriod.query.filter_by(
        status="active"
    ).first():

        db.session.add(
            BillingPeriod(
                name=datetime.now().strftime("%B %Y"),
                status="active"
            )
        )

    db.session.commit()


# ============================================================
# AUTHENTICATION
# ============================================================

def current_user():

    uid = session.get("uid")

    if not uid:
        return None

    return db.session.get(
        User,
        uid
    )


def auth(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user:

            return jsonify(
                error="Unauthorized"
            ), 401

        return func(*args, **kwargs)

    return wrapper


def room_allowed(user, room):

    return (
        user.role == "admin"
        or user.room == room
    )


# ============================================================
# BILLING PERIOD
# ============================================================

def active_period():

    return (
        BillingPeriod.query
        .filter_by(status="active")
        .order_by(BillingPeriod.id.desc())
        .first()
    )


# ============================================================
# ENERGY CALCULATION
# ============================================================

def get_period_energy(room_id, period):

    """
    PZEM energy_kwh adalah nilai kumulatif.

    Contoh:

    sebelum periode:
        100 kWh

    akhir periode:
        135 kWh

    penggunaan:
        135 - 100 = 35 kWh
    """

    first = (
        SensorReading.query
        .filter(
            SensorReading.room_id == room_id,
            SensorReading.timestamp >= period.started_at
        )
        .order_by(SensorReading.timestamp.asc())
        .first()
    )

    latest = (
        SensorReading.query
        .filter(
            SensorReading.room_id == room_id,
            SensorReading.timestamp >= period.started_at
        )
        .order_by(SensorReading.timestamp.desc())
        .first()
    )

    if not first or not latest:

        return 0.0

    energy = (
        latest.energy_kwh
        - first.energy_kwh
    )

    # Proteksi apabila meter di-reset
    if energy < 0:

        energy = latest.energy_kwh

    return max(
        0.0,
        energy
    )


# ============================================================
# BILL CALCULATION
# ============================================================

def compute_bills():

    period = active_period()

    if not period:

        return {}

    result = {}

    for room_id in [1, 2]:

        energy = get_period_energy(
            room_id,
            period
        )

        energy_cost = (
            energy
            * ELECTRICITY_TARIFF
        )

        bill = (
            Bill.query
            .filter_by(
                period_id=period.id,
                room_id=room_id
            )
            .first()
        )

        if not bill:

            bill = Bill(
                period_id=period.id,
                room_id=room_id
            )

            db.session.add(bill)

        bill.energy_kwh = energy

        bill.energy_cost = energy_cost

        # ====================================================
        # PENTING:
        #
        # HC-SR04 hanya membaca LEVEL TANGKI.
        #
        # Tidak boleh mengarang penggunaan air per kamar.
        #
        # Jadi default 0 sampai sistem memiliki flow meter
        # atau metode alokasi air yang benar.
        # ====================================================

        bill.water_cost = 0

        bill.total_cost = (
            bill.energy_cost
            + bill.water_cost
        )

        result[room_id] = bill

    db.session.commit()

    return result


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.post("/api/login")
def login():

    data = request.get_json(
        silent=True
    ) or {}

    username = data.get(
        "username",
        ""
    ).strip()

    password = data.get(
        "password",
        ""
    )

    user = User.query.filter_by(
        username=username
    ).first()

    if (
        not user
        or user.password_hash
        != hash_password(password)
    ):

        return jsonify(
            error="Username/password salah"
        ), 401

    session["uid"] = user.id

    return jsonify(
        user={
            "username": user.username,
            "role": user.role,
            "room": user.room
        }
    )


# ============================================================
# LOGOUT
# ============================================================

@app.post("/api/logout")
def logout():

    session.clear()

    return jsonify(
        ok=True
    )


# ============================================================
# STATE
# ============================================================

@app.get("/api/state")
@auth
def state():

    user = current_user()

    compute_bills()

    period = active_period()

    allowed_rooms = (
        [1, 2]
        if user.role == "admin"
        else [user.room]
    )

    bills = {}

    if period:

        bill_rows = Bill.query.filter_by(
            period_id=period.id
        ).all()

        bills = {
            b.room_id: b
            for b in bill_rows
        }

    rooms = {}

    for room_id in allowed_rooms:

        reading = (
            SensorReading.query
            .filter_by(room_id=room_id)
            .order_by(
                SensorReading.timestamp.desc()
            )
            .first()
        )

        bill = bills.get(room_id)

        relay_rows = RelayState.query.filter_by(
            room_id=room_id
        ).all()

        relay_map = {
            row.device: bool(row.state)
            for row in relay_rows
        }

        rooms[str(room_id)] = {

            "online": reading is not None,

            "last_update": (
                reading.timestamp.isoformat()
                if reading
                else None
            ),

            "sensor": {

                "voltage": (
                    reading.voltage
                    if reading else None
                ),

                "current": (
                    reading.current
                    if reading else None
                ),

                "power": (
                    reading.power
                    if reading else None
                ),

                "energy_kwh": (
                    reading.energy_kwh
                    if reading else None
                )
            },

            "relay": {

                "lamp": relay_map.get(
                    "lamp",
                    False
                ),

                "outlet": relay_map.get(
                    "power",
                    False
                )
            },

            "bill": {

                "energy_kwh": (
                    bill.energy_kwh
                    if bill else 0
                ),

                "energy_cost": (
                    bill.energy_cost
                    if bill else 0
                ),

                "water_cost": (
                    bill.water_cost
                    if bill else 0
                ),

                "total_cost": (
                    bill.total_cost
                    if bill else 0
                ),

                "paid_amount": (
                    bill.paid_amount
                    if bill else 0
                )
            }
        }

    water = (
        WaterReading.query
        .order_by(
            WaterReading.timestamp.desc()
        )
        .first()
    )

    return jsonify(

        rooms=rooms,

        water={

            "online": water is not None,

            "distance_cm": (
                water.distance_cm
                if water else None
            ),

            "level_percent": (
                water.level_percent
                if water else None
            ),

            "pump_on": (
                bool(water.pump_on)
                if water else False
            ),

            "last_update": (
                water.timestamp.isoformat()
                if water else None
            )
        },

        mqtt={
            "connected": (
                mqtt_client is not None
                and mqtt_client.is_connected()
            )
        }
    )


# ============================================================
# HISTORY
# ============================================================

@app.get("/api/history")
@auth
def history():

    user = current_user()

    allowed_rooms = (
        [1, 2]
        if user.role == "admin"
        else [user.room]
    )

    rows = (
        SensorReading.query
        .filter(
            SensorReading.room_id.in_(
                allowed_rooms
            )
        )
        .order_by(
            SensorReading.timestamp.desc()
        )
        .limit(500)
        .all()
    )

    return jsonify(

        rows=[

            {
                "room": row.room_id,

                "timestamp":
                    row.timestamp.isoformat(),

                "voltage":
                    row.voltage,

                "current":
                    row.current,

                "power":
                    row.power,

                "energy_kwh":
                    row.energy_kwh
            }

            for row in rows
        ]
    )


# ============================================================
# PAYMENTS
# ============================================================

@app.get("/api/payments")
@auth
def payments():

    user = current_user()

    allowed_rooms = (
        [1, 2]
        if user.role == "admin"
        else [user.room]
    )

    rows = (
        Payment.query
        .filter(
            Payment.room_id.in_(
                allowed_rooms
            )
        )
        .order_by(
            Payment.timestamp.desc()
        )
        .limit(500)
        .all()
    )

    return jsonify(

        rows=[

            {
                "id": row.id,

                "room":
                    row.room_id,

                "amount":
                    row.amount,

                "timestamp":
                    row.timestamp.isoformat(),

                "note":
                    row.note or ""
            }

            for row in rows
        ]
    )


# ============================================================
# PAYMENT
# ============================================================

@app.post("/api/payment")
@auth
def payment():

    user = current_user()

    data = request.get_json(
        silent=True
    ) or {}

    try:

        room = int(
            data.get("room")
        )

        amount = float(
            data.get("amount", 0)
        )

    except (
        ValueError,
        TypeError
    ):

        return jsonify(
            error="Data pembayaran tidak valid"
        ), 400

    if not room_allowed(
        user,
        room
    ):

        return jsonify(
            error="Akses ditolak"
        ), 403

    if amount <= 0:

        return jsonify(
            error="Nominal pembayaran harus > 0"
        ), 400

    period = active_period()

    if not period:

        return jsonify(
            error="Tidak ada periode aktif"
        ), 400

    compute_bills()

    bill = Bill.query.filter_by(
        period_id=period.id,
        room_id=room
    ).first()

    if not bill:

        return jsonify(
            error="Tagihan belum tersedia"
        ), 400

    remaining = max(
        0,
        bill.total_cost
        - bill.paid_amount
    )

    if amount > remaining:

        return jsonify(
            error=(
                "Pembayaran melebihi "
                "sisa tagihan"
            )
        ), 400

    bill.paid_amount += amount

    db.session.add(
        Payment(
            room_id=room,
            period_id=period.id,
            amount=amount,
            note=data.get(
                "note",
                "Pembayaran"
            )
        )
    )

    db.session.commit()

    return jsonify(
        ok=True,
        paid_amount=bill.paid_amount,
        remaining=max(
            0,
            bill.total_cost
            - bill.paid_amount
        )
    )


# ============================================================
# RELAY
# ============================================================

@app.post("/api/relay")
@auth
def relay():

    user = current_user()

    data = request.get_json(
        silent=True
    ) or {}

    try:

        room = int(
            data.get("room")
        )

    except (
        ValueError,
        TypeError
    ):

        return jsonify(
            error="Room tidak valid"
        ), 400

    device = data.get(
        "device"
    )

    if device not in [
        "lamp",
        "power"
    ]:

        return jsonify(
            error="Device harus lamp/power"
        ), 400

    state_value = bool(
        data.get(
            "state",
            False
        )
    )

    if not room_allowed(
        user,
        room
    ):

        return jsonify(
            error="Akses ditolak"
        ), 403

    if not mqtt_client or not mqtt_client.is_connected():

        return jsonify(
            error="MQTT offline"
        ), 503

    topic = (
        f"equilink/r{room}/{device}"
    )

    payload = (
        "on"
        if state_value
        else "off"
    )

    result = mqtt_client.publish(
        topic,
        payload,
        qos=1,
        retain=True
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:

        return jsonify(
            error="Gagal publish MQTT"
        ), 503

    save_relay_state(
        room,
        device,
        state_value
    )

    return jsonify(
        ok=True,
        room=room,
        device=device,
        state=state_value
    )


# ============================================================
# SAVE RELAY STATE
# ============================================================

def save_relay_state(
    room,
    device,
    state_value
):

    row = RelayState.query.filter_by(
        room_id=room,
        device=device
    ).first()

    if not row:

        row = RelayState(
            room_id=room,
            device=device
        )

        db.session.add(row)

    row.state = state_value
    row.updated_at = now_utc()

    db.session.commit()


# ============================================================
# PUMP
# ============================================================

@app.post("/api/pump")
@auth
def pump():

    user = current_user()

    if user.role != "admin":

        return jsonify(
            error="Admin only"
        ), 403

    data = request.get_json(
        silent=True
    ) or {}

    state_value = bool(
        data.get(
            "state",
            False
        )
    )

    if not mqtt_client or not mqtt_client.is_connected():

        return jsonify(
            error="MQTT offline"
        ), 503

    payload = (
        "on"
        if state_value
        else "off"
    )

    mqtt_client.publish(
        TOPICS["water_pump"],
        payload,
        qos=1,
        retain=True
    )

    return jsonify(
        ok=True,
        state=state_value
    )


# ============================================================
# NEW BILLING PERIOD
# ============================================================

@app.post("/api/period/new")
@auth
def new_period():

    user = current_user()

    if user.role != "admin":

        return jsonify(
            error="Admin only"
        ), 403

    old = active_period()

    if old:

        compute_bills()

        old.status = "closed"

        old.ended_at = now_utc()

    new_period = BillingPeriod(
        name=datetime.now().strftime(
            "%B %Y"
        ),
        status="active"
    )

    db.session.add(
        new_period
    )

    db.session.commit()

    return jsonify(
        ok=True,
        period_id=new_period.id
    )


# ============================================================
# EDUCATION
# ============================================================

@app.get("/api/education")
@auth
def education():

    return jsonify(

        lessons=[

            {
                "title":
                    "Equality vs Equity",

                "body":
                    (
                        "Equality membagi sama rata, "
                        "sedangkan equity membagi "
                        "secara proporsional berdasarkan "
                        "penggunaan aktual."
                    )
            },

            {
                "title":
                    "Hemat Listrik",

                "body":
                    (
                        "Matikan perangkat yang tidak "
                        "digunakan dan kurangi penggunaan "
                        "perangkat dalam kondisi standby."
                    )
            },

            {
                "title":
                    "Transparansi Tagihan",

                "body":
                    (
                        "Penggunaan energi dicatat secara "
                        "digital sehingga penghuni dapat "
                        "melihat dasar perhitungan tagihan."
                    )
            }
        ],

        quiz=[

            {
                "q":
                    (
                        "Jika Kamar 1 menggunakan "
                        "60 kWh dan Kamar 2 menggunakan "
                        "40 kWh, proporsi penggunaan "
                        "Kamar 1 adalah?"
                    ),

                "options": [
                    "50%",
                    "60%",
                    "75%"
                ],

                "answer": 1
            }
        ]
    )


# ============================================================
# AI
# ============================================================

@app.post("/api/ai")
@auth
def ai():

    user = current_user()

    if not GEMINI_API_KEY:

        return jsonify(
            error="GEMINI_API_KEY belum diatur"
        ), 503

    data = request.get_json(
        silent=True
    ) or {}

    query = (
        data.get(
            "query",
            ""
        )
        .strip()
    )

    if not query:

        return jsonify(
            error="Pertanyaan kosong"
        ), 400

    # ========================================================
    # BATASI DATA AI BERDASARKAN USER
    # ========================================================

    allowed_rooms = (
        [1, 2]
        if user.role == "admin"
        else [user.room]
    )

    compute_bills()

    context = []

    for room_id in allowed_rooms:

        reading = (
            SensorReading.query
            .filter_by(
                room_id=room_id
            )
            .order_by(
                SensorReading.timestamp.desc()
            )
            .first()
        )

        period = active_period()

        bill = None

        if period:

            bill = Bill.query.filter_by(
                period_id=period.id,
                room_id=room_id
            ).first()

        context.append({

            "room":
                room_id,

            "voltage":
                reading.voltage
                if reading else None,

            "current":
                reading.current
                if reading else None,

            "power":
                reading.power
                if reading else None,

            "energy_meter":
                reading.energy_kwh
                if reading else None,

            "period_energy":
                bill.energy_kwh
                if bill else 0,

            "bill":
                bill.total_cost
                if bill else 0
        })

    prompt = f"""
Anda adalah AI Consultant untuk sistem EQUILINK.

User role:
{user.role}

Data yang boleh dianalisis:
{json.dumps(context, indent=2)}

Pertanyaan pengguna:
{query}

Berikan jawaban dalam Bahasa Indonesia.
Jangan mengarang data sensor.
Jika data tidak tersedia, katakan bahwa data belum tersedia.
Jangan memberikan instruksi untuk mengendalikan relay
secara langsung.
Fokus pada edukasi, efisiensi energi, transparansi,
dan keadilan penggunaan.
"""

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    try:

        response = requests.post(

            url,

            headers={
                "x-goog-api-key":
                    GEMINI_API_KEY,

                "Content-Type":
                    "application/json"
            },

            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "text":
                                    prompt
                            }
                        ]
                    }
                ]
            },

            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        answer = (
            result[
                "candidates"
            ][0][
                "content"
            ][
                "parts"
            ][0][
                "text"
            ]
        )

        return jsonify(
            answer=answer
        )

    except Exception as exc:

        app.logger.exception(
            "Gemini error"
        )

        return jsonify(
            error=f"AI error: {exc}"
        ), 502


# ============================================================
# MQTT PARSER
# ============================================================

def safe_float(
    value,
    default=0.0
):

    try:

        return float(value)

    except (
        ValueError,
        TypeError
    ):

        return default


# ============================================================
# PROCESS ROOM SENSOR
# ============================================================

def process_room_sensor(
    room_id,
    payload
):

    electricity = payload.get(
        "electricity",
        payload
    )

    voltage = safe_float(
        electricity.get(
            "voltage"
        )
    )

    current = safe_float(
        electricity.get(
            "current"
        )
    )

    power = safe_float(
        electricity.get(
            "power"
        )
    )

    energy_kwh = safe_float(
        electricity.get(
            "energy_kwh"
        )
    )

    reading = SensorReading(

        room_id=room_id,

        voltage=voltage,

        current=current,

        power=power,

        energy_kwh=energy_kwh
    )

    db.session.add(
        reading
    )

    db.session.commit()

    app.logger.info(
        "ROOM %s | V=%.2f V | I=%.3f A | P=%.2f W | E=%.4f kWh",
        room_id,
        voltage,
        current,
        power,
        energy_kwh
    )


# ============================================================
# PROCESS WATER
# ============================================================

def process_water(
    payload
):

    water = payload.get(
        "water",
        payload
    )

    distance = safe_float(
        water.get(
            "distance_cm"
        )
    )

    level = safe_float(
        water.get(
            "level_percent"
        )
    )

    pump_on = bool(
        water.get(
            "pump_on",
            False
        )
    )

    reading = WaterReading(

        distance_cm=distance,

        level_percent=level,

        pump_on=pump_on
    )

    db.session.add(
        reading
    )

    db.session.commit()

    app.logger.info(
        "WATER | distance=%.2f cm | level=%.2f%% | pump=%s",
        distance,
        level,
        pump_on
    )


# ============================================================
# PROCESS RELAY STATUS
# ============================================================

def process_status(
    room_id,
    payload
):

    relay = payload.get(
        "relay",
        {}
    )

    if "lamp" in relay:

        save_relay_state(
            room_id,
            "lamp",
            bool(
                relay["lamp"]
            )
        )

    if "outlet" in relay:

        save_relay_state(
            room_id,
            "power",
            bool(
                relay["outlet"]
            )
        )


# ============================================================
# MQTT MESSAGE
# ============================================================

def process_message(
    topic,
    payload_str
):

    try:

        payload = json.loads(
            payload_str
        )

        # ----------------------------------------------------
        # ROOM 1
        # ----------------------------------------------------

        if topic == TOPICS["r1_sensor"]:

            process_room_sensor(
                1,
                payload
            )

            return

        # ----------------------------------------------------
        # ROOM 2
        # ----------------------------------------------------

        if topic == TOPICS["r2_sensor"]:

            process_room_sensor(
                2,
                payload
            )

            return

        # ----------------------------------------------------
        # WATER
        # ----------------------------------------------------

        if topic == TOPICS["water_sensor"]:

            process_water(
                payload
            )

            return

        # ----------------------------------------------------
        # ROOM STATUS
        # ----------------------------------------------------

        if topic == TOPICS["r1_status"]:

            process_status(
                1,
                payload
            )

            return

        if topic == TOPICS["r2_status"]:

            process_status(
                2,
                payload
            )

            return

        app.logger.warning(
            "MQTT topic tidak dikenal: %s",
            topic
        )

    except Exception as exc:

        app.logger.exception(
            "MQTT parse error: %s",
            exc
        )


# ============================================================
# MQTT CLIENT
# ============================================================

mqtt_client = None


def mqtt_loop():

    global mqtt_client

    while True:

        try:

            client_id = (
                "equlink-backend-"
                + secrets.token_hex(4)
            )

            mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id
            )

            if MQTT_USERNAME:

                mqtt_client.username_pw_set(
                    MQTT_USERNAME,
                    MQTT_PASSWORD
                )

            if MQTT_TLS:

                mqtt_client.tls_set()

            def on_connect(
                client,
                userdata,
                flags,
                reason_code,
                properties=None
            ):

                if reason_code == 0:

                    app.logger.info(
                        "MQTT CONNECTED"
                    )

                    # SENSOR
                    client.subscribe(
                        TOPICS["r1_sensor"],
                        qos=1
                    )

                    client.subscribe(
                        TOPICS["r2_sensor"],
                        qos=1
                    )

                    client.subscribe(
                        TOPICS["water_sensor"],
                        qos=1
                    )

                    # STATUS
                    client.subscribe(
                        TOPICS["r1_status"],
                        qos=1
                    )

                    client.subscribe(
                        TOPICS["r2_status"],
                        qos=1
                    )

                else:

                    app.logger.error(
                        "MQTT connect failed: %s",
                        reason_code
                    )

            def on_message(
                client,
                userdata,
                msg
            ):

                try:

                    payload = (
                        msg.payload
                        .decode("utf-8")
                    )

                    with app.app_context():

                        process_message(
                            msg.topic,
                            payload
                        )

                except Exception as exc:

                    app.logger.exception(
                        "MQTT message error: %s",
                        exc
                    )

            mqtt_client.on_connect = on_connect

            mqtt_client.on_message = on_message

            app.logger.info(
                "Connecting MQTT %s:%s",
                MQTT_HOST,
                MQTT_PORT
            )

            mqtt_client.connect(
                MQTT_HOST,
                MQTT_PORT,
                60
            )

            mqtt_client.loop_forever()

        except Exception as exc:

            app.logger.error(
                "MQTT connection error: %s",
                exc
            )

            time.sleep(5)


# ============================================================
# STARTUP
# ============================================================

with app.app_context():

    seed_database()


mqtt_thread = threading.Thread(
    target=mqtt_loop,
    daemon=True
)

mqtt_thread.start()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "5000"
            )
        ),
        debug=False
    )
