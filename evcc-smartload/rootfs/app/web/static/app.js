/**
 * EVCC-Smartload Dashboard v4.0.0
 *
 * Fetches /status, /slots, /vehicles via JSON APIs and renders the dashboard.
 * Auto-refreshes every 60 seconds.
 */

// ---- State ----
let currentVehicleId = '';

// ---- Helpers ----
function $(id) { return document.getElementById(id); }

function socColor(soc) {
    if (soc >= 80) return '#00ff88';
    if (soc >= 50) return '#ffaa00';
    return '#ff4444';
}

function priceColor(ct) {
    if (ct < 25) return '#00ff88';
    if (ct < 35) return '#ffaa00';
    return '#ff4444';
}

function ageText(isoStr) {
    if (!isoStr) return '';
    try {
        const ms = Date.now() - new Date(isoStr).getTime();
        const min = Math.floor(ms / 60000);
        if (min < 2) return '<span style="color:#00ff88">🕐 vor ' + min + 'min</span>';
        if (min < 60) return '<span style="color:#ffaa00">🕐 vor ' + min + 'min</span>';
        return '<span style="color:#ff4444">🕐 vor ' + Math.floor(min/60) + 'h</span>';
    } catch(e) { return ''; }
}

// ---- Data fetching ----
async function fetchJSON(url) {
    try {
        const r = await fetch(url);
        return r.ok ? await r.json() : null;
    } catch (e) {
        console.error('Fetch error:', url, e);
        return null;
    }
}

// ---- Rendering ----
async function refresh() {
    const [status, slots, vehicles] = await Promise.all([
        fetchJSON('/status'),
        fetchJSON('/slots'),
        fetchJSON('/vehicles'),
    ]);
    if (status) renderStatus(status);
    if (slots) renderSlots(slots, vehicles);
    if (status) renderRL(status);
    if (status) renderConfig(status);
}

function renderStatus(s) {
    const c = s.current || {};
    $('priceVal').textContent = c.price_ct != null ? c.price_ct.toFixed(1) + ' ct' : '--';
    $('priceVal').style.color = priceColor(c.price_ct);
    $('batteryVal').textContent = c.battery_soc != null ? c.battery_soc.toFixed(0) + '%' : '--';
    $('batteryVal').style.color = socColor(c.battery_soc || 0);
    $('pvVal').textContent = c.pv_w != null ? (c.pv_w / 1000).toFixed(1) + ' kW' : '--';
    $('homeVal').textContent = c.home_w != null ? (c.home_w / 1000).toFixed(1) + ' kW' : '--';
}

function renderSlots(slots, vehicles) {
    const container = $('devicesContainer');
    if (!container) return;
    let html = '';

    // Battery
    const bat = slots.battery;
    if (bat) html += renderDevice(bat, 'battery', null);

    // Vehicles
    const vMap = vehicles ? (vehicles.vehicles || {}) : {};
    for (const [name, dev] of Object.entries(slots.vehicles || {})) {
        const vInfo = vMap[name] || {};
        html += renderDevice(dev, name, vInfo);
    }

    container.innerHTML = html;
}

function renderDevice(dev, deviceId, vehicleInfo) {
    const soc = dev.current_soc || 0;
    const target = dev.target_soc || 80;
    const cap = dev.capacity_kwh || 0;
    const need = dev.need_kwh || 0;
    const statusText = dev.status || '';
    const slots = dev.slots || [];
    const lastUpdate = dev.last_update || '';
    const icon = dev.icon || '🔋';
    const name = dev.name || deviceId;
    const age = ageText(lastUpdate);

    const isStale = lastUpdate && (Date.now() - new Date(lastUpdate).getTime()) > 3600000 && soc > 0;
    const showManualBtn = (soc === 0 && slots.length === 0) || deviceId.toLowerCase().includes('ora');

    let h = '<div class="device-card">';

    // Header
    h += '<div class="device-header"><div>';
    h += '<span class="device-name">' + icon + ' ' + name + '</span>';
    h += ' <span style="color:#888;margin-left:10px;">' + cap.toFixed(0) + ' kWh</span>';
    if (age) h += ' <span style="margin-left:10px;font-size:0.85em;">' + age + '</span>';
    h += '</div><div class="device-status">' + statusText + '</div></div>';

    // Stale warning
    if (isStale) {
        const min = Math.floor((Date.now() - new Date(lastUpdate).getTime()) / 60000);
        h += '<div class="stale-warning"><strong style="color:#ffaa00;">⚠️ Daten möglicherweise veraltet</strong><br>';
        h += '<span style="font-size:0.85em;color:#888;">Letztes Update vor ' + Math.floor(min/60) + 'h ' + (min%60) + 'min.</span></div>';
    }

    // SoC bar
    const sColor = socColor(soc);
    h += '<div style="display:flex;align-items:center;gap:10px;">';
    h += '<span style="color:' + sColor + ';font-size:1.5em;font-weight:bold;">' + soc + '%</span>';
    h += '<div style="flex:1;"><div class="soc-bar"><div class="soc-fill" style="width:' + soc + '%;background:' + sColor + ';"></div></div></div>';
    h += '<span style="color:#888;">→ ' + target + '%</span></div>';

    // Manual SoC button
    if (showManualBtn) {
        h += '<div style="margin-top:10px;">';
        h += '<button class="btn-manual" onclick="openModal(\'' + deviceId + '\',\'' + name + '\',' + cap + ')">✏️ SoC manuell eingeben</button>';
        h += ' <span style="margin-left:10px;font-size:0.85em;color:#888;">(keine API verfügbar)</span></div>';
    }

    // Slots
    if (need > 0 && slots.length > 0) {
        h += '<div style="margin-top:10px;color:#888;font-size:0.9em;">Bedarf: <strong>' + need.toFixed(1) + ' kWh</strong> in <strong>' + (dev.hours_needed || 0) + ' Stunden</strong></div>';
        h += '<div class="slots-container">';
        for (const s of slots) {
            const pc = s.price_ct || 0;
            const active = s.is_now ? ' active' : '';
            h += '<div class="slot' + active + '"><div class="time">' + s.hour + '</div>';
            h += '<div class="price" style="color:' + priceColor(pc) + ';">' + pc.toFixed(1) + 'ct</div>';
            h += '<div class="cost">' + (s.energy_kwh || 0).toFixed(1) + 'kWh</div>';
            h += '<div class="cost">€' + (s.cost_eur || 0).toFixed(2) + '</div></div>';
        }
        h += '</div>';
        h += '<div class="summary">';
        h += '<div class="summary-item"><div class="summary-value">' + slots.length + 'h</div><div class="summary-label">Ladedauer</div></div>';
        h += '<div class="summary-item"><div class="summary-value">' + (dev.avg_price_ct || 0).toFixed(1) + 'ct</div><div class="summary-label">⌀ Preis</div></div>';
        h += '<div class="summary-item"><div class="summary-value">€' + (dev.total_cost_eur || 0).toFixed(2) + '</div><div class="summary-label">Gesamtkosten</div></div>';
        h += '</div>';
    } else if (need <= 0) {
        h += '<p style="color:#00ff88;margin-top:10px;">✅ Kein Ladebedarf</p>';
    } else {
        h += '<p style="color:#ffaa00;margin-top:10px;">⚠️ ' + need.toFixed(1) + ' kWh Bedarf, aber keine passenden Slots</p>';
    }

    h += '</div>';
    return h;
}

