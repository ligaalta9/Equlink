import os, json, threading, secrets, hashlib
from datetime import datetime, timezone
from functools import wraps

import requests
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, session, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'change-this-secret-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///equlink.db').replace('postgres://','postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ELECTRICITY_TARIFF = float(os.getenv('ELECTRICITY_TARIFF', '1444.70'))
WATER_TARIFF_PER_SECOND = float(os.getenv('WATER_TARIFF_PER_SECOND', '37.5'))
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
MQTT_HOST = os.getenv('MQTT_HOST', 'broker.emqx.io')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_TLS = os.getenv('MQTT_TLS', 'false').lower() == 'true'

# Topik diselaraskan penuh dengan firmware ESP32
TOPICS = {
    'r1_sensor': 'equilink/r1/elec',
    'r2_sensor': 'equilink/r2/elec',
    'water_sensor': 'equilink/water',
    'r1_lamp': 'equilink/r1/lamp',
    'r1_power': 'equilink/r1/power',
    'r2_lamp': 'equilink/r2/lamp',
    'r2_power': 'equilink/r2/power'
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    room = db.Column(db.Integer)

class SensorReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    voltage = db.Column(db.Float, default=0)
    current = db.Column(db.Float, default=0)
    power = db.Column(db.Float, default=0)
    energy_kwh = db.Column(db.Float, default=0)

class WaterReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    distance_cm = db.Column(db.Float, default=0)
    level_percent = db.Column(db.Float, default=0)

class BillingPeriod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active')

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, nullable=False)
    room_id = db.Column(db.Integer, nullable=False)
    energy_kwh = db.Column(db.Float, default=0)
    energy_cost = db.Column(db.Float, default=0)
    water_cost = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    paid_amount = db.Column(db.Float, default=0)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, nullable=False)
    period_id = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    note = db.Column(db.String(255))

def h(p): return hashlib.sha256(p.encode()).hexdigest()
def seed():
    db.create_all()
    for u, r, room in [('admin', 'admin123', None), ('user1', 'user123', 1), ('user2', 'user123', 2)]:
        if not User.query.filter_by(username=u).first():
            db.session.add(User(username=u, password_hash=h(r), role='admin' if u == 'admin' else 'user', room=room))
    if not BillingPeriod.query.filter_by(status='active').first():
        db.session.add(BillingPeriod(name=datetime.now().strftime('%B %Y')))
    db.session.commit()

@app.route('/')
def index(): return render_template('index.html')

@app.post('/api/login')
def login():
    d = request.get_json() or {}
    u = User.query.filter_by(username=d.get('username', '')).first()
    if not u or u.password_hash != h(d.get('password', '')):
        return jsonify(error='Username/password salah'), 401
    session['uid'] = u.id
    return jsonify(user={'username': u.username, 'role': u.role, 'room': u.room})

@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

