/**
 * EVCC-Smartload Dashboard v4.3.2
 *
 * Fetches /status, /slots, /vehicles, /strategy, /chart-data, /rl-devices
 * Auto-refreshes every 60 seconds.
 */

let currentVehicleId = '';

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
        if (min < 2) return '<span style="color:#00ff88">\u{1F550} vor ' + min + 'min</span>';
        if (min < 60) return '<span style="color:#ffaa00">\u{1F550} vor ' + min + 'min</span>';
        return '<span style="color:#ff4444">\u{1F550} vor ' + Math.floor(min/60) + 'h</span>';
    } catch(e) { return ''; }
}

async function fetchJSON(url) {
    try {
        const r = await fetch(url);
        return r.ok ? await r.json() : null;
    } catch (e) {
        console.error('Fetch error:', url, e);
        return null;
    }
}

// ---- Main refresh ----
async function refresh() {
    const [status, slots, vehicles, strategy, chartData, rlDevices] = await Promise.all([
        fetchJSON('/status'),
        fetchJSON('/slots'),
        fetchJSON('/vehicles'),
        fetchJSON('/strategy'),
        fetchJSON('/chart-data'),
        fetchJSON('/rl-devices'),
    ]);
    if (status) renderStatus(status);
    if (strategy) renderStrategy(strategy);
    if (chartData) renderChart(chartData);
    if (chartData) renderEnergyBalance(chartData);
    if (slots) renderSlots(slots, vehicles);
    if (status) renderRL(status);
    if (rlDevices) renderRLDevices(rlDevices);
    if (status) renderConfig(status);
}

// ---- Status cards ----
function renderStatus(s) {
    const c = s.current || {};
    $('priceVal').textContent = c.price_ct != null ? c.price_ct.toFixed(1) + ' ct' : '--';
    $('priceVal').style.color = priceColor(c.price_ct);
    $('batteryVal').textContent = c.battery_soc != null ? c.battery_soc.toFixed(0) + '%' : '--';
    $('batteryVal').style.color = socColor(c.battery_soc || 0);
    $('pvVal').textContent = c.pv_w != null ? (c.pv_w / 1000).toFixed(1) + ' kW' : '--';
    $('homeVal').textContent = c.home_w != null ? (c.home_w / 1000).toFixed(1) + ' kW' : '--';
}

// ---- Strategy banner ----
function renderStrategy(s) {
    $('strategyText').innerHTML = s.text || 'Keine Strategie';
    var details = s.details || [];
    if (details.length > 2) {
        $('strategyDetails').innerHTML = details.slice(2).join('<br>');
        $('strategyDetails').style.display = 'block';
    } else {
        $('strategyDetails').style.display = 'none';
    }
}

// ---- Price chart ----
function renderChart(data) {
    var prices = data.prices || [];
    if (!prices.length) { $('chartBars').innerHTML = '<div style="color:#888;padding:20px;">Keine Preisdaten</div>'; return; }

    var maxPrice = Math.max.apply(null, prices.map(function(p){ return p.price_ct; }).concat([40]));
    var batLimit = data.battery_max_ct || 35;
    var evLimit = data.ev_max_ct || 40;

    var html = '';
    for (var i = 0; i < prices.length; i++) {
        var p = prices[i];
        var h = Math.max(2, (p.price_ct / maxPrice) * 120);
        var col = priceColor(p.price_ct);
        var cls = p.is_now ? ' now' : '';
        html += '<div class="chart-bar' + cls + '" style="height:' + h + 'px;background:' + col + ';" title="' + p.hour + ': ' + p.price_ct.toFixed(1) + 'ct">';
        html += '<span class="bar-value" style="color:' + col + ';">' + p.price_ct.toFixed(1) + '</span>';
        html += '<span class="bar-label">' + p.hour + '</span>';
        html += '</div>';
    }
    $('chartBars').innerHTML = html;

    // Limit lines
    var wrap = $('chartWrap');
    var existing = wrap.querySelectorAll('.chart-limit,.pv-indicator');
    for (var j = 0; j < existing.length; j++) existing[j].remove();

    function addLimit(val, label, color) {
        var pct = (val / maxPrice) * 120;
        var bottom = pct + 22;
        var el = document.createElement('div');
        el.className = 'chart-limit';
        el.style.bottom = bottom + 'px';
        el.style.borderTopColor = color;
        el.innerHTML = '<span class="limit-label" style="color:' + color + ';">' + label + '</span>';
        wrap.appendChild(el);
    }
    addLimit(batLimit, '\u{1F50B} ' + batLimit + 'ct', '#00d4ff');
    if (evLimit !== batLimit) addLimit(evLimit, '\u{1F50C} ' + evLimit + 'ct', '#ff88ff');

    // PV indicator
    var pvKw = data.pv_now_kw || 0;
    if (pvKw > 0) {
        var pvEl = document.createElement('div');
        pvEl.className = 'pv-indicator';
        pvEl.style.cssText = 'text-align:right;font-size:0.85em;color:#ffdd00;margin-top:4px;';
        pvEl.textContent = '\u2600\uFE0F Aktuell: ' + pvKw.toFixed(1) + ' kW PV';
        wrap.appendChild(pvEl);
    }
}

