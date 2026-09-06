import os, json, threading, time, hashlib, secrets
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
WATER_TARIFF_PER_LITER = float(os.getenv('WATER_TARIFF_PER_LITER', '0'))
WATER_TARIFF_PER_SECOND = float(os.getenv('WATER_TARIFF_PER_SECOND', '37.5'))
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
MQTT_HOST = os.getenv('MQTT_HOST', 'broker.emqx.io')
MQTT_PORT = int(os.getenv('MQTT_PORT', '8883'))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_TLS = os.getenv('MQTT_TLS', 'true').lower() == 'true'

TOPICS = {
    'r1_sensor':'equilink/room1/sensor', 'r2_sensor':'equilink/room2/sensor',
    'water_sensor':'equilink/water/sensor', 'r1_relay':'equilink/room1/relay',
    'r2_relay':'equilink/room2/relay', 'water_pump':'equilink/water/pump'
}

class User(db.Model):
    id=db.Column(db.Integer, primary_key=True); username=db.Column(db.String(80), unique=True, nullable=False)
    password_hash=db.Column(db.String(128), nullable=False); role=db.Column(db.String(20), nullable=False); room=db.Column(db.Integer)
class Room(db.Model):
    id=db.Column(db.Integer, primary_key=True); name=db.Column(db.String(80), nullable=False); code=db.Column(db.String(20), unique=True, nullable=False)
class SensorReading(db.Model):
    id=db.Column(db.Integer, primary_key=True); room_id=db.Column(db.Integer, nullable=False, index=True); timestamp=db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    voltage=db.Column(db.Float, default=0); current=db.Column(db.Float, default=0); power=db.Column(db.Float, default=0); energy_kwh=db.Column(db.Float, default=0)
class WaterReading(db.Model):
    id=db.Column(db.Integer, primary_key=True); timestamp=db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True); distance_cm=db.Column(db.Float, default=0); level_percent=db.Column(db.Float, default=0); liters_used=db.Column(db.Float, default=0)
class BillingPeriod(db.Model):
    id=db.Column(db.Integer, primary_key=True); name=db.Column(db.String(80), nullable=False); started_at=db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)); ended_at=db.Column(db.DateTime); status=db.Column(db.String(20), default='active')
class Bill(db.Model):
    id=db.Column(db.Integer, primary_key=True); period_id=db.Column(db.Integer, nullable=False); room_id=db.Column(db.Integer, nullable=False); energy_kwh=db.Column(db.Float, default=0); energy_cost=db.Column(db.Float, default=0); water_cost=db.Column(db.Float, default=0); total_cost=db.Column(db.Float, default=0); paid_amount=db.Column(db.Float, default=0)
class Payment(db.Model):
    id=db.Column(db.Integer, primary_key=True); room_id=db.Column(db.Integer, nullable=False); period_id=db.Column(db.Integer, nullable=False); amount=db.Column(db.Float, nullable=False); timestamp=db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)); note=db.Column(db.String(255))
class AIAnalysis(db.Model):
    id=db.Column(db.Integer, primary_key=True); room_id=db.Column(db.Integer); period_id=db.Column(db.Integer); created_at=db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)); prompt_type=db.Column(db.String(50)); result_json=db.Column(db.Text)


def h(p): return hashlib.sha256(p.encode()).hexdigest()
def seed():
    db.create_all()
    if not Room.query.count(): db.session.add_all([Room(id=1,name='Kamar 1',code='ROOM1'),Room(id=2,name='Kamar 2',code='ROOM2')])
    for u,r,room in [('admin','admin123',None),('user1','user123',1),('user2','user123',2)]:
        if not User.query.filter_by(username=u).first(): db.session.add(User(username=u,password_hash=h(r),role='admin' if u=='admin' else 'user',room=room))
    if not BillingPeriod.query.filter_by(status='active').first(): db.session.add(BillingPeriod(name=datetime.now().strftime('%B %Y')))
    db.session.commit()