function renderRL(s) {
    const rl = s.rl || {};
    const m = s.rl_maturity || {};
    let h = '';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">';
    h += '<span style="font-size:1.1em;">' + (m.status || '?') + '</span>';
    h += '<span style="color:#888;">' + (m.message || '') + '</span></div>';
    h += '<div class="progress-bar"><div class="progress-fill" style="width:' + (m.percent || 0) + '%;background:' + (m.color || '#00d4ff') + ';"></div></div>';
    h += '<div style="font-size:0.85em;color:#888;margin-top:6px;">';
    h += 'Win-Rate: ' + (rl.win_rate || 0).toFixed(1) + '% | ε: ' + (rl.epsilon || 0).toFixed(3);
    h += ' | Steps: ' + (rl.total_steps || 0) + ' | Memory: ' + (rl.memory_size || 0);
    h += '</div>';
    $('rlStatus').innerHTML = h;
}

function renderConfig(s) {
    const cfg = s.config || {};
    const rows = [
        ['Batterie max', (cfg.battery_max_ct || 0) + 'ct'],
        ['EV max', (cfg.ev_max_ct || 0) + 'ct'],
        ['EV Deadline', cfg.ev_deadline || '--'],
    ];
    let h = '';
    for (const [k, v] of rows) h += '<tr><td>' + k + '</td><td>' + v + '</td></tr>';
    $('configTable').querySelector('tbody').innerHTML = h;
}

// ---- Manual SoC Modal ----
function openModal(vehicleId, vehicleName, capacity) {
    currentVehicleId = vehicleId;
    $('modalVehicleName').textContent = vehicleName;
    $('modalCapacity').textContent = capacity.toFixed(0);
    $('manualSocInput').value = '';
    $('modalError').style.display = 'none';
    $('modalSuccess').style.display = 'none';
    $('manualSocModal').style.display = 'flex';
}

function closeModal() {
    $('manualSocModal').style.display = 'none';
}

async function submitManualSoc() {
    const soc = parseInt($('manualSocInput').value);
    $('modalError').style.display = 'none';
    $('modalSuccess').style.display = 'none';

    if (isNaN(soc) || soc < 0 || soc > 100) {
        $('modalError').textContent = 'Bitte gib einen Wert zwischen 0 und 100 ein.';
        $('modalError').style.display = 'block';
        return;
    }

    try {
        const resp = await fetch('/vehicles/manual-soc', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicle: currentVehicleId, soc: soc }),
        });
        const data = await resp.json();
        if (resp.ok) {
            $('modalSuccess').textContent = '✓ SoC für ' + currentVehicleId + ' auf ' + soc + '% gesetzt!';
            $('modalSuccess').style.display = 'block';
            setTimeout(() => { closeModal(); refresh(); }, 1500);
        } else {
            $('modalError').textContent = data.error || 'Fehler beim Speichern';
            $('modalError').style.display = 'block';
        }
    } catch (err) {
        $('modalError').textContent = 'Netzwerkfehler: ' + err.message;
        $('modalError').style.display = 'block';
    }
}

// ESC & backdrop close
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
$('manualSocModal').addEventListener('click', e => { if (e.target === $('manualSocModal')) closeModal(); });

// ---- Init ----
refresh();
setInterval(refresh, 60000);