// ---- Energy Balance ----
function renderEnergyBalance(data) {
    var el = document.getElementById('energyBalance');
    if (!el) return;

    var pv = data.pv_now_kw || 0;
    var home = data.home_now_kw || 0;
    var grid = data.grid_now_kw || 0;
    var bat = data.battery_power_kw || 0;
    var surplus = data.pv_surplus_kw || 0;

    var gridColor = grid > 0 ? '#ff4444' : '#00ff88';
    var gridLabel = grid > 0 ? 'Netzbezug' : 'Einspeisung';
    var batColor = bat > 0 ? '#00ff88' : '#ffaa00';
    var batLabel = bat > 0 ? 'Bat. l\u00E4dt' : (bat < 0 ? 'Bat. entl\u00E4dt' : 'Batterie');

    var h = '';
    h += '<div class="eb-item"><div class="eb-value" style="color:#ffdd00;">' + pv.toFixed(1) + ' kW</div><div class="eb-label">\u2600\uFE0F PV-Erzeugung</div></div>';
    h += '<div class="eb-item"><div class="eb-value" style="color:#ffaa00;">' + home.toFixed(1) + ' kW</div><div class="eb-label">\u{1F3E0} Hausverbrauch</div></div>';
    h += '<div class="eb-item"><div class="eb-value" style="color:' + gridColor + ';">' + Math.abs(grid).toFixed(1) + ' kW</div><div class="eb-label">\u{1F50C} ' + gridLabel + '</div></div>';
    h += '<div class="eb-item"><div class="eb-value" style="color:' + batColor + ';">' + Math.abs(bat).toFixed(1) + ' kW</div><div class="eb-label">\u{1F50B} ' + batLabel + '</div></div>';
    if (surplus > 0.1) {
        h += '<div class="eb-item"><div class="eb-value" style="color:#00ff88;">' + surplus.toFixed(1) + ' kW</div><div class="eb-label">\u2728 PV-\u00DCberschuss</div></div>';
    }
    el.innerHTML = h;
}

// ---- Device cards ----
function renderSlots(slots, vehicles) {
    var container = $('devicesContainer');
    if (!container) return;
    var html = '';
    var bat = slots.battery;
    if (bat) html += renderDevice(bat, 'battery', null);
    var vMap = vehicles ? (vehicles.vehicles || {}) : {};
    var names = Object.keys(slots.vehicles || {});
    for (var i = 0; i < names.length; i++) {
        var name = names[i];
        html += renderDevice(slots.vehicles[name], name, vMap[name] || {});
    }
    container.innerHTML = html;
}

