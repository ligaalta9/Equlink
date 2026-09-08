/**
 * EQUILINK — APLIKASI UTAMA (app.js)
 * Sistem Edukasi Keadilan Penggunaan Energi & Air Berbasis IoT + AI
 *
 * CATATAN PERBAIKAN (dibanding versi sebelumnya):
 * 1) Toggle "Power" sekarang mengirim device 'outlet' (bukan 'power') ke /api/relay,
 *    sesuai validasi di app.py — sebelumnya selalu gagal 400.
 * 2) SEMUA angka (voltase, arus, daya, kWh, tagihan, level air, riwayat) sekarang
 *    diambil dari /api/state, /api/history, /api/payments milik server — bukan lagi
 *    di-random di browser (Math.random()). Tampilan & elemen HTML-nya sama persis,
 *    hanya sumber datanya yang sekarang nyata.
 * 3) Login tidak lagi diam-diam "berpura-pura sukses" kalau server tidak terjangkau —
 *    kalau gagal, pesan errornya ditampilkan apa adanya. Field password tidak lagi
 *    otomatis terisi kredensial admin.
 * 4) "Reset All" & "Close Period" sekarang benar-benar memanggil /api/period/new,
 *    bukan cuma mereset variabel di browser.
 * 5) "Slide Reset Pelunasan Total" sekarang memanggil /api/payment dengan nominal
 *    = sisa tagihan saat ini, jadi benar-benar melunasi di server (fitur/tampilan
 *    tetap sama seperti sebelumnya).
 * 6) Info "Koneksi MQTT" di Room Settings diluruskan supaya sesuai konfigurasi asli
 *    di app.py (topik & port), bukan lagi asal disalin dari proyek lain.
 */

let currentUser = null;
let pollTimer = null;
let logTimer = null;
let lastState = null; // cache state terakhir, dipakai auto-log riwayat pemakaian

const $ = id => document.getElementById(id);
const formatRp = num => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(num || 0);

function formatDateNow() {
  const d = new Date();
  return d.toLocaleDateString('id-ID', { weekday: 'long', year: 'numeric', month: 'short', day: '2-digit' });
}
const dateEl = $('currentDateStr');
if (dateEl) dateEl.textContent = formatDateNow();

function fillLogin(u, p) {
  $('loginUser').value = u;
  $('loginPass').value = p;
}

async function api(url, opt = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(opt.headers || {}) }, ...opt });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Request gagal');
  return d;
}