@app.route('/')
def index(): return render_template('index.html')
@app.get('/api/health')
def health(): return jsonify(ok=True, mqtt=bool(mqtt_client and mqtt_client.is_connected()))

@app.post('/api/login')
def login():
    d=request.get_json() or {}; u=User.query.filter_by(username=d.get('username','')).first()
    if not u or u.password_hash!=h(d.get('password','')): return jsonify(error='Username/password salah'),401
    session['uid']=u.id; return jsonify(user={'username':u.username,'role':u.role,'room':u.room})
@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

def current_user(): return db.session.get(User,session.get('uid')) if session.get('uid') else None
def auth(f):
    @wraps(f)
    def w(*a,**k):
        if not current_user(): return jsonify(error='Unauthorized'),401
        return f(*a,**k)
    return w

def room_allowed(u, room): return u.role=='admin' or u.room==room

def latest_room(room):
    x=SensorReading.query.filter_by(room_id=room).order_by(SensorReading.timestamp.desc()).first()
    if not x: return {'voltage':0,'current':0,'power':0,'energy_kwh':0,'timestamp':None}
    return {'voltage':x.voltage,'current':x.current,'power':x.power,'energy_kwh':x.energy_kwh,'timestamp':x.timestamp.isoformat()}

def active_period(): return BillingPeriod.query.filter_by(status='active').order_by(BillingPeriod.id.desc()).first()
def compute_bills():
    p=active_period(); out={}
    if not p: return out
    energies={1:0,2:0}
    for r in [1,2]:
        x=SensorReading.query.filter_by(room_id=r).filter(SensorReading.timestamp>=p.started_at).order_by(SensorReading.timestamp.desc()).first()
        energies[r]=x.energy_kwh if x else 0
    total=sum(energies.values())
    for r in [1,2]:
        energy=energies[r]; cost=energy*ELECTRICITY_TARIFF
        b=Bill.query.filter_by(period_id=p.id,room_id=r).first()
        if not b: b=Bill(period_id=p.id,room_id=r); db.session.add(b)
        b.energy_kwh=energy; b.energy_cost=cost; b.water_cost=0; b.total_cost=cost; out[r]=b
    db.session.commit(); return out

@app.get('/api/state')
@auth
def state():
    u=current_user(); compute_bills(); p=active_period(); bills=Bill.query.filter_by(period_id=p.id).all() if p else []
    allowed=[1,2] if u.role=='admin' else [u.room]
    rooms={}
    for r in allowed:
        b=next((x for x in bills if x.room_id==r),None)
        rooms[str(r)]={'sensor':latest_room(r),'bill':({'energy_kwh':b.energy_kwh,'energy_cost':b.energy_cost,'water_cost':b.water_cost,'total_cost':b.total_cost,'paid_amount':b.paid_amount,'status':'LUNAS' if b and b.paid_amount>=b.total_cost and b.total_cost>0 else 'BELUM BAYAR'} if b else {})}
    w=WaterReading.query.order_by(WaterReading.timestamp.desc()).first()
    return jsonify(user={'username':u.username,'role':u.role,'room':u.room},period={'id':p.id,'name':p.name,'started_at':p.started_at.isoformat()} if p else None,rooms=rooms,water={'distance_cm':w.distance_cm,'level_percent':w.level_percent,'timestamp':w.timestamp.isoformat()} if w else {'distance_cm':0,'level_percent':0})

@app.get('/api/history')
@auth
def history():
    u=current_user(); allowed=[1,2] if u.role=='admin' else [u.room]
    rows=SensorReading.query.filter(SensorReading.room_id.in_(allowed)).order_by(SensorReading.timestamp.desc()).limit(200).all()
    return jsonify(rows=[{'room':x.room_id,'timestamp':x.timestamp.isoformat(),'voltage':x.voltage,'current':x.current,'power':x.power,'energy_kwh':x.energy_kwh} for x in rows])