function renderDevice(dev, deviceId, vehicleInfo) {
    var soc = dev.current_soc || 0;
    var target = dev.target_soc || 80;
    var cap = dev.capacity_kwh || 0;
    var need = dev.need_kwh || 0;
    var statusText = dev.status || '';
    var slots = dev.slots || [];
    var icon = dev.icon || '\u{1F50B}';
    var name = dev.name || deviceId;

    // Use server-computed age strings
    var pollAge = dev.poll_age || vehicleInfo?.poll_age || '';
    var dataAge = dev.data_age || vehicleInfo?.data_age || '';
    var isStale = dev.is_stale || vehicleInfo?.is_stale || false;
    var dataSource = dev.data_source || vehicleInfo?.data_source || 'evcc';

    var isManual = vehicleInfo && vehicleInfo.manual_soc != null && vehicleInfo.manual_soc > 0;
    var displaySoc = soc;
    if (isManual && soc === 0) displaySoc = vehicleInfo.manual_soc;

    var showManualBtn = deviceId !== 'battery' && ((soc === 0 && !isManual) || deviceId.toLowerCase().includes('ora') || isManual);

    var h = '<div class="device-card">';
    h += '<div class="device-header"><div>';
    h += '<span class="device-name">' + icon + ' ' + name + '</span>';
    h += ' <span style="color:#888;margin-left:10px;">' + cap.toFixed(0) + ' kWh</span>';
    // Show poll time (when we last checked), not data age
    if (pollAge && deviceId !== 'battery') {
        var pollColor = pollAge.includes('gerade') ? '#00ff88' : '#ffaa00';
        h += ' <span style="margin-left:10px;font-size:0.85em;color:' + pollColor + ';">\u{1F4E1} ' + pollAge + '</span>';
    }
    if (isManual) h += ' <span class="manual-badge">\u270F\uFE0F manuell: ' + vehicleInfo.manual_soc.toFixed(0) + '%</span>';
    h += '</div><div class="device-status">' + statusText + '</div></div>';

    // Stale warning: shows DATA age (how old the vehicle's own data is)
    if (isStale && displaySoc > 0 && deviceId !== 'battery') {
        h += '<div class="stale-warning"><strong style="color:#ffaa00;">\u26A0\uFE0F Fahrzeug-Daten veraltet</strong><br>';
        h += '<span style="font-size:0.85em;color:#888;">Letzte Fahrzeugmeldung: ' + dataAge + ' (' + dataSource + ')</span></div>';
    }

    var sColor = socColor(displaySoc);
    h += '<div style="display:flex;align-items:center;gap:10px;">';
    h += '<span style="color:' + sColor + ';font-size:1.5em;font-weight:bold;">' + displaySoc.toFixed(0) + '%</span>';
    h += '<div style="flex:1;"><div class="soc-bar"><div class="soc-fill" style="width:' + displaySoc + '%;background:' + sColor + ';"></div></div></div>';
    h += '<span style="color:#888;">\u2192 ' + target + '%</span></div>';

    if (showManualBtn) {
        h += '<div style="margin-top:10px;">';
        h += '<button class="btn-manual" onclick="openModal(\'' + deviceId + '\',\'' + name + '\',' + cap + ')">\u270F\uFE0F SoC manuell eingeben</button>';
        if (!isManual) h += ' <span style="margin-left:10px;font-size:0.85em;color:#888;">(keine API verf\u00FCgbar)</span>';
        h += '</div>';
    }

    if (need > 0 && slots.length > 0) {
        var pvOff = dev.pv_offset_kwh || 0;
        var grossNeed = dev.gross_need_kwh || need;
        var needText = '<strong>' + need.toFixed(1) + ' kWh</strong> in <strong>' + (dev.hours_needed || 0) + ' Stunden</strong>';
        if (pvOff > 0.5) needText += ' <span style="color:#ffdd00;">(Brutto: ' + grossNeed.toFixed(1) + ' kWh, PV spart ~' + pvOff.toFixed(0) + ' kWh)</span>';
        h += '<div style="margin-top:10px;color:#888;font-size:0.9em;">Netz-Bedarf: ' + needText + '</div>';
        h += '<div class="slots-container">';
        for (var s = 0; s < slots.length; s++) {
            var sl = slots[s];
            var pc = sl.price_ct || 0;
            var active = sl.is_now ? ' active' : '';
            h += '<div class="slot' + active + '"><div class="time">' + sl.hour + '</div>';
            h += '<div class="price" style="color:' + priceColor(pc) + ';">' + pc.toFixed(1) + 'ct</div>';
            h += '<div class="cost">' + (sl.energy_kwh || 0).toFixed(1) + 'kWh</div>';
            h += '<div class="cost">\u20AC' + (sl.cost_eur || 0).toFixed(2) + '</div></div>';
        }
        h += '</div>';
        h += '<div class="summary">';
        h += '<div class="summary-item"><div class="summary-value">' + slots.length + 'h</div><div class="summary-label">Ladedauer</div></div>';
        h += '<div class="summary-item"><div class="summary-value">' + (dev.avg_price_ct || 0).toFixed(1) + 'ct</div><div class="summary-label">\u2300 Preis</div></div>';
        h += '<div class="summary-item"><div class="summary-value">\u20AC' + (dev.total_cost_eur || 0).toFixed(2) + '</div><div class="summary-label">Gesamtkosten</div></div>';
        h += '</div>';
    } else if (need <= 0) {
        h += '<p style="color:#00ff88;margin-top:10px;">\u2705 Kein Ladebedarf</p>';
    } else {
        h += '<p style="color:#ffaa00;margin-top:10px;">\u26A0\uFE0F ' + need.toFixed(1) + ' kWh Bedarf, aber keine passenden Slots</p>';
    }

    h += '</div>';
    return h;
}

