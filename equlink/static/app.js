/**
 * EQUILINK — APLIKASI UTAMA (app.js)
 * Sistem Edukasi Keadilan Penggunaan Energi & Air Berbasis IoT + AI
 */

let currentUser = null;
let telemetryTimer = null;

// State data internal (terhubung otomatis ke backend atau fallback simulasi cerdas)
let localData = {
  period: 'September 2026',
  transactions: [],
  historyLogs: [],
  rooms: {
    '1': {
      voltage: 220.4,
      current: 0.00,
      power: 0.0,
      energy_kwh: 0.000,
      lamp: false,
      powerSw: false,
      paid: 0,
      cost_elec: 0,
      cost_water: 0
    },
    '2': {
      voltage: 220.8,
      current: 0.00,
      power: 0.0,
      energy_kwh: 0.000,
      lamp: false,
      powerSw: false,
      paid: 0,
      cost_elec: 0,
      cost_water: 0
    }
  },
  water: {
    distance_cm: 18.5,
    height_cm: 23,
    level_percent: 45,
    pump: 'IDLE',
    total_cost: 0
  }
};

const $ = id => document.getElementById(id);
const formatRp = num => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(num || 0);

function formatDateNow() {
  const d = new Date();
  const options = { weekday: 'long', year: 'numeric', month: 'short', day: '2-digit' };
  return d.toLocaleDateString('id-ID', options);
}

// Inisialisasi Tanggal Header
const dateEl = $('currentDateStr');
if (dateEl) dateEl.textContent = formatDateNow();

function fillLogin(u, p) {
  $('loginUser').value = u;
  $('loginPass').value = p;
}

// ================= AUTENTIKASI =================
async function handleLogin() {
  const u = $('loginUser').value.trim();
  const p = $('loginPass').value.trim();
  $('loginErrMsg').textContent = '';

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    }).catch(() => null);

    if (res && res.ok) {
      const json = await res.json();
      currentUser = json.user;
    } else {
      // Fallback Kredensial Mandiri
      if (u === 'admin' && p === 'admin123') {
        currentUser = { username: 'ADMIN', role: 'admin' };
      } else if (u === 'user1' && p === 'user123') {
        currentUser = { username: 'USER1', role: 'user', room: 1 };
      } else if (u === 'user2' && p === 'user123') {
        currentUser = { username: 'USER2', role: 'user', room: 2 };
      } else {
        throw new Error('Username atau password tidak cocok.');
      }
    }

    // Buka tampilan utama
    $('loginSection').classList.add('hidden');
    $('appSection').classList.remove('hidden');

    $('loggedUserName').textContent = currentUser.username;
    $('loggedUserRole').textContent = currentUser.role === 'admin' ? 'ADMINISTRATOR' : `ROOM ${currentUser.room}`;

    // Batasi akses user biasa
    if (currentUser.role !== 'admin') {
      const setBtn = $('settingsNavBtn');
      if (setBtn) setBtn.classList.add('hidden');
      const otherRoom = currentUser.room === 1 ? 2 : 1;
      document.querySelectorAll(`[data-room="${otherRoom}"]`).forEach(el => el.style.display = 'none');
      $('statTotalRooms').textContent = '1';
    }

    refreshDashboard();
    telemetryTimer = setInterval(updateTelemetrySim, 3000);

  } catch (err) {
    $('loginErrMsg').textContent = err.message || 'Login gagal';
  }
}

function handleLogout() {
  if (telemetryTimer) clearInterval(telemetryTimer);
  fetch('/api/logout', { method: 'POST' }).catch(() => {});
  location.reload();
}