@app.get('/api/payments')
@auth
def payments():
    u=current_user(); allowed=[1,2] if u.role=='admin' else [u.room]
    rows=Payment.query.filter(Payment.room_id.in_(allowed)).order_by(Payment.timestamp.desc()).limit(100).all()
    return jsonify(rows=[{'room':x.room_id,'amount':x.amount,'timestamp':x.timestamp.isoformat(),'note':x.note or ''} for x in rows])

@app.post('/api/payment')
@auth
def payment():
    u=current_user(); d=request.get_json() or {}; room=int(d.get('room')); amount=float(d.get('amount',0))
    if not room_allowed(u,room): return jsonify(error='Akses ruangan ditolak'),403
    p=active_period(); compute_bills(); b=Bill.query.filter_by(period_id=p.id,room_id=room).first()
    if not b or amount<=0: return jsonify(error='Nominal pembayaran tidak valid'),400
    b.paid_amount += amount; db.session.add(Payment(room_id=room,period_id=p.id,amount=amount,note=d.get('note','Pembayaran digital'))); db.session.commit()
    return jsonify(ok=True)

@app.post('/api/period/new')
@auth
def new_period():
    u=current_user()
    if u.role!='admin': return jsonify(error='Admin only'),403
    old=active_period()
    if old: old.status='closed'; old.ended_at=datetime.now(timezone.utc)
    p=BillingPeriod(name=datetime.now().strftime('%B %Y')); db.session.add(p); db.session.commit()
    return jsonify(ok=True,period=p.name)

@app.get('/api/equity')
@auth
def equity():
    u=current_user(); compute_bills(); p=active_period(); allowed=[1,2] if u.role=='admin' else [u.room]
    bs=Bill.query.filter(Bill.period_id==p.id,Bill.room_id.in_(allowed)).all(); total=sum(x.energy_kwh for x in bs); total_cost=sum(x.total_cost for x in bs)
    return jsonify(total_energy=total,total_cost=total_cost,rows=[{'room':x.room_id,'energy_kwh':x.energy_kwh,'share':(x.energy_kwh/total*100 if total else 0),'cost':x.total_cost,'fairness':(abs((x.energy_kwh/total if total else 0)-(x.total_cost/total_cost if total_cost else 0))<0.001)} for x in bs])

@app.get('/api/education')
@auth
def education():
    return jsonify(lessons=[{'title':'Equality vs Equity','body':'Equality membagi beban sama rata; equity membagi beban secara proporsional berdasarkan penggunaan aktual.'},{'title':'Hemat Energi','body':'Matikan lampu dan perangkat yang tidak digunakan, serta pantau pola konsumsi dari dashboard.'},{'title':'Hemat Air','body':'Pantau level dan penggunaan air, lalu hindari pemakaian berlebihan.'}],quiz=[{'q':'Jika Room 1 memakai 20 kWh dan Room 2 80 kWh dari total 100 kWh, pembagian biaya yang paling proporsional adalah?','options':['50% : 50%','20% : 80%','30% : 70%','40% : 60%'],'answer':1}])

@app.post('/api/ai')
@auth
def ai():
    if not GEMINI_API_KEY: return jsonify(error='GEMINI_API_KEY belum diatur di server'),503
    u=current_user(); d=request.get_json() or {}; q=d.get('query','').strip()
    if not q: return jsonify(error='Pertanyaan kosong'),400
    allowed=[1,2] if u.role=='admin' else [u.room]; compute_bills(); p=active_period(); bs=Bill.query.filter(Bill.period_id==p.id,Bill.room_id.in_(allowed)).all()
    context=[]
    for b in bs: context.append({'room':b.room_id,'energy_kwh':b.energy_kwh,'energy_cost':b.energy_cost,'total_cost':b.total_cost,'paid':b.paid_amount})
    w=WaterReading.query.order_by(WaterReading.timestamp.desc()).first(); payload={'rooms':context,'water_level_percent':w.level_percent if w else 0,'period':p.name if p else None}
    system='Anda adalah EQUILINK AI. Fokus pada edukasi energi/air, equity, efisiensi, dan rekomendasi berbasis data. Jangan mempermalukan pengguna dan jangan membuat data yang tidak tersedia. Jelaskan sederhana dalam Bahasa Indonesia.'
    prompt=system+'\nDATA AKTUAL:\n'+json.dumps(payload)+'\nPERTANYAAN:\n'+q
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
    try:
        r=requests.post(url,headers={'x-goog-api-key':GEMINI_API_KEY,'Content-Type':'application/json'},json={'contents':[{'parts':[{'text':prompt}]}]},timeout=45); r.raise_for_status(); data=r.json(); text=data['candidates'][0]['content']['parts'][0]['text']
        db.session.add(AIAnalysis(room_id=None if u.role=='admin' else u.room,period_id=p.id if p else None,prompt_type='chat',result_json=json.dumps({'question':q,'answer':text}))); db.session.commit(); return jsonify(answer=text)
    except Exception as e: return jsonify(error=f'AI error: {e}'),502