// ---- RL maturity ----
function renderRL(s) {
    var rl = s.rl || {};
    var m = s.rl_maturity || {};
    var h = '';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">';
    h += '<span style="font-size:1.1em;">' + (m.status || '?') + '</span>';
    h += '<span style="color:#888;">' + (m.message || '') + '</span></div>';
    h += '<div class="progress-bar"><div class="progress-fill" style="width:' + (m.percent || 0) + '%;background:' + (m.color || '#00d4ff') + ';"></div></div>';
    h += '<div style="font-size:0.85em;color:#888;margin-top:6px;">';
    h += 'Win-Rate: ' + (rl.win_rate || 0).toFixed(1) + '% | \u03B5: ' + (rl.epsilon || 0).toFixed(3);
    h += ' | Steps: ' + (rl.total_steps || 0) + ' | Memory: ' + (rl.memory_size || 0);
    h += '</div>';
    $('rlStatus').innerHTML = h;
}

// ---- RL device table ----
function renderRLDevices(data) {
    var devices = data.devices || {};
    var names = Object.keys(devices);
    if (!names.length) { $('rlDevices').innerHTML = '<div style="color:#888;font-size:0.85em;">Keine RL-Ger\u00E4te registriert</div>'; return; }

    var h = '<table class="rl-devices-table">';
    h += '<thead><tr><th>Ger\u00E4t</th><th>Modus</th><th>Win-Rate</th><th>Vergleiche</th><th>Steuerung</th></tr></thead><tbody>';
    for (var i = 0; i < names.length; i++) {
        var nm = names[i];
        var d = devices[nm];
        var mode = d.current_mode || 'lp';
        var ovr = d.override_mode || null;
        var wr = d.win_rate != null ? (d.win_rate * 100).toFixed(1) + '%' : '--';
        var comp = d.comparisons || 0;
        var modeText = mode === 'rl' ? '<span style="color:#00ff88;">\u{1F7E2} RL</span>' : '<span style="color:#00d4ff;">\u{1F535} LP</span>';

        h += '<tr><td><strong>' + nm + '</strong></td>';
        h += '<td>' + modeText + '</td>';
        h += '<td>' + wr + '</td>';
        h += '<td>' + comp + '</td>';
        h += '<td>';
        h += '<button class="mode-btn' + (!ovr ? ' active' : '') + '" onclick="setRLMode(\'' + nm + '\',null)">Auto</button>';
        h += '<button class="mode-btn' + (ovr === 'lp' ? ' active' : '') + '" onclick="setRLMode(\'' + nm + '\',\'lp\')">LP</button>';
        h += '<button class="mode-btn' + (ovr === 'rl' ? ' active' : '') + '" onclick="setRLMode(\'' + nm + '\',\'rl\')">RL</button>';
        h += '</td></tr>';
    }
    h += '</tbody></table>';
    $('rlDevices').innerHTML = h;
}

async function setRLMode(device, mode) {
    try {
        await fetch('/rl-override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device: device, mode: mode }),
        });
        refresh();
    } catch (e) { console.error('RL override error:', e); }
}

// ---- Config ----
function renderConfig(s) {
    var cfg = s.config || {};
    var rows = [
        ['Batterie max', (cfg.battery_max_ct || 0) + 'ct'],
        ['EV max', (cfg.ev_max_ct || 0) + 'ct'],
        ['EV Deadline', cfg.ev_deadline || '--'],
    ];
    var h = '';
    for (var i = 0; i < rows.length; i++) h += '<tr><td>' + rows[i][0] + '</td><td>' + rows[i][1] + '</td></tr>';
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

function closeModal() { $('manualSocModal').style.display = 'none'; }

async function submitManualSoc() {
    var soc = parseInt($('manualSocInput').value);
    $('modalError').style.display = 'none';
    $('modalSuccess').style.display = 'none';
    if (isNaN(soc) || soc < 0 || soc > 100) {
        $('modalError').textContent = 'Bitte gib einen Wert zwischen 0 und 100 ein.';
        $('modalError').style.display = 'block';
        return;
    }
    try {
        var resp = await fetch('/vehicles/manual-soc', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicle: currentVehicleId, soc: soc }),
        });
        var data = await resp.json();
        if (resp.ok) {
            $('modalSuccess').textContent = '\u2713 SoC f\u00FCr ' + currentVehicleId + ' auf ' + soc + '% gesetzt!';
            $('modalSuccess').style.display = 'block';
            setTimeout(function(){ closeModal(); refresh(); }, 1500);
        } else {
            $('modalError').textContent = data.error || 'Fehler';
            $('modalError').style.display = 'block';
        }
    } catch (err) {
        $('modalError').textContent = 'Netzwerkfehler: ' + err.message;
        $('modalError').style.display = 'block';
    }
}

document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeModal(); });
$('manualSocModal').addEventListener('click', function(e) { if (e.target === $('manualSocModal')) closeModal(); });

refresh();
setInterval(refresh, 60000);