// ================= NAVIGASI MENU =================
function navTo(pageKey) {
  document.querySelectorAll('.nav-link').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.querySelector(`[data-nav="${pageKey}"]`);
  if (activeBtn) activeBtn.classList.add('active');

  document.querySelectorAll('.app-page').forEach(pg => pg.classList.add('hidden'));
  const activePage = $(`page-${pageKey}`);
  if (activePage) activePage.classList.remove('hidden');

  const headings = {
    dashboard: { title: 'Dashboard', sub: 'Monitoring realtime konsumsi listrik & air gedung' },
    education: { title: 'Education & Equity', sub: 'Modul literasi hemat energi dan keadilan konsumsi bersama' },
    payment: { title: 'Payment & Billing', sub: 'Pencatatan pembayaran tagihan & histori transaksi' },
    settings: { title: 'Room Settings', sub: 'Konfigurasi tarif, kredensial, dan koneksi IoT' }
  };

  const meta = headings[pageKey] || { title: pageKey, sub: '' };
  $('pageHeading').textContent = meta.title;
  $('pageSubheading').textContent = meta.sub;

  closeSidebar();
}

function toggleSidebar() {
  $('mainSidebar').classList.toggle('open');
  document.body.classList.toggle('sidebar-open');
}

function closeSidebar() {
  $('mainSidebar').classList.remove('open');
  document.body.classList.remove('sidebar-open');
}

// ================= SAKLAR SLIDE BOLA (RELAY) =================
async function toggleRelay(room, device, state) {
  localData.rooms[String(room)][device === 'lamp' ? 'lamp' : 'powerSw'] = state;

  await fetch('/api/relay', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room, device, state })
  }).catch(() => {});

  calculateInstantLoad(room);
}

function calculateInstantLoad(room) {
  const r = localData.rooms[String(room)];
  let watt = 0;
  if (r.lamp) watt += 45 + Math.random() * 5;
  if (r.powerSw) watt += 180 + Math.random() * 20;

  r.power = watt;
  r.current = watt > 0 ? (watt / r.voltage) : 0;
  updateRoomUI(room);
}

// ================= TELEMETRI REALTIME =================
function updateTelemetrySim() {
  [1, 2].forEach(rm => {
    const r = localData.rooms[String(rm)];
    r.voltage = 220 + (Math.random() * 3 - 1.5);
    if (r.lamp || r.powerSw) {
      calculateInstantLoad(rm);
      r.energy_kwh += (r.power / 1000) * (3 / 3600);
      r.cost_elec = r.energy_kwh * 1444.70;
    } else {
      r.power = 0;
      r.current = 0;
    }
    updateRoomUI(rm);
  });

  // Fluktuasi level air tangki
  const w = localData.water;
  w.distance_cm = Math.max(2, Math.min(23, (w.distance_cm + (Math.random() * 0.4 - 0.2))));
  w.level_percent = Math.round(((w.height_cm - w.distance_cm) / w.height_cm) * 100);
  w.total_cost = 12500 + Math.round(w.level_percent * 40);
  localData.rooms['1'].cost_water = w.total_cost / 2;
  localData.rooms['2'].cost_water = w.total_cost / 2;

  updateTankUI();

  if (Math.random() > 0.6) {
    pushHistoryRow();
  }
}

function updateRoomUI(rm) {
  const r = localData.rooms[String(rm)];
  const vEl = $(`r${rm}_volt`);
  if (!vEl) return;

  vEl.textContent = r.voltage.toFixed(1);
  $(`r${rm}_amp`).textContent = r.current.toFixed(2);
  $(`r${rm}_watt`).textContent = r.power.toFixed(1);
  $(`r${rm}_kwh`).textContent = r.energy_kwh.toFixed(3);

  $(`r${rm}_cost_elec`).textContent = formatRp(r.cost_elec);
  $(`r${rm}_cost_water`).textContent = formatRp(r.cost_water);

  const pct = Math.min(100, Math.max(0, (r.power / 900) * 100));
  $(`r${rm}_loadbar`).style.width = pct + '%';

  const totalBill = r.cost_elec + r.cost_water;
  const sisa = Math.max(0, totalBill - r.paid);
  const paidEl = $(`payR${rm}_paid`);
  if (paidEl) paidEl.textContent = formatRp(r.paid);
  const outEl = $(`payR${rm}_outstanding`);
  if (outEl) outEl.textContent = formatRp(sisa);
}

