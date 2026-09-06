let me = null, state = null;
const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(n || 0);

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

async function api(url, opt = {}) {
    const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(opt.headers || {}) }, ...opt });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'Request gagal');
    return d;
}

// ============ AUTH ============
async function login() {
    try {
        const d = await api('/api/login', { method: 'POST', body: JSON.stringify({ username: $('username').value, password: $('password').value }) });
        me = d.user;
        $('login').classList.add('hidden');
        $('app').classList.remove('hidden');
        $('who').innerHTML = `<i class="fa-solid fa-user" style="margin-right:.3rem;"></i>${escapeHtml(me.username)} · ${escapeHtml(me.role)}${me.room ? ' · Room ' + me.room : ''}`;
        if (me.role !== 'admin') $('settingsNav').classList.add('hidden');
        applyAccess();
        await refreshAll();
        setInterval(refreshAll, 5000);
    } catch (e) {
        $('loginErr').textContent = e.message;
    }
}

async function logout() {
    await api('/api/logout', { method: 'POST' });
    location.reload();
}

// Ruangan yang tidak diizinkan untuk role user dihapus dari DOM (kartu dashboard & form payment)
// — server (app.py) tetap jadi lapisan pertahanan utama lewat room_allowed().
function applyAccess() {
    if (me.role === 'admin') return;
    const otherRoom = me.room === 1 ? 2 : 1;
    document.querySelectorAll(`[data-room="${otherRoom}"]`).forEach(el => el.remove());
}

// ============ NAVIGASI ============
function nav(page) {
    document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
    $(page)?.classList.add('active');
    document.querySelectorAll('aside nav button').forEach(x => x.classList.remove('active'));
    document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
    const titles = { dashboard: 'Dashboard', payment: 'Payment', education: 'Education', settings: 'Settings' };
    $('title').textContent = titles[page] || page;
    closeSidebar(); // di mobile, pilih menu langsung menutup sidebar
}

// ============ SIDEBAR MOBILE (hamburger) ============
function toggleSidebar() {
    const isOpen = $('sidebar').classList.contains('open');
    if (isOpen) closeSidebar(); else openSidebar();
}
function openSidebar() {
    $('sidebar').classList.add('open');
    document.body.classList.add('sidebar-open');
}
function closeSidebar() {
    $('sidebar').classList.remove('open');
    document.body.classList.remove('sidebar-open');
}

// ============ DASHBOARD (Room Monitoring + Water + Equity + History + AI, semua di satu halaman) ============
async function refreshAll() {
    try {
        state = await api('/api/state');
        $('status').textContent = '● Online';
        $('status').style.background = 'var(--emerald-soft)';
        $('status').style.color = 'var(--emerald)';
        $('period').textContent = state.period?.name || '-';
        const periodNameEl = $('periodName');
        if (periodNameEl) periodNameEl.textContent = state.period?.name || '-';

        $('r1kwh').textContent = (state.rooms['1']?.sensor.energy_kwh ?? 0).toFixed(2);
        $('r2kwh').textContent = (state.rooms['2']?.sensor.energy_kwh ?? 0).toFixed(2);

        const pct = Math.min(100, Math.max(0, state.water?.level_percent || 0));
        $('water').textContent = pct.toFixed(0);
        const tank = $('waterTank'); if (tank) tank.style.height = pct.toFixed(0) + '%';
        const waterPctEl = $('waterPct'); if (waterPctEl) waterPctEl.textContent = pct.toFixed(0);

        renderRoom(1);
        renderRoom(2);
        await history();
        await payments();
        await equity();
        await education();
    } catch (e) {
        $('status').textContent = '● Offline';
        $('status').style.background = 'var(--red-soft)';
        $('status').style.color = 'var(--red)';
    }
}

function renderRoom(r) {
    const d = state.rooms[String(r)];
    if (!d) return; // ruangan ini tidak diizinkan untuk user saat ini (elemen sudah dihapus applyAccess)

    $(`r${r}volt`).textContent = d.sensor.voltage.toFixed(1);
    $(`r${r}amp`).textContent = d.sensor.current.toFixed(2);
    $(`r${r}watt`).textContent = d.sensor.power.toFixed(1);
    $(`r${r}cost`).textContent = money(d.bill.total_cost);

    const statusEl = $(`r${r}status`);
    if (statusEl && d.bill.status) {
        statusEl.textContent = d.bill.status;
        statusEl.className = 'pill ' + (d.bill.status === 'LUNAS' ? 'pill-lunas' : 'pill-belum');
    }
}

// ============ HISTORY (bagian dari Dashboard) ============
async function history() {
    const d = await api('/api/history');
    $('historyBody').innerHTML = d.rows.length ? d.rows.map(x => `
        <tr>
            <td>Room ${x.room}</td>
            <td>${new Date(x.timestamp).toLocaleString('id-ID')}</td>
            <td class="meter-font">${x.voltage.toFixed(1)}</td>
            <td class="meter-font">${x.current.toFixed(2)}</td>
            <td class="meter-font">${x.power.toFixed(1)}</td>
            <td class="meter-font">${x.energy_kwh.toFixed(3)}</td>
        </tr>`).join('')
        : `<tr><td colspan="6" style="text-align:center; color:var(--muted); font-style:italic;">Belum ada data sensor.</td></tr>`;
}