@app.post('/api/relay')
@auth
def relay():
    u=current_user(); d=request.get_json() or {}; room=int(d.get('room')); device=d.get('device'); state=bool(d.get('state'))
    if not room_allowed(u,room): return jsonify(error='Akses ruangan ditolak'),403
    topic=TOPICS['r1_relay'] if room==1 else TOPICS['r2_relay']
    if device not in ['lamp','outlet']: return jsonify(error='Device tidak valid'),400
    if not mqtt_client or not mqtt_client.is_connected(): return jsonify(error='MQTT offline'),503
    mqtt_client.publish(topic,json.dumps({'device':device,'state':state,'timestamp':datetime.now(timezone.utc).isoformat()}),qos=1)
    return jsonify(ok=True)

@app.post('/api/pump')
@auth
def pump():
    u=current_user()
    if u.role!='admin': return jsonify(error='Admin only'),403
    state=bool((request.get_json() or {}).get('state'))
    if not mqtt_client or not mqtt_client.is_connected(): return jsonify(error='MQTT offline'),503
    mqtt_client.publish(TOPICS['water_pump'],json.dumps({'state':state}),qos=1); return jsonify(ok=True)

def process_message(topic,payload):
    try:
        d=json.loads(payload)
        if topic==TOPICS['r1_sensor'] or topic==TOPICS['r2_sensor']:
            room=1 if topic==TOPICS['r1_sensor'] else 2
            db.session.add(SensorReading(room_id=room,voltage=float(d.get('voltage',0)),current=float(d.get('current',0)),power=float(d.get('power',0)),energy_kwh=float(d.get('energy_kwh',d.get('energy',0)))))
        elif topic==TOPICS['water_sensor']:
            db.session.add(WaterReading(distance_cm=float(d.get('distance_cm',d.get('distance',0))),level_percent=float(d.get('level_percent',d.get('percent',0))),liters_used=float(d.get('liters_used',0))))
        db.session.commit()
    except Exception as e: app.logger.error('MQTT message error: %s',e)

def mqtt_loop():
    global mqtt_client
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='equlink-backend-'+secrets.token_hex(4))
    if MQTT_USERNAME: client.username_pw_set(MQTT_USERNAME,MQTT_PASSWORD)
    if MQTT_TLS: client.tls_set()
    def on_connect(c,userdata,flags,reason_code,properties=None):
        if reason_code==0:
            for t in [TOPICS['r1_sensor'],TOPICS['r2_sensor'],TOPICS['water_sensor']]: c.subscribe(t,qos=1)
    def on_message(c,userdata,msg):
        with app.app_context(): process_message(msg.topic,msg.payload.decode())
    client.on_connect=on_connect; client.on_message=on_message
    try: client.connect(MQTT_HOST,MQTT_PORT,60); client.loop_forever()
    except Exception as e: app.logger.error('MQTT connection failed: %s',e)

mqtt_client=None
with app.app_context(): seed()
threading.Thread(target=mqtt_loop,daemon=True).start()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=True)