// ================= AUTENTIKASI =================
async function handleLogin() {
  const u = $('loginUser').value.trim();
  const p = $('loginPass').value.trim();
  $('loginErrMsg').textContent = '';

  try {
    const json = await api('/api/login', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    currentUser = json.user;

    $('loginSection').classList.add('hidden');
    $('appSection').classList.remove('hidden');

    $('loggedUserName').textContent = currentUser.username;
    $('loggedUserRole').textContent = currentUser.role === 'admin' ? 'ADMINISTRATOR' : `ROOM ${currentUser.room}`;

    if (currentUser.role !== 'admin') {
      const setBtn = $('settingsNavBtn');
      if (setBtn) setBtn.classList.add('hidden');
      const otherRoom = currentUser.room === 1 ? 2 : 1;
      document.querySelectorAll(`[data-room="${otherRoom}"]`).forEach(el => el.style.display = 'none');
      $('statTotalRooms').textContent = '1';
      $('roomCountPill').innerHTML = '<i class="fa-solid fa-layer-group"></i> 1 Room';
    } else {
      $('btnResetAll').classList.remove('hidden');
      $('periodSettingsCard').classList.remove('hidden');
    }

    await refreshAll();
    pollTimer = setInterval(refreshAll, 5000);
    logTimer = setInterval(logUsageSnapshot, 60000);

  } catch (err) {
    $('loginErrMsg').textContent = err.message || 'Login gagal. Pastikan server backend (app.py) sedang berjalan.';
  }
}

function handleLogout() {
  if (pollTimer) clearInterval(pollTimer);
  if (logTimer) clearInterval(logTimer);
  api('/api/logout', { method: 'POST' }).catch(() => {}).finally(() => location.reload());
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
// device HARUS 'lamp' atau 'outlet' — sesuai validasi di app.py.
async function toggleRelay(room, device, state) {
  try {
    await api('/api/relay', { method: 'POST', body: JSON.stringify({ room, device, state }) });
  } catch (e) {
    alert('Gagal mengirim perintah relay: ' + e.message);
    // kembalikan toggle ke posisi semula kalau request ditolak server
    const el = device === 'lamp' ? $(`r${room}_lamp_sw`) : $(`r${room}_power_sw`);
    if (el) el.checked = !state;
    return;
  }
  // Nilai daya/arus akan ter-update otomatis dari data sensor asli
  // pada polling /api/state berikutnya (maks. 5 detik), bukan dikira-kira di sini.
  setTimeout(refreshAll, 1200);
}

// ================= AMBIL DATA ASLI DARI SERVER =================
async function refreshAll() {
  try {
    const state = await api('/api/state');
    lastState = state;

    $('connStatus').innerHTML = '<i class="fa-solid fa-circle" style="font-size:0.55rem;"></i> Terhubung';
    $('connStatus').style.background = 'var(--emerald-soft)';
    $('connStatus').style.color = 'var(--emerald)';

    const statusEl = $('statSystemStatus');
    statusEl.textContent = 'Healthy';
    statusEl.style.color = 'var(--emerald)';

    [1, 2].forEach(rm => {
      const d = state.rooms[String(rm)];
      if (d) updateRoomUI(rm, d);
    });

    updateTankUI(state.water || {});

    let grid = 'Stable';
    [1, 2].forEach(rm => {
      const d = state.rooms[String(rm)];
      if (d && d.sensor && d.sensor.power > 900) grid = 'Overload';
    });
    const gridEl = $('statEnergyGrid');
    gridEl.textContent = grid;
    gridEl.style.color = grid === 'Overload' ? 'var(--rose)' : 'var(--brand-navy)';

    await loadPayments();
  } catch (e) {
    $('connStatus').innerHTML = '<i class="fa-solid fa-circle" style="font-size:0.55rem;"></i> Terputus';
    $('connStatus').style.background = 'var(--rose-soft)';
    $('connStatus').style.color = 'var(--rose)';
    const statusEl = $('statSystemStatus');
    statusEl.textContent = 'Terputus';
    statusEl.style.color = 'var(--rose)';
  }
}

function updateRoomUI(rm, d) {
  const s = d.sensor || {};
  const b = d.bill || {};

  const vEl = $(`r${rm}_volt`);
  if (!vEl) return;

  vEl.textContent = (s.voltage || 0).toFixed(1);
  $(`r${rm}_amp`).textContent = (s.current || 0).toFixed(2);
  $(`r${rm}_watt`).textContent = (s.power || 0).toFixed(1);
  $(`r${rm}_kwh`).textContent = (s.energy_kwh || 0).toFixed(3);

  $(`r${rm}_cost_elec`).textContent = formatRp(b.energy_cost || 0);
  $(`r${rm}_cost_water`).textContent = formatRp(b.water_cost || 0);

  const pct = Math.min(100, Math.max(0, ((s.power || 0) / 900) * 100));
  $(`r${rm}_loadbar`).style.width = pct + '%';

  const paid = b.paid_amount || 0;
  const sisa = Math.max(0, (b.total_cost || 0) - paid);
  const paidEl = $(`payR${rm}_paid`);
  if (paidEl) paidEl.textContent = formatRp(paid);
  const outEl = $(`payR${rm}_outstanding`);
  if (outEl) outEl.textContent = formatRp(sisa);

  const statusBadge = $(`r${rm}status`);
  if (statusBadge && b.status) {
    statusBadge.innerHTML = `<i class="fa-solid fa-circle" style="font-size:0.45rem;"></i> ${b.status === 'LUNAS' ? 'LUNAS' : 'LISTENING'}`;
  }
}

function updateTankUI(w) {
  const distEl = $('tankDistance');
  if (!distEl) return;

  const dist = w.distance_cm || 0;
  const pct = Math.min(100, Math.max(0, w.level_percent || 0));

  distEl.textContent = dist.toFixed(1);
  $('tankPercentText').textContent = pct.toFixed(0);
  $('tankLiquidFill').style.height = pct + '%';

  // app.py belum menghitung water_cost (selalu 0 di compute_bills), jadi kartu ini
  // jujur menampilkan Rp 0 sesuai data asli — bukan dikarang seperti versi sebelumnya.
  $('tankTotalCost').textContent = formatRp(0);
  $('tankCostPerRoom').textContent = 'Biaya per Ruangan: ' + formatRp(0);

  // app.py (WaterReading) belum menyimpan status ON/OFF pompa, jadi ditampilkan
  // apa adanya sebagai "tidak tersedia" alih-alih pura-pura tahu.
  $('pumpStatusBadge').textContent = 'Pompa: data tidak tersedia';
}

// ================= RIWAYAT PEMAKAIAN (auto-log tiap 1 menit, data ASLI) =================
function logUsageSnapshot() {
  const tbody = $('telemetryHistoryTbody');
  if (!tbody || !lastState) return;
  if (tbody.children[0] && tbody.children[0].children.length === 1) tbody.innerHTML = '';

  const now = new Date();
  const timeStr = now.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) + ', ' + now.toTimeString().split(' ')[0];

  const r1 = lastState.rooms['1']?.sensor;
  const r2 = lastState.rooms['2']?.sensor;
  const w = lastState.water || {};

  const row = document.createElement('tr');
  row.innerHTML = `
    <td style="font-weight:600;">${timeStr}</td>
    <td class="meter-font">${r1 ? `${r1.power.toFixed(1)} W · ${r1.energy_kwh.toFixed(3)} kWh` : '-'}</td>
    <td class="meter-font">${r2 ? `${r2.power.toFixed(1)} W · ${r2.energy_kwh.toFixed(3)} kWh` : '-'}</td>
    <td><span style="color:var(--cyan); font-weight:600;">${(w.distance_cm || 0).toFixed(1)} cm · ${(w.level_percent || 0).toFixed(0)}%</span></td>
  `;
  tbody.prepend(row);
  while (tbody.children.length > 30) tbody.removeChild(tbody.lastChild);
}

// ================= PROSES PEMBAYARAN =================
async function processPayment(room) {
  const input = $(`payInputR${room}`);
  const val = parseFloat(input.value);
  if (!val || val <= 0) {
    alert('Masukkan nominal pembayaran yang valid.');
    return;
  }
  try {
    await api('/api/payment', { method: 'POST', body: JSON.stringify({ room, amount: val }) });
    input.value = '';
    await refreshAll();
    alert(`Pembayaran ${formatRp(val)} untuk Ruang ${room} berhasil disimpan.`);
  } catch (e) {
    alert(e.message);
  }
}

// "Slide Reset Pelunasan Total" — melunasi lewat endpoint /api/payment yang sama
// (nominal = persis sisa tagihan saat ini), jadi benar-benar tercatat di server.
async function handleResetPelunasan(room, checkbox) {
  if (!checkbox.checked) return;
  const d = lastState && lastState.rooms[String(room)];
  const bill = d && d.bill;
  const sisa = bill ? Math.max(0, (bill.total_cost || 0) - (bill.paid_amount || 0)) : 0;

  if (sisa <= 0) {
    alert('Tagihan ruangan ini sudah lunas.');
    setTimeout(() => { checkbox.checked = false; }, 400);
    return;
  }
  try {
    await api('/api/payment', { method: 'POST', body: JSON.stringify({ room, amount: sisa, note: 'Pelunasan Total' }) });
    await refreshAll();
  } catch (e) {
    alert(e.message);
  }
  setTimeout(() => { checkbox.checked = false; }, 400);
}

async function loadPayments() {
  const rows = (await api('/api/payments')).rows;
  const tbody = $('paymentHistoryTbody');
  $('statTransactionsCount').textContent = rows.length;

  tbody.innerHTML = rows.length ? rows.map(t => {
    const d = lastState && lastState.rooms[String(t.room)];
    const bill = d && d.bill;
    const sisa = bill ? Math.max(0, (bill.total_cost || 0) - (bill.paid_amount || 0)) : 0;
    return `
      <tr>
        <td>${new Date(t.timestamp).toLocaleString('id-ID')}</td>
        <td><b>Ruang ${t.room}</b></td>
        <td style="color: var(--emerald); font-weight:700;">+ ${formatRp(t.amount)}</td>
        <td style="color: var(--amber); font-weight:700;">${formatRp(sisa)}</td>
        <td><span class="pill-btn" style="padding:0.2rem 0.6rem; font-size:0.7rem;">${t.note || 'Pembayaran'}</span></td>
      </tr>`;
  }).join('') : `<tr><td colspan="5" style="text-align:center; color:var(--text-light); padding:1.5rem; font-style:italic;">Belum ada riwayat transaksi pembayaran.</td></tr>`;
}

// ================= AI CONSULTANT & CHATBOT =================
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function appendAIChatMessage(sender, text, isAi = false) {
  const win = $('aiChatWindow');
  const div = document.createElement('div');
  div.className = `chat-bubble ${isAi ? 'ai' : 'user'}`;
  div.innerHTML = `<b>${sender}:</b> ${escapeHtml(text).replace(/\n/g, '<br>')}`;
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
    const json = await api('/api/ai', { method: 'POST', body: JSON.stringify({ query: prompt }) });
    loadingMsg.innerHTML = `<b>🤖 EQUILINK AI:</b> ${escapeHtml(json.answer).replace(/\n/g, '<br>')}`;
  } catch (err) {
    loadingMsg.innerHTML = `<b>🤖 EQUILINK AI:</b> ${escapeHtml(err.message)}`;
  }
}