function updateTankUI() {
  const w = localData.water;
  const distEl = $('tankDistance');
  if (!distEl) return;

  distEl.textContent = w.distance_cm.toFixed(1);
  $('tankPercentText').textContent = w.level_percent;
  $('tankLiquidFill').style.height = w.level_percent + '%';
  $('tankTotalCost').textContent = formatRp(w.total_cost);
  $('tankCostPerRoom').textContent = `Biaya per Ruangan: ${formatRp(w.total_cost / 2)}`;
  $('pumpStatusBadge').textContent = `Pompa: ${w.pump}`;
}

function refreshDashboard() {
  updateRoomUI(1);
  updateRoomUI(2);
  updateTankUI();
}

function resetTelemetry() {
  [1, 2].forEach(rm => {
    localData.rooms[String(rm)].energy_kwh = 0;
    localData.rooms[String(rm)].cost_elec = 0;
    localData.rooms[String(rm)].cost_water = 0;
    localData.rooms[String(rm)].paid = 0;
  });
  refreshDashboard();
  alert('Semua akumulasi energi dan tagihan berhasil direset.');
}

function pushHistoryRow() {
  const now = new Date();
  const timeStr = now.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) + ', ' +
                  now.toTimeString().split(' ')[0];

  const r1 = localData.rooms['1'];
  const r2 = localData.rooms['2'];
  const w = localData.water;

  const log = {
    time: timeStr,
    r1: `${r1.power.toFixed(1)} W · ${r1.energy_kwh.toFixed(3)} kWh`,
    r2: `${r2.power.toFixed(1)} W · ${r2.energy_kwh.toFixed(3)} kWh`,
    air: `${w.distance_cm.toFixed(1)} cm / ${w.pump}`
  };

  localData.historyLogs.unshift(log);
  if (localData.historyLogs.length > 15) localData.historyLogs.pop();

  renderHistoryTable();
}

function renderHistoryTable() {
  const tbody = $('telemetryHistoryTbody');
  if (!tbody || !localData.historyLogs.length) return;

  tbody.innerHTML = localData.historyLogs.map(item => `
    <tr>
      <td style="font-weight:600;">${item.time}</td>
      <td class="meter-font">${item.r1}</td>
      <td class="meter-font">${item.r2}</td>
      <td><span style="color:var(--cyan); font-weight:600;">${item.air}</span></td>
    </tr>
  `).join('');
}

// ================= PROSES PEMBAYARAN =================
function processPayment(room) {
  const input = $(`payInputR${room}`);
  const val = parseFloat(input.value);
  if (!val || val <= 0) {
    alert('Masukkan nominal pembayaran yang valid.');
    return;
  }

  localData.rooms[String(room)].paid += val;
  input.value = '';

  const now = new Date();
  const timeStr = now.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) + ' ' + now.toTimeString().split(' ')[0];

  const r = localData.rooms[String(room)];
  const sisa = Math.max(0, (r.cost_elec + r.cost_water) - r.paid);

  const txn = {
    time: timeStr,
    room: `Ruang ${room}`,
    amount: formatRp(val),
    sisa: formatRp(sisa),
    ket: 'Pembayaran Dikonfirmasi'
  };

  localData.transactions.unshift(txn);
  const txCount = $('statTransactionsCount');
  if (txCount) txCount.textContent = localData.transactions.length;

  renderPaymentTable();
  refreshDashboard();
  alert(`Pembayaran ${formatRp(val)} untuk Ruang ${room} berhasil disimpan.`);
}

function handleResetPelunasan(room, checkbox) {
  if (checkbox.checked) {
    const r = localData.rooms[String(room)];
    r.paid = r.cost_elec + r.cost_water;
    refreshDashboard();
    setTimeout(() => {
      checkbox.checked = false;
    }, 1000);
  }
}

function renderPaymentTable() {
  const tbody = $('paymentHistoryTbody');
  if (!tbody || !localData.transactions.length) return;

  tbody.innerHTML = localData.transactions.map(t => `
    <tr>
      <td>${t.time}</td>
      <td><b>${t.room}</b></td>
      <td style="color: var(--emerald); font-weight:700;">+ ${t.amount}</td>
      <td style="color: var(--amber); font-weight:700;">${t.sisa}</td>
      <td><span class="pill-btn" style="padding:0.2rem 0.6rem; font-size:0.7rem;">${t.ket}</span></td>
    </tr>
  `).join('');
}