def current_user(): return db.session.get(User, session.get('uid')) if session.get('uid') else None
def auth(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user(): return jsonify(error='Unauthorized'), 401
        return f(*a, **k)
    return w

def room_allowed(u, room): return u.role == 'admin' or u.room == room
def active_period(): return BillingPeriod.query.filter_by(status='active').order_by(BillingPeriod.id.desc()).first()

def compute_bills():
    p = active_period()
    out = {}
    if not p: return out
    energies = {1: 0, 2: 0}
    for r in [1, 2]:
        x = SensorReading.query.filter_by(room_id=r).filter(SensorReading.timestamp >= p.started_at).order_by(SensorReading.timestamp.desc()).first()
        energies[r] = x.energy_kwh if x else 0
    for r in [1, 2]:
        energy = energies[r]
        cost = energy * ELECTRICITY_TARIFF
        b = Bill.query.filter_by(period_id=p.id, room_id=r).first()
        if not b:
            b = Bill(period_id=p.id, room_id=r)
            db.session.add(b)
        b.energy_kwh = energy
        b.energy_cost = cost
        b.water_cost = cost * 0.1  # Alokasi proporsional air
        b.total_cost = b.energy_cost + b.water_cost
        out[r] = b
    db.session.commit()
    return out

@app.get('/api/state')
@auth
def state():
    u = current_user()
    compute_bills()
    p = active_period()
    bills = Bill.query.filter_by(period_id=p.id).all() if p else []
    allowed = [1, 2] if u.role == 'admin' else [u.room]
    rooms = {}
    for r in allowed:
        b = next((x for x in bills if x.room_id == r), None)
        x = SensorReading.query.filter_by(room_id=r).order_by(SensorReading.timestamp.desc()).first()
        rooms[str(r)] = {
            'sensor': {'voltage': x.voltage if x else 220, 'current': x.current if x else 0, 'power': x.power if x else 0, 'energy_kwh': x.energy_kwh if x else 0},
            'bill': {'energy_cost': b.energy_cost if b else 0, 'water_cost': b.water_cost if b else 0, 'total_cost': b.total_cost if b else 0, 'paid_amount': b.paid_amount if b else 0}
        }
    w = WaterReading.query.order_by(WaterReading.timestamp.desc()).first()
    return jsonify(rooms=rooms, water={'distance_cm': w.distance_cm if w else 15, 'level_percent': w.level_percent if w else 50})

@app.get('/api/history')
@auth
def history():
    u = current_user()
    allowed = [1, 2] if u.role == 'admin' else [u.room]
    rows = SensorReading.query.filter(SensorReading.room_id.in_(allowed)).order_by(SensorReading.timestamp.desc()).limit(50).all()
    return jsonify(rows=[{'room': x.room_id, 'timestamp': x.timestamp.isoformat(), 'voltage': x.voltage, 'current': x.current, 'power': x.power, 'energy_kwh': x.energy_kwh} for x in rows])

@app.get('/api/payments')
@auth
def payments():
    u = current_user()
    allowed = [1, 2] if u.role == 'admin' else [u.room]
    rows = Payment.query.filter(Payment.room_id.in_(allowed)).order_by(Payment.timestamp.desc()).limit(50).all()
    return jsonify(rows=[{'room': x.room_id, 'amount': x.amount, 'timestamp': x.timestamp.isoformat(), 'note': x.note or ''} for x in rows])

@app.post('/api/payment')
@auth
def payment():
    u = current_user()
    d = request.get_json() or {}
    room = int(d.get('room'))
    amount = float(d.get('amount', 0))
    if not room_allowed(u, room): return jsonify(error='Akses ditolak'), 403
    p = active_period()
    b = Bill.query.filter_by(period_id=p.id, room_id=room).first()
    if not b or amount <= 0: return jsonify(error='Tidak valid'), 400
    b.paid_amount += amount
    db.session.add(Payment(room_id=room, period_id=p.id, amount=amount, note=d.get('note', 'Bayar')))
    db.session.commit()
    return jsonify(ok=True)

@app.post('/api/relay')
@auth
def relay():
    u = current_user()
    d = request.get_json() or {}
    room = int(d.get('room'))
    device = d.get('device')  # 'lamp' atau 'outlet'
    state = bool(d.get('state'))
    if not room_allowed(u, room): return jsonify(error='Akses ditolak'), 403
    
    topic = f"equilink/r{room}/{device}"
    payload = "on" if state else "off"
    
    if not mqtt_client or not mqtt_client.is_connected(): return jsonify(error='MQTT offline'), 503
    mqtt_client.publish(topic, payload, qos=1)
    return jsonify(ok=True)

@app.post('/api/ai')
@auth
def ai():
    if not GEMINI_API_KEY: return jsonify(error='GEMINI_API_KEY belum diatur'), 503
    q = (request.get_json() or {}).get('query', '')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
    try:
        r = requests.post(url, headers={'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'}, json={'contents': [{'parts': [{'text': q}]}]}, timeout=20)
        r.raise_for_status()
        text = r.json()['candidates'][0]['content']['parts'][0]['text']
        return jsonify(answer=text)
    except Exception as e:
        return jsonify(error=f'AI error: {e}'), 502

@app.post('/api/period/new')
@auth
def new_period():
    u = current_user()
    if u.role != 'admin': return jsonify(error='Admin only'), 403
    old = active_period()
    if old:
        old.status = 'closed'
        old.ended_at = datetime.now(timezone.utc)
    db.session.add(BillingPeriod(name=datetime.now().strftime('%B %Y')))
    db.session.commit()
    return jsonify(ok=True)

@app.get('/api/education')
@auth
def education():
    return jsonify(
        lessons=[
            {'title': 'Equality vs Equity', 'body': 'Equality membagi rata; equity membagi secara proporsional sesuai penggunaan aktual.'},
            {'title': 'Hemat Listrik', 'body': 'Matikan perangkat siaga (phantom load) untuk menghemat pengeluaran.'}
        ],
        quiz=[{'q': 'Jika Kamar 1 memakai 60 kWh dan Kamar 2 memakai 40 kWh, proporsi biaya yang adil untuk Kamar 1 adalah?', 'options': ['50%', '60%', '75%'], 'answer': 1}]
    )

def process_message(topic, payload_str):
    try:
        d = json.loads(payload_str)
        if topic == TOPICS['r1_sensor']:
            v = float(d.get('Volts', d.get('voltage', 220)))
            c = float(d.get('Current', d.get('current', 0)))
            db.session.add(SensorReading(room_id=1, voltage=v, current=c, power=v*c, energy_kwh=(v*c)/1000.0))
        elif topic == TOPICS['r2_sensor']:
            v = float(d.get('Volts', d.get('voltage', 220)))
            c = float(d.get('Current', d.get('current', 0)))
            db.session.add(SensorReading(room_id=2, voltage=v, current=c, power=v*c, energy_kwh=(v*c)/1000.0))
        db.session.commit()
    except Exception as e:
        app.logger.error('MQTT parse error: %s', e)

def mqtt_loop():
    global mqtt_client
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='equlink-backend-' + secrets.token_hex(4))
    if MQTT_USERNAME: mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_TLS: mqtt_client.tls_set()
    def on_connect(c, userdata, flags, rc, props=None):
        if rc == 0:
            c.subscribe(TOPICS['r1_sensor'], qos=1)
            c.subscribe(TOPICS['r2_sensor'], qos=1)
    def on_message(c, userdata, msg):
        with app.app_context():
            process_message(msg.topic, msg.payload.decode())
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        app.logger.error('MQTT connection error: %s', e)

mqtt_client = None
with app.app_context(): seed()
threading.Thread(target=mqtt_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=True)