function triggerAutoAIAnalysis() {
  $('aiInputPrompt').value = 'Berikan ringkasan analisis efisiensi energi dan air kedua kamar saat ini, beserta rekomendasi hemat energi.';
  sendAIChat();
}

// ================= QUIZ LOGIC (statis, tidak ada bug — dibiarkan sama) =================
function checkQuizAnswer(selectedIdx) {
  const res = $('quizResultMsg');
  if (selectedIdx === 1) {
    res.innerHTML = '<span style="color: var(--emerald);">✓ Benar! Prinsip Proportional Equity membagi beban sesuai konsumsi riil (60:40) sehingga tidak merugikan pihak lain.</span>';
  } else {
    res.innerHTML = '<span style="color: var(--rose);">✗ Kurang tepat. Membagi rata sama banyak akan membebankan pemborosan satu pihak kepada penghuni yang hemat.</span>';
  }
}

// ================= SETTINGS: TUTUP PERIODE (Admin, panggilan asli ke server) =================
async function handleNewPeriod() {
  if (!confirm('Tutup periode penagihan aktif saat ini dan mulai siklus baru? Ini akan mereset akumulasi kWh & tagihan KEDUA ruangan di server.')) return;
  try {
    await api('/api/period/new', { method: 'POST' });
    await refreshAll();
    alert('Periode baru berhasil dimulai.');
  } catch (e) {
    alert(e.message);
  }
}