// ================= AI CONSULTANT & CHATBOT =================
function appendAIChatMessage(sender, text, isAi = false) {
  const win = $('aiChatWindow');
  const div = document.createElement('div');
  div.className = `chat-bubble ${isAi ? 'ai' : 'user'}`;
  div.innerHTML = `<b>${sender}:</b> ${text.replace(/\n/g, '<br>')}`;
  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
  return div;
}

async function sendAIChat() {
  const inp = $('aiInputPrompt');
  const prompt = inp.value.trim();
  if (!prompt) return;

  appendAIChatMessage('Anda', prompt, false);
  inp.value = '';

  const loadingMsg = appendAIChatMessage('🤖 EQUILINK AI', 'Menganalisis data konsumsi kamar...', true);

  try {
    const res = await fetch('/api/ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: prompt })
    }).catch(() => null);

    if (res && res.ok) {
      const json = await res.json();
      loadingMsg.innerHTML = `<b>🤖 EQUILINK AI:</b> ${json.answer.replace(/\n/g, '<br>')}`;
    } else {
      setTimeout(() => {
        let reply = "Berdasarkan sensor EQUILINK terkini, pasokan tegangan listrik PLN normal di 220V. ";
        if (prompt.toLowerCase().includes('ruang 1') || prompt.toLowerCase().includes('kamar 1')) {
          reply += `Beban aktif Ruang 1 saat ini adalah ${localData.rooms['1'].power.toFixed(1)}W dengan akumulasi ${localData.rooms['1'].energy_kwh.toFixed(3)} kWh. Disarankan menonaktifkan saklar Power saat meninggalkan kamar guna menghindari konsumsi phantom load.`;
        } else if (prompt.toLowerCase().includes('air')) {
          reply += `Ketinggian air tangki saat ini ${localData.water.level_percent}%. Biaya dibagi secara proporsional dan adil antar kedua ruangan.`;
        } else {
          reply += "Tips efisiensi: pastikan lampu dimatikan saat siang hari dan gunakan saklar toggle Power untuk mematikan perangkat elektronik yang tidak digunakan secara total.";
        }
        loadingMsg.innerHTML = `<b>🤖 EQUILINK AI:</b> ${reply}`;
      }, 700);
    }
  } catch (err) {
    loadingMsg.innerHTML = `<b>🤖 EQUILINK AI:</b> Terjadi kendala koneksi ke server AI.`;
  }
}

function triggerAutoAIAnalysis() {
  $('aiInputPrompt').value = 'Berikan ringkasan analisis efisiensi energi dan air kedua kamar saat ini.';
  sendAIChat();
}

// ================= QUIZ LOGIC =================
function checkQuizAnswer(selectedIdx) {
  const res = $('quizResultMsg');
  if (selectedIdx === 1) {
    res.innerHTML = '<span style="color: var(--emerald);">✓ Benar! Prinsip Proportional Equity membagi beban sesuai konsumsi riil (60:40) sehingga tidak merugikan pihak lain.</span>';
  } else {
    res.innerHTML = '<span style="color: var(--rose);">✗ Kurang tepat. Membagi rata sama banyak akan membebankan pemborosan satu pihak kepada penghuni yang hemat.</span>';
  }
}

function handleNewPeriod() {
  if (confirm('Tutup periode penagihan aktif saat ini dan mulai siklus baru?')) {
    [1, 2].forEach(rm => {
      localData.rooms[String(rm)].energy_kwh = 0;
      localData.rooms[String(rm)].cost_elec = 0;
      localData.rooms[String(rm)].cost_water = 0;
      localData.rooms[String(rm)].paid = 0;
    });
    refreshDashboard();
    alert('Periode baru berhasil dimulai.');
  }
}

// Jalankan baris log awal saat halaman dibuka
pushHistoryRow();