// ============ PAYMENT ============
async function payments() {
    const d = await api('/api/payments');
    $('paymentBody').innerHTML = d.rows.length ? d.rows.map(x => `
        <tr>
            <td>Room ${x.room}</td>
            <td style="color:var(--emerald); font-weight:700;">${money(x.amount)}</td>
            <td>${new Date(x.timestamp).toLocaleString('id-ID')}</td>
            <td style="color:var(--muted);">${escapeHtml(x.note)}</td>
        </tr>`).join('')
        : `<tr><td colspan="4" style="text-align:center; color:var(--muted); font-style:italic;">Belum ada riwayat pembayaran.</td></tr>`;
}

async function pay(room) {
    try {
        const amount = Number($(`amount${room}`).value);
        await api('/api/payment', { method: 'POST', body: JSON.stringify({ room, amount }) });
        $(`amount${room}`).value = '';
        await refreshAll();
        alert('Pembayaran tersimpan');
    } catch (e) {
        alert(e.message);
    }
}

// ============ RELAY ============
async function relay(room, device, on) {
    try {
        await api('/api/relay', { method: 'POST', body: JSON.stringify({ room, device, state: on }) });
    } catch (e) {
        alert(e.message);
    }
}

// ============ EQUITY (bagian dari Dashboard) ============
async function equity() {
    const d = await api('/api/equity');
    $('equityBox').innerHTML = `
        <div class="mini-row" style="margin-bottom:1rem;">
            <div class="mini-stat"><p class="mlabel">TOTAL ENERGI</p><p class="mvalue">${d.total_energy.toFixed(2)} kWh</p></div>
            <div class="mini-stat"><p class="mlabel">TOTAL BIAYA</p><p class="mvalue">${money(d.total_cost)}</p></div>
        </div>
        ${d.rows.map(x => `
            <div class="equity-row">
                <div><b style="color:var(--navy-900);">Room ${x.room}</b><br>
                    <span style="color:var(--muted); font-size:.8rem;">${x.energy_kwh.toFixed(2)} kWh · ${x.share.toFixed(1)}% dari total</span>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:700;">${money(x.cost)}</div>
                    <div class="${x.fairness ? 'good' : 'bad'}" style="font-size:.72rem;">${x.fairness ? '✓ Fair Distribution' : '⚠ Check Distribution'}</div>
                </div>
            </div>`).join('')}
    `;
}

// ============ SETTINGS ============
async function newPeriod() {
    try {
        await api('/api/period/new', { method: 'POST' });
        await refreshAll();
        alert('Periode baru dibuat');
    } catch (e) {
        alert(e.message);
    }
}

// ============ EDUCATION ============
async function education() {
    const d = await api('/api/education');
    $('lessons').innerHTML = d.lessons.map(x => `<div class="lesson"><b>${escapeHtml(x.title)}</b><p>${escapeHtml(x.body)}</p></div>`).join('');
    const q = d.quiz[0];
    $('quiz').innerHTML = `
        <p style="font-weight:700; font-size:.85rem;">${escapeHtml(q.q)}</p>
        <div class="quizopt">${q.options.map((o, i) => `<button onclick="answer(${i},${q.answer})">${String.fromCharCode(65 + i)}. ${escapeHtml(o)}</button>`).join('')}</div>
        <div id="quizResult" style="margin-top:.6rem;"></div>`;
}

function answer(i, a) {
    $('quizResult').innerHTML = i === a
        ? '<p class="good">✓ Benar. Itulah proportional equity.</p>'
        : '<p class="bad">Belum tepat. Coba pahami perbandingan konsumsi aktual.</p>';
}

// ============ AI CONSULTANT & CHATBOT (bagian dari Dashboard) ============
function appendChat(role, html) {
    const box = $('chat');
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    div.innerHTML = html;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
}

async function askAI() {
    const q = $('question').value.trim();
    if (!q) return;
    appendChat('user', `<b>Anda:</b> ${escapeHtml(q)}`);
    $('question').value = '';
    try {
        const d = await api('/api/ai', { method: 'POST', body: JSON.stringify({ query: q }) });
        appendChat('ai', `<b>EQUILINK AI:</b> ${escapeHtml(d.answer).replace(/\n/g, '<br>')}`);
    } catch (e) {
        appendChat('bad', escapeHtml(e.message));
    }
}

// Tombol "Analisis Otomatis" — mengirim pertanyaan baku ke AI supaya user tidak perlu mengetik apa pun.
async function analyzeAuto() {
    const btn = $('btnAnalyze');
    btn.disabled = true;
    const loading = appendChat('ai', '<b>EQUILINK AI:</b> ⏳ Menganalisis efisiensi energi & air Anda...');
    try {
        const d = await api('/api/ai', {
            method: 'POST',
            body: JSON.stringify({ query: 'Berikan analisis singkat (2 paragraf) mengenai efisiensi penggunaan listrik dan air saya saat ini, beserta rekomendasi hemat energi dan estimasi tagihan bulanan.' })
        });
        loading.innerHTML = `<b>Analisis Otomatis AI:</b> ${escapeHtml(d.answer).replace(/\n/g, '<br>')}`;
    } catch (e) {
        loading.className = 'msg bad';
        loading.innerHTML = escapeHtml(e.message);
    }
    btn.disabled = false;
}
