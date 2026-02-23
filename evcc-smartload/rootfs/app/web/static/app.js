/**
 * EVCC-Smartload Dashboard v6.0
 *
 * v6: SSE (Server-Sent Events) via /events for live state push.
 *   - EventSource connects to /events on load.
 *   - On each message, key values are updated in-place with a brief CSS flash.
 *   - Persistent "vor X Min aktualisiert" timestamp per data point.
 *   - Connection indicator (green dot = connected, grey = disconnected).
 *   - Existing 60s polling preserved as fallback for non-SSE endpoints.
 *
 * Fetches /status, /slots, /vehicles, /strategy, /chart-data,
 *         /rl-devices, /decisions, /sequencer
 * Auto-refreshes every 60 seconds.
 */

let currentVehicleId = '';
let currentSeqVehicle = '';

// v6: SSE state
var _sseSource = null;
var _sseLastUpdate = null;  // ISO string from last SSE message

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
    const [status, slots, vehicles, strategy, chartData, rlDevices, decisions, sequencer] = await Promise.all([
        fetchJSON('/status'),
        fetchJSON('/slots'),
        fetchJSON('/vehicles'),
        fetchJSON('/strategy'),
        fetchJSON('/chart-data'),
        fetchJSON('/rl-devices'),
        fetchJSON('/decisions'),
        fetchJSON('/sequencer'),
    ]);
    if (status) renderStatus(status);
    if (strategy) renderStrategy(strategy);
    if (chartData) renderChart(chartData);
    if (chartData) renderEnergyBalance(chartData);
    if (slots) renderSlots(slots, vehicles);
    if (status) renderRL(status);
    if (rlDevices) renderRLDevices(rlDevices);
    if (status) renderConfig(status);
    if (decisions) renderDecisions(decisions);
    if (sequencer) renderSequencer(sequencer);
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

// ---- Price chart (SVG) ----
function renderChart(data) {
    var prices = data.prices || [];
    var wrap = $('chartWrap');
    if (!prices.length) { wrap.innerHTML = '<div style="color:#888;padding:20px;">Keine Preisdaten</div>'; return; }

    var batLimit = data.battery_max_ct || 35;
    var evLimit = data.ev_max_ct || 40;
    var activeBat = data.active_battery_ct || null;
    var activeEv = data.active_ev_ct || null;
    var hasSolar = data.has_solar_forecast || false;
    var percentiles = data.percentiles || {};
    var p30 = percentiles[30] || percentiles['30'] || null;

    // --- Layout constants ---
    var marginL = 38, marginR = hasSolar ? 42 : 12, marginT = 18, marginB = 32;
    var n = prices.length;
    var containerW = wrap.clientWidth || 700;
    var W = containerW;
    var H = 200;
    var plotW = W - marginL - marginR;
    var plotH = H - marginT - marginB;

    var maxPrice = Math.max.apply(null, prices.map(function(p){ return p.price_ct; }));
    maxPrice = Math.max(maxPrice, evLimit + 2, 30);
    maxPrice = Math.ceil(maxPrice / 5) * 5;

    var maxSolar = 0;
    if (hasSolar) {
        maxSolar = Math.max.apply(null, prices.map(function(p){ return p.solar_kw || 0; }).concat([0.5]));
        maxSolar = Math.ceil(maxSolar);
    }

    var barW = plotW / n;
    var barGap = Math.max(1, barW * 0.12);
    var barInner = barW - barGap;

    // --- Build SVG ---
    var s = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';

    s += '<defs>';
    s += '<linearGradient id="solarGrad" x1="0" y1="0" x2="0" y2="1">';
    s += '<stop offset="0%" stop-color="#ffdd00" stop-opacity="0.35"/>';
    s += '<stop offset="100%" stop-color="#ffdd00" stop-opacity="0.05"/>';
    s += '</linearGradient>';
    s += '<filter id="glowNow"><feGaussianBlur stdDeviation="3" result="blur"/>';
    s += '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    s += '</defs>';

    // Y-axis grid lines + labels (price)
    var ySteps = maxPrice <= 30 ? 5 : (maxPrice <= 50 ? 5 : 10);
    for (var yv = 0; yv <= maxPrice; yv += ySteps) {
        var yy = marginT + plotH - (yv / maxPrice) * plotH;
        s += '<line x1="' + marginL + '" y1="' + yy + '" x2="' + (W - marginR) + '" y2="' + yy + '" stroke="#333" stroke-width="0.5"/>';
        s += '<text x="' + (marginL - 4) + '" y="' + (yy + 3) + '" fill="#666" font-size="9" text-anchor="end" font-family="sans-serif">' + yv + '</text>';
    }
    s += '<text x="6" y="' + (marginT + plotH / 2) + '" fill="#888" font-size="8" text-anchor="middle" font-family="sans-serif" transform="rotate(-90,6,' + (marginT + plotH / 2) + ')">ct/kWh</text>';

    // Solar Y-axis (right side)
    if (hasSolar && maxSolar > 0.1) {
        for (var sv = 0; sv <= maxSolar; sv += Math.max(1, Math.ceil(maxSolar / 4))) {
            var sy = marginT + plotH - (sv / maxSolar) * plotH;
            s += '<text x="' + (W - marginR + 4) + '" y="' + (sy + 3) + '" fill="#998800" font-size="8" font-family="sans-serif">' + sv + '</text>';
        }
        s += '<text x="' + (W - 5) + '" y="' + (marginT + plotH / 2) + '" fill="#998800" font-size="8" text-anchor="middle" font-family="sans-serif" transform="rotate(90,' + (W - 5) + ',' + (marginT + plotH / 2) + ')">kW \u2600</text>';
    }

    // Solar area (drawn BEFORE bars so bars are on top)
    if (hasSolar && maxSolar > 0.1) {
        var solarPts = '';
        var firstX = marginL + barW * 0.5;
        for (var si = 0; si < n; si++) {
            var skw = prices[si].solar_kw || 0;
            var sx = marginL + si * barW + barW * 0.5;
            var sy2 = marginT + plotH - (skw / maxSolar) * plotH;
            solarPts += (si === 0 ? 'M' : 'L') + sx.toFixed(1) + ',' + sy2.toFixed(1) + ' ';
        }
        var lastX = marginL + (n - 1) * barW + barW * 0.5;
        var baseY = marginT + plotH;
        s += '<path d="' + solarPts + 'L' + lastX.toFixed(1) + ',' + baseY + ' L' + firstX.toFixed(1) + ',' + baseY + ' Z" fill="url(#solarGrad)" />';
        s += '<path d="' + solarPts + '" fill="none" stroke="#ffdd00" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"/>';
    }

    // Limit lines helper
    function limitY(ct) { return marginT + plotH - (ct / maxPrice) * plotH; }

    // P30 Percentile line (EV cheapest 30% window) — NEW in v5
    if (p30 != null && p30 > 0) {
        var p30Y = limitY(p30 * 100);  // p30 is in EUR, convert to ct
        s += '<line x1="' + marginL + '" y1="' + p30Y + '" x2="' + (W - marginR) + '" y2="' + p30Y + '" stroke="#00ffcc" stroke-width="1.2" stroke-dasharray="4,3" opacity="0.8"/>';
        s += '<text x="' + (marginL + 3) + '" y="' + (p30Y - 3) + '" fill="#00ffcc" font-size="8" font-family="sans-serif">\u26A1 P30 ' + (p30 * 100).toFixed(1) + 'ct</text>';
    }

    var batY = limitY(batLimit);
    s += '<line x1="' + marginL + '" y1="' + batY + '" x2="' + (W - marginR) + '" y2="' + batY + '" stroke="#00d4ff" stroke-width="1" stroke-dasharray="6,3" opacity="0.7"/>';
    s += '<text x="' + (W - marginR - 2) + '" y="' + (batY - 3) + '" fill="#00d4ff" font-size="8" text-anchor="end" font-family="sans-serif">\uD83D\uDD0B ' + batLimit + 'ct</text>';

    if (Math.abs(evLimit - batLimit) > 1) {
        var evY = limitY(evLimit);
        s += '<line x1="' + marginL + '" y1="' + evY + '" x2="' + (W - marginR) + '" y2="' + evY + '" stroke="#ff88ff" stroke-width="1" stroke-dasharray="6,3" opacity="0.7"/>';
        s += '<text x="' + (W - marginR - 2) + '" y="' + (evY - 3) + '" fill="#ff88ff" font-size="8" text-anchor="end" font-family="sans-serif">\uD83D\uDD0C ' + evLimit + 'ct</text>';
    }

    // Active dynamic limits (solid lines — the ACTUAL applied thresholds)
    if (activeBat != null && activeBat > 0 && Math.abs(activeBat - batLimit) > 0.5) {
        var abY = limitY(activeBat);
        s += '<line x1="' + marginL + '" y1="' + abY + '" x2="' + (W - marginR) + '" y2="' + abY + '" stroke="#00d4ff" stroke-width="1.8" opacity="0.9"/>';
        s += '<text x="' + (marginL + 3) + '" y="' + (abY - 3) + '" fill="#00d4ff" font-size="8" font-family="sans-serif">\uD83D\uDD0B\u21D2 ' + activeBat + 'ct</text>';
    }
    if (activeEv != null && activeEv > 0 && Math.abs(activeEv - evLimit) > 0.5) {
        var aeY = limitY(activeEv);
        s += '<line x1="' + marginL + '" y1="' + aeY + '" x2="' + (W - marginR) + '" y2="' + aeY + '" stroke="#ff88ff" stroke-width="1.8" opacity="0.9"/>';
        s += '<text x="' + (marginL + 3) + '" y="' + (aeY - 3) + '" fill="#ff88ff" font-size="8" font-family="sans-serif">\uD83D\uDD0C\u21D2 ' + activeEv + 'ct</text>';
    }

    // Price bars
    for (var i = 0; i < n; i++) {
        var p = prices[i];
        var barH = Math.max(1, (p.price_ct / maxPrice) * plotH);
        var bx = marginL + i * barW + barGap / 2;
        var by = marginT + plotH - barH;
        var col = priceColor(p.price_ct);
        var isCheapP30 = p30 != null && p.price_ct <= (p30 * 100);

        // Cheap P30 highlight (subtle glow)
        if (isCheapP30) {
            s += '<rect x="' + bx + '" y="' + marginT + '" width="' + barInner + '" height="' + plotH + '" rx="1" fill="#00ffcc" opacity="0.04"/>';
        }

        if (p.is_now) {
            s += '<rect x="' + (bx - 1) + '" y="' + (by - 1) + '" width="' + (barInner + 2) + '" height="' + (barH + 2) + '" rx="2" fill="none" stroke="#00d4ff" stroke-width="2" filter="url(#glowNow)" opacity="0.6"/>';
        }

        s += '<rect x="' + bx + '" y="' + by + '" width="' + barInner + '" height="' + barH + '" rx="1.5" fill="' + col + '" opacity="' + (p.is_now ? '1' : '0.85') + '" data-idx="' + i + '" class="price-bar" style="cursor:pointer;"/>';

        if (barH > 18 && barInner > 14) {
            var labelSize = barInner > 20 ? 9 : 7;
            s += '<text x="' + (bx + barInner / 2) + '" y="' + (by + barH / 2 + 3) + '" fill="#000" font-size="' + labelSize + '" text-anchor="middle" font-weight="bold" font-family="sans-serif" pointer-events="none">';
            s += p.price_ct.toFixed(0);
            s += '</text>';
        } else if (barH > 8 && barInner > 10) {
            s += '<text x="' + (bx + barInner / 2) + '" y="' + (by - 2) + '" fill="' + col + '" font-size="7" text-anchor="middle" font-family="sans-serif" pointer-events="none">' + p.price_ct.toFixed(0) + '</text>';
        }

        var hourNum = parseInt(p.hour);
        var showLabel = false;
        if (n <= 24) showLabel = (hourNum % 3 === 0);
        else if (n <= 48) showLabel = (hourNum % 6 === 0) || (i === 0);
        else showLabel = (hourNum % 6 === 0) || (i === 0);
        if (p.is_now) showLabel = true;

        if (showLabel) {
            var lx = bx + barInner / 2;
            var ly = marginT + plotH + 14;
            s += '<text x="' + lx + '" y="' + ly + '" fill="' + (p.is_now ? '#00d4ff' : '#888') + '" font-size="9" text-anchor="middle" font-family="sans-serif" font-weight="' + (p.is_now ? 'bold' : 'normal') + '">' + p.hour + '</text>';
        }

        if (p.is_now) {
            s += '<text x="' + (bx + barInner / 2) + '" y="' + (marginT + plotH + 26) + '" fill="#00d4ff" font-size="8" text-anchor="middle" font-family="sans-serif">\u25B2 jetzt</text>';
        }
    }

    s += '</svg>';
    wrap.innerHTML = s + '<div class="chart-tooltip" id="chartTooltip"></div>';

    // --- Tooltip on hover ---
    var tooltip = $('chartTooltip');
    var bars = wrap.querySelectorAll('.price-bar');
    for (var b = 0; b < bars.length; b++) {
        bars[b].addEventListener('mouseenter', function(e) {
            var idx = parseInt(this.getAttribute('data-idx'));
            var p = prices[idx];
            if (!p) return;
            var html = '<div class="tt-time">' + p.hour + ':00</div>';
            html += '<div class="tt-price" style="color:' + priceColor(p.price_ct) + ';">' + p.price_ct.toFixed(1) + ' ct/kWh</div>';
            if (p.solar_kw > 0) html += '<div class="tt-solar">\u2600\uFE0F ' + p.solar_kw.toFixed(1) + ' kW</div>';
            if (p30 != null && p.price_ct <= (p30 * 100)) html += '<div style="color:#00ffcc;font-size:0.9em;">\u26A1 G\u00FCnstigstes 30%-Fenster \u2713</div>';
            if (p.price_ct <= batLimit) html += '<div style="color:#00d4ff;font-size:0.9em;">\uD83D\uDD0B Batterie-Laden \u2713</div>';
            if (p.price_ct <= evLimit) html += '<div style="color:#ff88ff;font-size:0.9em;">\uD83D\uDD0C EV-Laden \u2713</div>';
            tooltip.innerHTML = html;
            tooltip.style.display = 'block';
        });
        bars[b].addEventListener('mousemove', function(e) {
            var rect = wrap.getBoundingClientRect();
            var x = e.clientX - rect.left + 10;
            var y = e.clientY - rect.top - 10;
            if (x + 140 > rect.width) x = x - 160;
            tooltip.style.left = x + 'px';
            tooltip.style.top = y + 'px';
        });
        bars[b].addEventListener('mouseleave', function() {
            tooltip.style.display = 'none';
        });
    }

    // Summary line
    var pvKw = data.pv_now_kw || 0;
    var summaryHtml = '';
    if (pvKw > 0) summaryHtml += '<span style="color:#ffdd00;">\u2600\uFE0F Aktuell: ' + pvKw.toFixed(1) + ' kW PV</span>';
    if (hasSolar) {
        var totalKwh = data.solar_total_kwh || 0;
        summaryHtml += '<span style="color:#ffdd00;">\uD83D\uDCC8 Prognose: ' + totalKwh.toFixed(0) + ' kWh</span>';
    }
    if (p30 != null) {
        summaryHtml += '<span style="color:#00ffcc;">\u26A1 P30: ' + (p30 * 100).toFixed(1) + 'ct</span>';
    }
    if (summaryHtml) {
        var sumEl = document.createElement('div');
        sumEl.style.cssText = 'display:flex;justify-content:space-between;font-size:0.85em;margin-top:4px;flex-wrap:wrap;gap:8px;';
        sumEl.innerHTML = summaryHtml;
        wrap.appendChild(sumEl);
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
    h += '<div class="eb-item"><div class="eb-value" style="color:#ffaa00;">' + home.toFixed(1) + ' kW</div><div class="eb-label">\uD83C\uDFE0 Hausverbrauch</div></div>';
    h += '<div class="eb-item"><div class="eb-value" style="color:' + gridColor + ';">' + Math.abs(grid).toFixed(1) + ' kW</div><div class="eb-label">\uD83D\uDD0C ' + gridLabel + '</div></div>';
    h += '<div class="eb-item"><div class="eb-value" style="color:' + batColor + ';">' + Math.abs(bat).toFixed(1) + ' kW</div><div class="eb-label">\uD83D\uDD0B ' + batLabel + '</div></div>';
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

    renderBatToEv(slots.battery_to_ev);
}

function renderBatToEv(b2e) {
    var card = $('batToEvCard');
    var content = $('batToEvContent');
    if (!card || !content || !b2e) { if (card) card.style.display = 'none'; return; }

    card.style.display = '';
    var profitable = b2e.is_profitable;

    if (b2e.ev_need_kwh < 0.5) {
        card.style.borderLeft = '3px solid #555';
        var h = '<div style="color:#888;font-size:0.95em;">\u2705 Alle Fahrzeuge geladen \u2014 kein Entladebedarf</div>';
        h += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:0.85em;margin-top:8px;">';
        h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
        h += '<div style="color:#888;font-size:0.8em;">Batterie verf\u00FCgbar</div>';
        h += '<div style="color:#00d4ff;">' + b2e.available_kwh + ' kWh</div></div>';
        h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
        h += '<div style="color:#888;font-size:0.8em;">Netzpreis aktuell</div>';
        h += '<div>' + b2e.grid_price_ct + ' ct/kWh</div></div>';
        h += '</div>';
        content.innerHTML = h;
        return;
    }

    var borderColor = profitable ? '#00ff88' : '#555';
    card.style.borderLeft = '3px solid ' + borderColor;

    var h = '<div style="margin-bottom:10px;font-size:1.05em;">' + b2e.recommendation + '</div>';

    h += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:0.9em;">';
    h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
    h += '<div style="color:#888;font-size:0.8em;">Batterie verf\u00FCgbar</div>';
    h += '<div style="color:#00d4ff;font-size:1.1em;font-weight:bold;">' + b2e.available_kwh + ' kWh</div></div>';

    h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
    h += '<div style="color:#888;font-size:0.8em;">EV-Bedarf</div>';
    h += '<div style="color:#ff88ff;font-size:1.1em;font-weight:bold;">' + b2e.ev_need_kwh + ' kWh</div></div>';

    h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
    h += '<div style="color:#888;font-size:0.8em;">Batterie-Kosten (inkl. Verluste)</div>';
    h += '<div style="font-size:1.1em;font-weight:bold;">' + b2e.bat_cost_ct + ' ct/kWh</div>';
    h += '<div style="color:#888;font-size:0.75em;">Roundtrip: ' + b2e.round_trip_efficiency + '%</div></div>';

    h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
    h += '<div style="color:#888;font-size:0.8em;">Netzpreis aktuell</div>';
    h += '<div style="font-size:1.1em;font-weight:bold;">' + b2e.grid_price_ct + ' ct/kWh</div>';
    h += '<div style="color:#888;font-size:0.75em;">\u00D8 n\u00E4chste 6h: ' + b2e.avg_upcoming_ct + 'ct</div></div>';
    h += '</div>';

    if (profitable && b2e.usable_kwh > 0.5) {
        var savingsTotal = (b2e.savings_ct_per_kwh * b2e.usable_kwh).toFixed(0);
        h += '<div style="margin-top:10px;padding:8px;background:#0a2a0a;border:1px solid #00ff88;border-radius:6px;text-align:center;">';
        h += '<span style="color:#00ff88;font-weight:bold;">\u2714 Ersparnis: ~' + savingsTotal + ' ct</span>';
        h += ' <span style="color:#888;font-size:0.85em;">(' + b2e.savings_ct_per_kwh + ' ct/kWh \u00D7 ' + b2e.usable_kwh + ' kWh)</span>';
        h += '</div>';
    } else {
        h += '<div style="margin-top:10px;padding:8px;background:#1a1a2e;border:1px solid #555;border-radius:6px;text-align:center;color:#888;font-size:0.9em;">';
        h += 'Mindest-Ersparnis: ' + b2e.min_profit_ct + ' ct/kWh n\u00F6tig';
        h += '</div>';
    }

    var dl = b2e.dynamic_limits;
    if (dl && b2e.dynamic_limit_enabled) {
        h += '<div style="margin-top:12px;padding:10px;background:#0f3460;border-radius:6px;">';
        h += '<div style="font-size:0.9em;font-weight:bold;margin-bottom:8px;color:#00d4ff;">\uD83C\uDFAF Dynamische Entladegrenze</div>';
        h += '<div style="position:relative;height:28px;background:#1a1a2e;border-radius:14px;overflow:hidden;margin-bottom:8px;border:1px solid #333;">';
        h += '<div style="position:absolute;left:0;width:' + dl.priority_soc + '%;height:100%;background:rgba(255,68,68,0.3);"></div>';
        var bufferWidth = Math.max(0, dl.buffer_soc - dl.priority_soc);
        h += '<div style="position:absolute;left:' + dl.priority_soc + '%;width:' + bufferWidth + '%;height:100%;background:rgba(255,170,0,0.2);"></div>';
        var evWidth = 100 - dl.buffer_soc;
        h += '<div style="position:absolute;left:' + dl.buffer_soc + '%;width:' + evWidth + '%;height:100%;background:rgba(0,255,136,0.15);"></div>';
        h += '<div style="position:absolute;left:' + (dl.priority_soc - 1) + '%;top:0;bottom:0;border-right:2px solid #ff4444;"></div>';
        h += '<div style="position:absolute;left:' + (dl.buffer_soc - 1) + '%;top:0;bottom:0;border-right:2px solid #00ff88;"></div>';
        h += '<div style="position:absolute;left:4px;top:50%;transform:translateY(-50%);font-size:0.7em;color:#ff8888;">\uD83D\uDEE1 ' + dl.priority_soc + '%</div>';
        h += '<div style="position:absolute;right:4px;top:50%;transform:translateY(-50%);font-size:0.7em;color:#00ff88;">\uD83D\uDD0B\u2192\uD83D\uDE97 ab ' + dl.buffer_soc + '%</div>';
        h += '</div>';
        h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.8em;">';
        if (dl.solar_refill_pct > 1) {
            h += '<div style="color:#ffdd00;">\u2600\uFE0F Solar: +' + dl.solar_refill_pct + '% (' + dl.solar_surplus_kwh + ' kWh)</div>';
        }
        if (dl.grid_refill_pct > 1) {
            h += '<div style="color:#00d4ff;">\u26A1 G\u00FCnstig-Netz: +' + dl.grid_refill_pct + '% (' + dl.cheap_hours + 'h)</div>';
        }
        h += '<div style="color:#ff88ff;">\uD83D\uDE97 EV braucht: ' + dl.ev_need_pct + '% (inkl. Verluste)</div>';
        h += '<div style="color:#888;">\uD83D\uDEE1 Untergrenze: ' + dl.floor_soc + '%</div>';
        h += '</div></div>';
    }

    content.innerHTML = h;
}

function renderDevice(dev, deviceId, vehicleInfo) {
    var soc = dev.current_soc || 0;
    var target = dev.target_soc || 80;
    var cap = dev.capacity_kwh || 0;
    var need = dev.need_kwh || 0;
    var statusText = dev.status || '';
    var slots = dev.slots || [];
    var icon = dev.icon || '\uD83D\uDD0B';
    var name = dev.name || deviceId;

    var pollAge = dev.poll_age || (vehicleInfo && vehicleInfo.poll_age) || '';
    var dataAge = dev.data_age || (vehicleInfo && vehicleInfo.data_age) || '';
    var isStale = dev.is_stale || (vehicleInfo && vehicleInfo.is_stale) || false;
    var dataSource = dev.data_source || (vehicleInfo && vehicleInfo.data_source) || 'evcc';

    var isManual = vehicleInfo && vehicleInfo.manual_soc != null && vehicleInfo.manual_soc > 0;
    var displaySoc = soc;
    if (isManual && soc === 0) displaySoc = vehicleInfo.manual_soc;

    var showManualBtn = deviceId !== 'battery' && ((soc === 0 && !isManual) || deviceId.toLowerCase().includes('ora') || isManual);

    var h = '<div class="device-card">';
    h += '<div class="device-header"><div>';
    h += '<span class="device-name">' + icon + ' ' + name + '</span>';
    h += ' <span style="color:#888;margin-left:10px;">' + cap.toFixed(0) + ' kWh</span>';
    if (pollAge && deviceId !== 'battery') {
        var pollColor = pollAge.includes('gerade') ? '#00ff88' : '#ffaa00';
        h += ' <span style="margin-left:10px;font-size:0.85em;color:' + pollColor + ';">\uD83D\uDCE1 ' + pollAge + '</span>';
    }
    var isConnected = dev.connected || false;
    var isCharging = dev.charging || false;
    if (deviceId !== 'battery') {
        if (isCharging) {
            h += ' <span style="margin-left:8px;font-size:0.85em;color:#00ff88;">\u26A1 L\u00E4dt</span>';
        } else if (isConnected) {
            h += ' <span style="margin-left:8px;font-size:0.85em;color:#00d4ff;">\uD83D\uDD0C Verbunden</span>';
        }
    }
    if (isManual) h += ' <span class="manual-badge">\u270F\uFE0F manuell: ' + vehicleInfo.manual_soc.toFixed(0) + '%</span>';
    h += '</div><div class="device-status">' + statusText + '</div></div>';

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
        for (var si = 0; si < slots.length; si++) {
            var sl = slots[si];
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
        h += '<div class="summary-item"><div class="summary-value">' + (dev.avg_price_ct || 0).toFixed(1) + 'ct</div><div class="summary-label">\u00D8 Preis</div></div>';
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
        var modeText = mode === 'rl' ? '<span style="color:#00ff88;">\uD83D\uDFE2 RL</span>' : '<span style="color:#00d4ff;">\uD83D\uDD35 LP</span>';

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
    var batActive = cfg.active_battery_ct != null ? ' \u2192 ' + cfg.active_battery_ct + 'ct' : '';
    var evActive = cfg.active_ev_ct != null ? ' \u2192 ' + cfg.active_ev_ct + 'ct' : '';
    var rows = [
        ['Batterie max', (cfg.battery_max_ct || 0) + 'ct' + batActive],
        ['EV max', (cfg.ev_max_ct || 0) + 'ct' + evActive],
        ['EV Deadline', cfg.ev_deadline || '--'],
        ['Roundtrip-Eff.', ((cfg.battery_charge_eff || 0.92) * (cfg.battery_discharge_eff || 0.92) * 100).toFixed(1) + '%'],
        ['Bat\u2192EV Min-Vorteil', (cfg.bat_to_ev_min_ct || 3) + 'ct'],
        ['Dynamische Grenze', cfg.bat_to_ev_dynamic ? '\u2705 aktiv' : '\u274C aus'],
        ['Entlade-Untergrenze', (cfg.bat_to_ev_floor || 20) + '%'],
        ['Ruhezeit', cfg.quiet_hours_enabled ?
            '\u{1F634} ' + (cfg.quiet_hours || '21:00–06:00') :
            '\u274C deaktiviert'],
    ];
    var h = '';
    for (var i = 0; i < rows.length; i++) h += '<tr><td>' + rows[i][0] + '</td><td>' + rows[i][1] + '</td></tr>';
    $('configTable').querySelector('tbody').innerHTML = h;
}

// ---- Charge Sequencer (NEU v5) ----
function renderSequencer(data) {
    var card = $('sequencerCard');
    if (!card) return;

    var requests = data.requests || [];
    var schedule = data.schedule || [];
    var quietHours = data.quiet_hours || {};
    var isQuiet = data.is_quiet_now || false;
    var preQuiet = data.pre_quiet_recommendation || null;

    var h = '';

    // Quiet Hours status badge
    if (quietHours.enabled) {
        var qColor = isQuiet ? '#ffaa00' : '#555';
        var qIcon = isQuiet ? '\uD83D\uDE34' : '\uD83D\uDD14';
        h += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
        h += '<span style="background:' + qColor + '22;border:1px solid ' + qColor + ';border-radius:12px;padding:3px 10px;font-size:0.85em;color:' + qColor + ';">';
        h += qIcon + ' Ruhezeit ' + quietHours.start + ':00–' + quietHours.end + ':00';
        if (isQuiet) h += ' \u2014 aktiv';
        h += '</span>';
        h += '</div>';
    }

    // Pre-quiet recommendation banner
    if (preQuiet) {
        h += '<div style="background:#2a1a00;border:1px solid #ffaa00;border-radius:6px;padding:10px;margin-bottom:12px;">';
        h += '<div style="color:#ffaa00;font-weight:bold;margin-bottom:4px;">\uD83D\uDD0C Bitte anstecken</div>';
        h += '<div style="font-size:0.9em;">' + escapeHtml(preQuiet.message) + '</div>';
        h += '</div>';
    }

    // Charge requests
    if (requests.length > 0) {
        h += '<div style="font-size:0.85em;color:#888;margin-bottom:6px;">Ladewünsche:</div>';
        h += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px;">';
        for (var i = 0; i < requests.length; i++) {
            var req = requests[i];
            var statusColor = req.status === 'charging' ? '#00ff88' :
                              req.status === 'scheduled' ? '#00d4ff' :
                              req.status === 'done' ? '#555' : '#ffaa00';
            var statusIcon = req.status === 'charging' ? '\u26A1' :
                             req.status === 'scheduled' ? '\uD83D\uDDD3' :
                             req.status === 'done' ? '\u2705' : '\u23F3';
            h += '<div style="background:#0f3460;border-radius:6px;padding:8px;display:flex;justify-content:space-between;align-items:center;">';
            h += '<div>';
            h += '<span style="font-weight:bold;">' + escapeHtml(req.vehicle) + '</span>';
            h += ' <span style="color:#888;font-size:0.85em;">(' + escapeHtml(req.driver || '') + ')</span>';
            h += '<br><span style="color:#888;font-size:0.85em;">';
            h += req.current_soc.toFixed(0) + '% \u2192 ' + req.target_soc + '% ';
            h += '<span style="color:#00d4ff;">(' + req.need_kwh.toFixed(1) + ' kWh)</span>';
            h += '</span></div>';
            h += '<div style="text-align:right;">';
            h += '<span style="color:' + statusColor + ';font-size:0.9em;">' + statusIcon + ' ' + req.status + '</span>';
            h += '<br><button class="seq-cancel-btn" onclick="cancelSeqRequest(\'' + req.vehicle + '\')" style="margin-top:4px;font-size:0.75em;padding:2px 6px;">\u274C</button>';
            h += '</div></div>';
        }
        h += '</div>';
    } else {
        h += '<div style="color:#555;font-size:0.9em;margin-bottom:12px;">Keine aktiven Ladewünsche. ';
        h += 'Fahrzeug anstecken und per Telegram Ziel-SoC bestätigen, oder:</div>';
    }

    // Add request button
    h += '<button class="seq-add-btn" onclick="openSeqModal()">\u2795 Ladewunsch hinzufügen</button>';

    // Schedule
    if (schedule.length > 0) {
        h += '<div style="font-size:0.85em;color:#888;margin-top:14px;margin-bottom:6px;">Ladeplan:</div>';
        h += '<div style="display:flex;flex-direction:column;gap:4px;">';
        for (var j = 0; j < schedule.length; j++) {
            var slot = schedule[j];
            var srcColor = slot.source === 'solar' ? '#ffdd00' :
                           slot.source === 'grid_cheap' ? '#00ff88' : '#ffaa00';
            var srcIcon = slot.source === 'solar' ? '\u2600\uFE0F' :
                          slot.source === 'grid_cheap' ? '\u26A1' : '\uD83D\uDD0C';
            var startH = slot.start ? new Date(slot.start).getHours() + ':00' : '--';
            var endH = slot.end ? new Date(slot.end).getHours() + ':00' : '--';
            h += '<div style="background:#16213e;border-left:3px solid ' + srcColor + ';border-radius:4px;padding:6px 10px;display:flex;justify-content:space-between;font-size:0.85em;">';
            h += '<span>' + srcIcon + ' <strong>' + escapeHtml(slot.vehicle) + '</strong> ' + startH + '–' + endH + '</span>';
            h += '<span style="color:' + srcColor + ';">' + slot.kwh.toFixed(1) + ' kWh @ ' + slot.price_ct.toFixed(1) + 'ct</span>';
            h += '</div>';
        }
        h += '</div>';
    }

    card.querySelector('.card-content') ? (card.querySelector('.card-content').innerHTML = h) : (card.innerHTML = '<h3 style="color:#00d4ff;margin-bottom:12px;">\uD83D\uDD0C Ladeplanung</h3>' + h);
}

// ---- Sequencer Modal ----
function openSeqModal() {
    var modal = $('seqModal');
    if (!modal) {
        // Create modal on the fly if not in dashboard.html
        var el = document.createElement('div');
        el.id = 'seqModal';
        el.style.cssText = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;justify-content:center;align-items:center;';
        el.innerHTML = '<div style="background:#16213e;border-radius:12px;padding:24px;width:340px;max-width:95vw;">' +
            '<h3 style="color:#00d4ff;margin-bottom:16px;">\u2795 Ladewunsch</h3>' +
            '<div style="margin-bottom:12px;"><label style="color:#888;font-size:0.85em;display:block;margin-bottom:4px;">Fahrzeug</label>' +
            '<input type="text" id="seqVehicleInput" placeholder="z.B. KIA_EV9" style="width:100%;padding:8px;background:#0f3460;border:1px solid #333;color:#eee;border-radius:4px;"></div>' +
            '<div style="margin-bottom:16px;"><label style="color:#888;font-size:0.85em;display:block;margin-bottom:4px;">Ziel-SoC (%)</label>' +
            '<input type="number" id="seqSocInput" min="10" max="100" value="80" style="width:100%;padding:8px;background:#0f3460;border:1px solid #333;color:#eee;border-radius:4px;"></div>' +
            '<div id="seqModalError" style="color:#ff4444;font-size:0.85em;display:none;margin-bottom:8px;"></div>' +
            '<div style="display:flex;gap:8px;">' +
            '<button onclick="submitSeqRequest()" style="flex:1;padding:10px;background:#00d4ff;color:#000;border:none;border-radius:6px;font-weight:bold;cursor:pointer;">Planen</button>' +
            '<button onclick="closeSeqModal()" style="flex:1;padding:10px;background:#333;color:#eee;border:none;border-radius:6px;cursor:pointer;">Abbrechen</button>' +
            '</div></div>';
        el.addEventListener('click', function(ev) { if (ev.target === el) closeSeqModal(); });
        document.body.appendChild(el);
    } else {
        modal.style.display = 'flex';
    }
}

function closeSeqModal() {
    var modal = $('seqModal');
    if (modal) modal.style.display = 'none';
}

async function submitSeqRequest() {
    var vehicle = ($('seqVehicleInput') || {}).value || '';
    var soc = parseInt(($('seqSocInput') || {}).value || '80');
    var errEl = $('seqModalError');

    if (!vehicle) {
        if (errEl) { errEl.textContent = 'Bitte Fahrzeug eingeben'; errEl.style.display = 'block'; }
        return;
    }
    if (isNaN(soc) || soc < 10 || soc > 100) {
        if (errEl) { errEl.textContent = 'SoC muss zwischen 10 und 100 liegen'; errEl.style.display = 'block'; }
        return;
    }

    try {
        var resp = await fetch('/sequencer/request', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicle: vehicle, target_soc: soc }),
        });
        var data = await resp.json();
        if (resp.ok) {
            closeSeqModal();
            refresh();
        } else {
            if (errEl) { errEl.textContent = data.error || 'Fehler'; errEl.style.display = 'block'; }
        }
    } catch(e) {
        if (errEl) { errEl.textContent = 'Netzwerkfehler: ' + e.message; errEl.style.display = 'block'; }
    }
}

async function cancelSeqRequest(vehicle) {
    try {
        await fetch('/sequencer/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicle: vehicle }),
        });
        refresh();
    } catch(e) { console.error('Seq cancel error:', e); }
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

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeModal(); closeSeqModal(); }
});

if ($('manualSocModal')) {
    $('manualSocModal').addEventListener('click', function(e) {
        if (e.target === $('manualSocModal')) closeModal();
    });
}

// ---- Decision Log ----
function renderDecisions(data) {
    var el = $('decisionLog');
    var countEl = $('decisionCount');
    if (!el || !data) return;

    var entries = data.entries || [];
    if (!entries.length) {
        el.innerHTML = '<div style="color:#888;padding:10px;">Noch keine Entscheidungen aufgezeichnet...</div>';
        return;
    }

    countEl.textContent = '(' + entries.length + ' Eintr\u00E4ge)';

    var categoryColors = {
        'observe': '#888',
        'plan': '#00d4ff',
        'action': '#00ff88',
        'warning': '#ffaa00',
        'rl': '#ff88ff',
        'sequencer': '#00ffcc',
    };

    var categoryLabels = {
        'observe': 'SEHE',
        'plan': 'PLANE',
        'action': 'AKTION',
        'warning': 'WARNUNG',
        'rl': 'RL',
        'sequencer': 'SEQ',
    };

    var html = '';
    var lastTime = '';
    for (var i = entries.length - 1; i >= 0; i--) {
        var e = entries[i];
        var color = categoryColors[e.category] || '#888';
        var label = categoryLabels[e.category] || e.category;
        var time = e.ts_local || '';

        if (lastTime && time !== lastTime && e.category === 'observe' && i < entries.length - 1) {
            html += '<div style="border-top:1px solid #333;margin:6px 0;"></div>';
        }

        html += '<div style="color:' + color + ';">';
        html += '<span style="color:#555;">' + time + '</span> ';
        html += '<span style="background:' + color + '22;padding:1px 5px;border-radius:3px;font-size:0.85em;">' + label + '</span> ';
        html += e.icon + ' ' + escapeHtml(e.text);
        if (e.details) {
            html += ' <span style="color:#555;font-size:0.85em;">(' + escapeHtml(e.details) + ')</span>';
        }
        html += '</div>';
        lastTime = time;
    }

    el.innerHTML = html;
}

function escapeHtml(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// =============================================================================
// v7: Forecast chart — 24h SVG visualization
// =============================================================================

/**
 * Render a 24h forecast chart as pure SVG into #forecastChart.
 * Shows consumption (blue #00d4ff) and PV (yellow #ffdd00) lines,
 * with price zone background colors and battery phase areas.
 */
function renderForecastChart(data) {
    var container = $('forecastChart');
    if (!container) return;

    var consumption96 = data.consumption_96 || data.consumption_forecast || null;
    var pv96 = data.pv_96 || data.pv_forecast || null;
    var priceZones96 = data.price_zones_96 || null;
    var batteryPhases96 = data.battery_phases_96 || null;

    // If no data at all, show placeholder
    if (!consumption96 && !pv96) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#555;font-size:0.9em;">Prognose wird geladen...</div>';
        return;
    }

    // --- Layout ---
    var marginL = 50, marginR = 20, marginT = 20, marginB = 30;
    var W = 960, H = 250;
    var plotW = W - marginL - marginR;
    var plotH = H - marginT - marginB;
    var slots = 96;
    var slotW = plotW / slots;

    // --- Y-axis: scale to max of both datasets ---
    var allVals = [];
    if (consumption96) allVals = allVals.concat(consumption96);
    if (pv96) {
        // pv96 may be in kW — convert to W if values are small (< 20 means kW)
        var pvMax = Math.max.apply(null, pv96.map(function(v) { return v || 0; }));
        var pvUnit = pvMax > 20 ? 1.0 : 1000.0;  // scale kW to W
        allVals = allVals.concat(pv96.map(function(v) { return (v || 0) * pvUnit; }));
    }
    var maxW = allVals.length > 0 ? Math.max.apply(null, allVals) : 3000;
    maxW = Math.max(maxW, 500);
    maxW = Math.ceil(maxW / 500) * 500;

    function xPos(i) { return marginL + i * slotW + slotW * 0.5; }
    function yPos(w) { return marginT + plotH - Math.min(1, Math.max(0, w / maxW)) * plotH; }

    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;">';

    // --- 1. Price zone background rectangles ---
    if (priceZones96) {
        for (var zi = 0; zi < priceZones96.length && zi < slots; zi++) {
            var zone = priceZones96[zi];
            var zx = marginL + zi * slotW;
            var zfill = '';
            if (zone === 'cheap') zfill = 'rgba(0,255,136,0.08)';
            else if (zone === 'expensive') zfill = 'rgba(255,68,68,0.06)';
            if (zfill) {
                s += '<rect x="' + zx.toFixed(1) + '" y="' + marginT + '" width="' + slotW.toFixed(1) + '" height="' + plotH + '" fill="' + zfill + '"/>';
            }
        }
    }

    // --- 2. Battery phase colored areas (placeholder for Phase 4) ---
    if (batteryPhases96) {
        for (var bi = 0; bi < batteryPhases96.length && bi < slots; bi++) {
            var phase = batteryPhases96[bi];
            var bx = marginL + bi * slotW;
            var bfill = '';
            if (phase === 'charge') bfill = 'rgba(0,255,136,0.15)';
            else if (phase === 'discharge') bfill = 'rgba(255,170,0,0.15)';
            if (bfill) {
                s += '<rect x="' + bx.toFixed(1) + '" y="' + marginT + '" width="' + slotW.toFixed(1) + '" height="' + plotH + '" fill="' + bfill + '"/>';
            }
        }
    }

    // --- 3. Grid lines ---
    var yStep = maxW <= 2000 ? 500 : (maxW <= 5000 ? 1000 : 2000);
    for (var yv = 0; yv <= maxW; yv += yStep) {
        var gy = yPos(yv);
        s += '<line x1="' + marginL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - marginR) + '" y2="' + gy.toFixed(1) + '" stroke="#2a2a4a" stroke-width="0.8" stroke-dasharray="3,3"/>';
        s += '<text x="' + (marginL - 4) + '" y="' + (gy + 3).toFixed(1) + '" fill="#555" font-size="9" text-anchor="end" font-family="sans-serif">' + (yv >= 1000 ? (yv/1000).toFixed(1)+'k' : yv) + '</text>';
    }
    s += '<text x="10" y="' + (marginT + plotH / 2) + '" fill="#555" font-size="8" text-anchor="middle" font-family="sans-serif" transform="rotate(-90,10,' + (marginT + plotH / 2) + ')">Watt</text>';

    // --- 4. PV forecast area + line (yellow #ffdd00) ---
    if (pv96) {
        var pvPath = '';
        var pvAreaPts = '';
        var pvScale = pvMax > 20 ? 1.0 : 1000.0;
        var firstPvX = xPos(0).toFixed(1);
        var lastPvX = xPos(slots - 1).toFixed(1);
        for (var pi = 0; pi < pv96.length && pi < slots; pi++) {
            var pvy = yPos((pv96[pi] || 0) * pvScale);
            var pvx = xPos(pi);
            pvPath += (pi === 0 ? 'M' : 'L') + pvx.toFixed(1) + ',' + pvy.toFixed(1) + ' ';
            pvAreaPts += (pi === 0 ? 'M' : 'L') + pvx.toFixed(1) + ',' + pvy.toFixed(1) + ' ';
        }
        var baseY = (marginT + plotH).toFixed(1);
        s += '<path d="' + pvAreaPts + 'L' + lastPvX + ',' + baseY + ' L' + firstPvX + ',' + baseY + ' Z" fill="rgba(255,221,0,0.1)"/>';
        s += '<path d="' + pvPath + '" fill="none" stroke="#ffdd00" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }

    // --- 5. Consumption forecast line (blue #00d4ff) ---
    if (consumption96) {
        var cPath = '';
        for (var ci = 0; ci < consumption96.length && ci < slots; ci++) {
            var cy = yPos(consumption96[ci] || 0);
            var cx = xPos(ci);
            cPath += (ci === 0 ? 'M' : 'L') + cx.toFixed(1) + ',' + cy.toFixed(1) + ' ';
        }
        s += '<path d="' + cPath + '" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }

    // --- 6. X-axis time labels (every 3 hours = 12 slots) ---
    var now = new Date();
    var nowHour = now.getHours();
    var nowMin = now.getMinutes();
    var startSlot = Math.floor((nowHour * 60 + nowMin) / 15);  // current 15-min slot of day
    for (var li = 0; li < slots; li += 12) {  // every 3 hours
        var absoluteSlot = (startSlot + li) % 96;
        var hour = Math.floor(absoluteSlot * 15 / 60);
        var lx = xPos(li);
        var ly = marginT + plotH + 14;
        var label = (hour < 10 ? '0' : '') + hour + ':00';
        s += '<text x="' + lx.toFixed(1) + '" y="' + ly + '" fill="#666" font-size="9" text-anchor="middle" font-family="sans-serif">' + label + '</text>';
    }

    // "Jetzt" marker at slot 0
    var nowX = xPos(0);
    s += '<line x1="' + nowX.toFixed(1) + '" y1="' + marginT + '" x2="' + nowX.toFixed(1) + '" y2="' + (marginT + plotH) + '" stroke="#00d4ff" stroke-width="1" stroke-dasharray="3,3" opacity="0.5"/>';
    s += '<text x="' + nowX.toFixed(1) + '" y="' + (marginT + plotH + 14) + '" fill="#00d4ff" font-size="8" text-anchor="middle" font-family="sans-serif">&#9650; jetzt</text>';

    s += '</svg>';
    container.innerHTML = s;
}

/**
 * Update forecaster maturity indicator and PV labels below the forecast chart.
 */
function updateForecastMeta(data) {
    var matEl = $('forecasterMaturity');
    var qualEl = $('pvQualityLabel');
    var corrEl = $('pvCorrectionLabel');

    if (matEl) {
        var days = data.forecaster_data_days || 0;
        var ready = data.forecaster_ready || false;
        if (ready) {
            matEl.textContent = 'Verbrauchsprognose: ' + days + '/14 Tage Daten';
            matEl.style.color = '#00ff88';
        } else {
            matEl.textContent = 'Verbrauchsprognose: ' + days + '/14 Tage Daten, Genauigkeit steigt noch';
            matEl.style.color = '#888';
        }
    }

    if (qualEl) {
        qualEl.textContent = data.pv_quality_label || '';
    }

    if (corrEl) {
        corrEl.textContent = data.pv_correction_label || '';
    }
}

/**
 * Show/hide the HA entity warning banner.
 */
function updateHaWarnings(warnings) {
    var banner = $('haWarningBanner');
    var text = $('haWarningText');
    if (!banner || !text) return;
    if (warnings && warnings.length > 0) {
        text.textContent = warnings.join(' | ');
        banner.style.display = 'flex';
    } else {
        banner.style.display = 'none';
    }
}

// =============================================================================
// v8: Dynamic Buffer — buffer section, chart, event log
// =============================================================================

/**
 * Update the dynamic buffer section from SSE/polled data.
 * buffer: object from data.buffer in SSE payload
 */
function updateBufferSection(buffer) {
    if (!buffer) return;

    var card = $('bufferCard');
    var banner = $('bufferObsBanner');
    if (card) card.style.display = 'block';

    // Observation banner
    if (banner) {
        if (buffer.mode === 'observation') {
            var days = buffer.days_remaining != null ? buffer.days_remaining : '?';
            var obsText = $('bufferObsText');
            if (obsText) obsText.textContent = 'Beobachtungsmodus \u2014 noch ' + days + ' Tage';
            banner.style.display = 'flex';
        } else {
            banner.style.display = 'none';
        }
    }

    // Confidence widget — update from last log entry
    var log = buffer.log_recent;
    var lastEntry = (log && log.length > 0) ? log[log.length - 1] : null;

    var confEl = $('confValue');
    var bufferValEl = $('bufferValue');
    var bufferModeEl = $('bufferMode');

    if (confEl) confEl.textContent = lastEntry ? lastEntry.pv_confidence.toFixed(0) : '--';
    if (bufferValEl) bufferValEl.textContent = buffer.current_buffer_pct != null ? buffer.current_buffer_pct : '--';
    if (bufferModeEl) bufferModeEl.textContent = buffer.mode === 'observation' ? 'Beobachtung' : 'Live';

    if (lastEntry) {
        var spreadEl = $('confSpread');
        var pv4hEl = $('confPv4h');
        var hourEl = $('confHour');
        if (spreadEl) spreadEl.textContent = lastEntry.price_spread_ct != null ? lastEntry.price_spread_ct.toFixed(1) : '--';
        if (pv4hEl) pv4hEl.textContent = lastEntry.expected_pv_kw != null ? lastEntry.expected_pv_kw.toFixed(1) : '--';
        if (hourEl) hourEl.textContent = lastEntry.hour_of_day != null ? lastEntry.hour_of_day + ':00' : '--';
    }

    if (log) {
        renderBufferChart(log);
        renderBufferLog(log);
    }
}

/**
 * Render the buffer history line chart as SVG into #bufferChart.
 * Shows new_buffer_pct over time with reference lines at 10% and 20%.
 * Observation-mode entries drawn with lower opacity/dashed style.
 */
function renderBufferChart(logEntries) {
    var svg = $('bufferChart');
    if (!svg || !logEntries || logEntries.length === 0) return;

    var W = 960, H = 160;
    var marginL = 36, marginR = 12, marginT = 10, marginB = 24;
    var plotW = W - marginL - marginR;
    var plotH = H - marginT - marginB;

    var n = logEntries.length;
    var minY = 0, maxY = 100;

    function xPos(i) { return marginL + (i / Math.max(1, n - 1)) * plotW; }
    function yPos(pct) { return marginT + plotH - (Math.min(maxY, Math.max(minY, pct)) / maxY) * plotH; }

    var s = '';

    // Y-axis grid lines and labels
    var yLabels = [0, 20, 50, 100];
    for (var li = 0; li < yLabels.length; li++) {
        var yv = yLabels[li];
        var gy = yPos(yv);
        s += '<line x1="' + marginL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - marginR) + '" y2="' + gy.toFixed(1) + '" stroke="#2a2a4a" stroke-width="0.8" stroke-dasharray="3,3"/>';
        s += '<text x="' + (marginL - 4) + '" y="' + (gy + 3).toFixed(1) + '" fill="#555" font-size="9" text-anchor="end" font-family="sans-serif">' + yv + '%</text>';
    }

    // Reference lines: 20% practical minimum (amber) and 10% hard floor (red)
    var y20 = yPos(20);
    var y10 = yPos(10);
    s += '<line x1="' + marginL + '" y1="' + y20.toFixed(1) + '" x2="' + (W - marginR) + '" y2="' + y20.toFixed(1) + '" stroke="#ffaa00" stroke-width="1" stroke-dasharray="4,3" opacity="0.7"/>';
    s += '<text x="' + (marginL + 4) + '" y="' + (y20 - 3).toFixed(1) + '" fill="#ffaa00" font-size="8" font-family="sans-serif">20% Min</text>';
    s += '<line x1="' + marginL + '" y1="' + y10.toFixed(1) + '" x2="' + (W - marginR) + '" y2="' + y10.toFixed(1) + '" stroke="#ff4444" stroke-width="1" stroke-dasharray="4,3" opacity="0.6"/>';
    s += '<text x="' + (marginL + 4) + '" y="' + (y10 - 3).toFixed(1) + '" fill="#ff4444" font-size="8" font-family="sans-serif">10% Boden</text>';

    // Split into segments by observation vs live mode for different styling
    // Build polyline segments
    var livePts = '';
    var obsPts = '';
    for (var i = 0; i < n; i++) {
        var e = logEntries[i];
        var x = xPos(i).toFixed(1);
        var y = yPos(e.new_buffer_pct).toFixed(1);
        var pt = x + ',' + y + ' ';
        if (e.mode === 'observation' || e.applied === false) {
            obsPts += (obsPts === '' ? 'M' : 'L') + pt;
            if (livePts !== '') {
                // Close live segment before starting obs
            }
        } else {
            livePts += (livePts === '' ? 'M' : 'L') + pt;
        }
    }

    // Draw observation line (dashed, lower opacity)
    if (obsPts) {
        s += '<path d="' + obsPts + '" fill="none" stroke="#22c55e" stroke-width="2" stroke-dasharray="5,3" stroke-linejoin="round" opacity="0.5"/>';
    }
    // Draw live line (solid)
    if (livePts) {
        s += '<path d="' + livePts + '" fill="none" stroke="#22c55e" stroke-width="2" stroke-linejoin="round" opacity="1"/>';
    }
    // If all same mode, draw single line for visual continuity
    if (!obsPts && !livePts) {
        var allPts = '';
        for (var j = 0; j < n; j++) {
            allPts += (j === 0 ? 'M' : 'L') + xPos(j).toFixed(1) + ',' + yPos(logEntries[j].new_buffer_pct).toFixed(1) + ' ';
        }
        s += '<path d="' + allPts + '" fill="none" stroke="#22c55e" stroke-width="2" stroke-linejoin="round" opacity="0.7"/>';
    }

    // X-axis labels: ~every 24 entries (6h at 15-min intervals)
    var labelStep = Math.max(1, Math.floor(n / 7));
    for (var xi = 0; xi < n; xi += labelStep) {
        var entry = logEntries[xi];
        var lx = xPos(xi).toFixed(1);
        var tsLabel = '';
        if (entry.ts) {
            try {
                var d = new Date(entry.ts);
                tsLabel = (d.getHours() < 10 ? '0' : '') + d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
            } catch(ex) { tsLabel = ''; }
        }
        if (tsLabel) {
            s += '<text x="' + lx + '" y="' + (marginT + plotH + 14) + '" fill="#666" font-size="8" text-anchor="middle" font-family="sans-serif">' + tsLabel + '</text>';
        }
    }

    svg.innerHTML = s;
}

/**
 * Render the buffer event log table into #bufferLogBody.
 * Most recent entries first, limit to last 50.
 * Observation-mode rows: muted/italic CSS class buffer-log-obs.
 */
function renderBufferLog(logEntries) {
    var tbody = $('bufferLogBody');
    if (!tbody || !logEntries) return;

    var entries = logEntries.slice(-50).reverse();  // most recent first
    var html = '';
    for (var i = 0; i < entries.length; i++) {
        var e = entries[i];
        var isObs = (e.mode === 'observation' || e.applied === false);
        var rowClass = isObs ? ' class="buffer-log-obs"' : '';

        // Time: HH:MM
        var timeStr = '--';
        if (e.ts) {
            try {
                var d = new Date(e.ts);
                timeStr = (d.getHours() < 10 ? '0' : '') + d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
            } catch(ex) { timeStr = '--'; }
        }

        var confidence = e.pv_confidence != null ? e.pv_confidence.toFixed(0) + '%' : '--';
        var spread = e.price_spread_ct != null ? e.price_spread_ct.toFixed(1) + 'ct' : '--';
        var bufferChange = e.old_buffer_pct + '%\u2192' + e.new_buffer_pct + '%';
        var reason = escapeHtml(e.reason || '');
        var statusText = isObs
            ? '<span style="color:#888;">Simulation</span>'
            : '<span style="color:#22c55e;">&#10003; Aktiv</span>';

        html += '<tr' + rowClass + '>';
        html += '<td>' + timeStr + '</td>';
        html += '<td>' + confidence + '</td>';
        html += '<td>' + spread + '</td>';
        html += '<td>' + bufferChange + '</td>';
        html += '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + reason + '">' + reason + '</td>';
        html += '<td>' + statusText + '</td>';
        html += '</tr>';
    }
    tbody.innerHTML = html;
}

/**
 * Toggle the collapsible confidence detail section.
 */
function toggleConfDetail() {
    var detail = $('confDetail');
    var summary = $('confSummary');
    if (!detail) return;
    var isVisible = detail.style.display !== 'none';
    detail.style.display = isVisible ? 'none' : 'block';
    // Update arrow icon
    if (summary) {
        var arrow = summary.querySelector('span:last-child');
        if (arrow) arrow.textContent = isVisible ? '\u25BC Details' : '\u25B2 Details';
    }
}

/**
 * Activate live mode early via POST /buffer/activate-live.
 */
async function activateBufferLive() {
    if (!confirm('Dynamischen Puffer jetzt live schalten? Die Beobachtungsphase wird beendet.')) return;
    try {
        var resp = await fetch('/buffer/activate-live', { method: 'POST' });
        var data = await resp.json();
        if (resp.ok) {
            var banner = $('bufferObsBanner');
            if (banner) banner.style.display = 'none';
            var modeEl = $('bufferMode');
            if (modeEl) modeEl.textContent = 'Live';
        } else {
            alert('Fehler: ' + (data.error || 'Unbekannter Fehler'));
        }
    } catch (e) {
        alert('Netzwerkfehler: ' + e.message);
    }
}

/**
 * Extend observation period by 14 days via POST /buffer/extend-obs.
 */
async function extendBufferObs() {
    try {
        var resp = await fetch('/buffer/extend-obs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: 14 }),
        });
        var data = await resp.json();
        if (resp.ok) {
            var obsText = $('bufferObsText');
            if (obsText) obsText.textContent = 'Beobachtungsmodus \u2014 um 14 Tage verl\u00E4ngert';
        } else {
            alert('Fehler: ' + (data.error || 'Unbekannter Fehler'));
        }
    } catch (e) {
        alert('Netzwerkfehler: ' + e.message);
    }
}

// =============================================================================
// v6: SSE — Live state push
// =============================================================================

/**
 * Format a duration in milliseconds as a human-readable "vor X Min" string.
 */
function formatAge(ms) {
    var min = Math.floor(ms / 60000);
    if (min < 1) return 'gerade eben';
    if (min < 60) return 'vor ' + min + ' Min';
    var h = Math.floor(min / 60);
    var m = min % 60;
    return 'vor ' + h + 'h ' + m + 'min';
}

/**
 * Flash a CSS highlight on an element to signal a value change.
 * Removes the class after 1.5 s so the animation can replay on next update.
 */
function flashUpdate(el) {
    if (!el) return;
    el.classList.remove('sse-updated');
    // Force reflow so the animation restarts even if the class was just removed
    void el.offsetWidth;
    el.classList.add('sse-updated');
    setTimeout(function() { el.classList.remove('sse-updated'); }, 1600);
}

/**
 * Update the "vor X Min" age labels for all key status cards.
 * Called every minute by setInterval.
 */
function updateAgeLabels() {
    if (!_sseLastUpdate) return;
    var ms = Date.now() - new Date(_sseLastUpdate).getTime();
    var text = formatAge(ms);
    var ids = ['priceAge', 'batteryAge', 'pvAge', 'homeAge'];
    for (var i = 0; i < ids.length; i++) {
        var el = $(ids[i]);
        if (el) el.textContent = text;
    }
}

/**
 * Apply an SSE state message to the dashboard status cards.
 * Only updates fields present in the message; falls back to polling for
 * complex sections (chart, slots, RL, etc.).
 */
function applySSEUpdate(msg) {
    var s = msg.state;
    if (!s) return;

    _sseLastUpdate = msg.last_update;

    // --- Price ---
    var priceEl = $('priceVal');
    if (priceEl && s.current_price != null) {
        var priceCt = s.current_price * 100;
        var newPriceText = priceCt.toFixed(1) + ' ct';
        if (priceEl.textContent !== newPriceText) {
            priceEl.textContent = newPriceText;
            priceEl.style.color = priceColor(priceCt);
            flashUpdate(priceEl);
        }
    }

    // --- Battery SoC ---
    var batEl = $('batteryVal');
    if (batEl && s.battery_soc != null) {
        var newBatText = s.battery_soc.toFixed(0) + '%';
        if (batEl.textContent !== newBatText) {
            batEl.textContent = newBatText;
            batEl.style.color = socColor(s.battery_soc);
            flashUpdate(batEl);
        }
    }

    // --- PV power ---
    var pvEl = $('pvVal');
    if (pvEl && s.pv_power != null) {
        var newPvText = (s.pv_power / 1000).toFixed(1) + ' kW';
        if (pvEl.textContent !== newPvText) {
            pvEl.textContent = newPvText;
            flashUpdate(pvEl);
        }
    }

    // --- Home power ---
    var homeEl = $('homeVal');
    if (homeEl && s.home_power != null) {
        var newHomeText = (s.home_power / 1000).toFixed(1) + ' kW';
        if (homeEl.textContent !== newHomeText) {
            homeEl.textContent = newHomeText;
            flashUpdate(homeEl);
        }
    }

    // Update age labels immediately after new data arrives
    updateAgeLabels();

    // v7: Live forecast chart update via SSE
    if (msg.forecast) {
        renderForecastChart(msg.forecast);
        updateForecastMeta(msg.forecast);
        updateHaWarnings(msg.forecast.ha_warnings || []);
    }

    // v8: Dynamic buffer section update via SSE
    if (msg.buffer) {
        updateBufferSection(msg.buffer);
    }
}

/**
 * Set SSE connection indicator state.
 * state: 'connected' | 'error' | 'disconnected'
 */
function setSseIndicator(state) {
    var dot = $('sseDot');
    var label = $('sseStatus');
    if (!dot || !label) return;
    dot.className = 'sse-dot';
    if (state === 'connected') {
        dot.classList.add('connected');
        label.textContent = 'Live';
        label.style.color = '#00ff88';
    } else if (state === 'error') {
        dot.classList.add('error');
        label.textContent = 'Getrennt';
        label.style.color = '#ff4444';
    } else {
        label.textContent = 'Verbinde...';
        label.style.color = '#555';
    }
}

/**
 * Start SSE connection to /events.
 * EventSource reconnects automatically on error; we only update the indicator.
 */
function startSSE() {
    if (_sseSource) {
        _sseSource.close();
    }
    _sseSource = new EventSource('/events');

    _sseSource.onopen = function() {
        setSseIndicator('connected');
    };

    _sseSource.onmessage = function(event) {
        try {
            var msg = JSON.parse(event.data);
            applySSEUpdate(msg);
        } catch(e) {
            console.warn('SSE parse error:', e);
        }
    };

    _sseSource.onerror = function() {
        setSseIndicator('error');
        // EventSource will reconnect automatically (browser built-in)
    };
}

// =============================================================================
// Phase 6: Tab navigation and Plan Gantt chart
// =============================================================================

/**
 * Switch between tabs: main (Status), plan (Plan-Gantt), history (Historie).
 * Overrides the inline fallback in dashboard.html with full implementation
 * that triggers data fetching on tab activation.
 */
function switchTab(name) {
    var tabs = ['main', 'plan', 'history'];
    for (var t = 0; t < tabs.length; t++) {
        var el = document.getElementById('tab-' + tabs[t]);
        if (el) el.style.display = (tabs[t] === name ? '' : 'none');
    }
    document.querySelectorAll('.tab-btn').forEach(function(btn, idx) {
        btn.classList.toggle('active', tabs[idx] === name);
    });
    if (name === 'plan') {
        fetchAndRenderPlan();
    }
    if (name === 'history') {
        fetchAndRenderHistory();
    }
}

/**
 * Stub for Plan 03 — Historie tab data loading.
 */
function fetchAndRenderHistory() { /* Plan 03 */ }

/**
 * Render an SVG Gantt chart of 96 dispatch slots into #planChartWrap.
 * Shows color-coded bars (green=bat_charge, orange=bat_discharge, blue=ev_charge,
 * gold=pv background), a red price polyline overlay, time axis labels,
 * hover tooltips (explanation_short), and click-to-expand detail (explanation_long).
 *
 * @param {Array} slots     Array of DispatchSlot objects from /plan
 * @param {string} computedAt ISO timestamp when plan was computed
 */
function renderPlanGantt(slots, computedAt) {
    var wrap = $('planChartWrap');
    if (!wrap || !slots || !slots.length) return;

    // --- Layout ---
    var W = 960, H = 250;
    var marginL = 50, marginR = 50, marginT = 25, marginB = 35;
    var plotW = W - marginL - marginR;
    var plotH = H - marginT - marginB;
    var n = slots.length;
    var slotW = plotW / n;

    // --- Scale: maxPower across all kW values ---
    var maxPower = 0.1;
    for (var i = 0; i < n; i++) {
        var sl = slots[i];
        if ((sl.bat_charge_kw || 0) > maxPower) maxPower = sl.bat_charge_kw;
        if ((sl.bat_discharge_kw || 0) > maxPower) maxPower = sl.bat_discharge_kw;
        if ((sl.ev_charge_kw || 0) > maxPower) maxPower = sl.ev_charge_kw;
    }
    maxPower = Math.max(maxPower, 1.0);

    // --- Scale: price ---
    var maxPrice = 0.1;
    for (var pi = 0; pi < n; pi++) {
        if ((slots[pi].price_ct || 0) > maxPrice) maxPrice = slots[pi].price_ct;
    }
    maxPrice = Math.max(maxPrice, 1.0);

    var s = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';

    // --- PV background bars (drawn FIRST so action bars overlay) ---
    for (var vi = 0; vi < n; vi++) {
        var pvKw = slots[vi].pv_kw || 0;
        if (pvKw > 0.1) {
            var pvH = (pvKw / maxPower) * plotH;
            var pvX = marginL + vi * slotW;
            var pvY = marginT + plotH - pvH;
            s += '<rect x="' + pvX.toFixed(1) + '" y="' + pvY.toFixed(1) + '" width="' + slotW.toFixed(1) + '" height="' + pvH.toFixed(1) + '" fill="#ffd700" opacity="0.2"/>';
        }
    }

    // --- Action bars (bat charge, bat discharge, ev charge) ---
    for (var bi = 0; bi < n; bi++) {
        var slot = slots[bi];
        var bx = marginL + bi * slotW;
        var stackY = marginT + plotH; // starting y from bottom, stacking upward

        // Battery charge (green)
        var bcKw = slot.bat_charge_kw || 0;
        if (bcKw > 0.1) {
            var bcH = (bcKw / maxPower) * plotH;
            stackY -= bcH;
            s += '<rect x="' + bx.toFixed(1) + '" y="' + stackY.toFixed(1) + '" width="' + slotW.toFixed(1) + '" height="' + bcH.toFixed(1) + '" fill="#00ff88" opacity="0.85" class="plan-slot" data-idx="' + bi + '" style="cursor:pointer;"/>';
        }

        // Battery discharge (orange) — stacks above battery charge
        var bdKw = slot.bat_discharge_kw || 0;
        if (bdKw > 0.1) {
            var bdH = (bdKw / maxPower) * plotH;
            stackY -= bdH;
            s += '<rect x="' + bx.toFixed(1) + '" y="' + stackY.toFixed(1) + '" width="' + slotW.toFixed(1) + '" height="' + bdH.toFixed(1) + '" fill="#ff8800" opacity="0.85" class="plan-slot" data-idx="' + bi + '" style="cursor:pointer;"/>';
        }

        // EV charge (blue) — stacks above battery
        var evKw = slot.ev_charge_kw || 0;
        if (evKw > 0.1) {
            var evH = (evKw / maxPower) * plotH;
            stackY -= evH;
            s += '<rect x="' + bx.toFixed(1) + '" y="' + stackY.toFixed(1) + '" width="' + slotW.toFixed(1) + '" height="' + evH.toFixed(1) + '" fill="#4488ff" opacity="0.85" class="plan-slot" data-idx="' + bi + '" style="cursor:pointer;"/>';
        }

        // If no action bar was drawn for this slot, add transparent hit-area for tooltip
        if (bcKw <= 0.1 && bdKw <= 0.1 && evKw <= 0.1) {
            s += '<rect x="' + bx.toFixed(1) + '" y="' + marginT + '" width="' + slotW.toFixed(1) + '" height="' + plotH + '" fill="transparent" class="plan-slot" data-idx="' + bi + '" style="cursor:pointer;"/>';
        }
    }

    // --- Price polyline overlay ---
    var pricePts = '';
    for (var ri = 0; ri < n; ri++) {
        var rpx = marginL + ri * slotW + slotW * 0.5;
        var priceY = marginT + plotH - ((slots[ri].price_ct || 0) / maxPrice) * plotH;
        pricePts += (ri === 0 ? 'M' : 'L') + rpx.toFixed(1) + ',' + priceY.toFixed(1) + ' ';
    }
    s += '<path d="' + pricePts + '" fill="none" stroke="#ff4444" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.9" pointer-events="none"/>';

    // --- Y-axis labels (left: power in kW) ---
    s += '<text x="' + (marginL - 6) + '" y="' + (marginT + 4) + '" fill="#888" font-size="9" text-anchor="end" font-family="sans-serif">' + maxPower.toFixed(1) + 'kW</text>';
    s += '<text x="' + (marginL - 6) + '" y="' + (marginT + plotH) + '" fill="#888" font-size="9" text-anchor="end" font-family="sans-serif">0</text>';
    s += '<text x="8" y="' + (marginT + plotH / 2) + '" fill="#888" font-size="8" text-anchor="middle" font-family="sans-serif" transform="rotate(-90,8,' + (marginT + plotH / 2) + ')">kW</text>';

    // --- Y-axis labels (right: price in ct) ---
    s += '<text x="' + (W - marginR + 4) + '" y="' + (marginT + 4) + '" fill="#ff4444" font-size="9" text-anchor="start" font-family="sans-serif">' + maxPrice.toFixed(0) + 'ct</text>';
    s += '<text x="' + (W - marginR + 4) + '" y="' + (marginT + plotH) + '" fill="#ff4444" font-size="9" text-anchor="start" font-family="sans-serif">0</text>';
    s += '<text x="' + (W - 8) + '" y="' + (marginT + plotH / 2) + '" fill="#ff4444" font-size="8" text-anchor="middle" font-family="sans-serif" transform="rotate(90,' + (W - 8) + ',' + (marginT + plotH / 2) + ')">ct/kWh</text>';

    // --- X-axis time labels (every 8 slots = every 2 hours) ---
    for (var ti = 0; ti < n; ti += 8) {
        var tslot = slots[ti];
        var timeLabel = '';
        if (tslot && tslot.start_iso) {
            try {
                var td = new Date(tslot.start_iso);
                var thh = td.getHours();
                var tmm = td.getMinutes();
                timeLabel = (thh < 10 ? '0' : '') + thh + ':' + (tmm < 10 ? '0' : '') + tmm;
            } catch(ex) { timeLabel = ''; }
        }
        if (timeLabel) {
            var tlx = marginL + ti * slotW + slotW * 0.5;
            var tly = marginT + plotH + 14;
            s += '<text x="' + tlx.toFixed(1) + '" y="' + tly + '" fill="#888" font-size="9" text-anchor="middle" font-family="sans-serif">' + timeLabel + '</text>';
        }
    }

    // --- Computed-at label ---
    if (computedAt) {
        try {
            var ca = new Date(computedAt);
            var caLabel = 'Plan: ' + (ca.getHours() < 10 ? '0' : '') + ca.getHours() + ':' + (ca.getMinutes() < 10 ? '0' : '') + ca.getMinutes();
            s += '<text x="' + (W - marginR) + '" y="' + (marginT - 8) + '" fill="#555" font-size="8" text-anchor="end" font-family="sans-serif">' + caLabel + '</text>';
        } catch(ex) {}
    }

    // --- Legend ---
    var legY = H - 8;
    var legItems = [
        { color: '#00ff88', label: 'Batterie laden' },
        { color: '#ff8800', label: 'Batterie entladen' },
        { color: '#4488ff', label: 'EV laden' },
        { color: '#ffd700', label: 'PV-Erzeugung' },
        { color: '#ff4444', label: 'Preis', isLine: true },
    ];
    var legX = marginL;
    for (var lgi = 0; lgi < legItems.length; lgi++) {
        var leg = legItems[lgi];
        if (leg.isLine) {
            s += '<line x1="' + legX + '" y1="' + (legY - 4) + '" x2="' + (legX + 12) + '" y2="' + (legY - 4) + '" stroke="' + leg.color + '" stroke-width="2"/>';
        } else {
            s += '<rect x="' + legX + '" y="' + (legY - 8) + '" width="12" height="8" fill="' + leg.color + '" opacity="0.85"/>';
        }
        s += '<text x="' + (legX + 14) + '" y="' + legY + '" fill="#888" font-size="9" font-family="sans-serif">' + leg.label + '</text>';
        legX += leg.label.length * 5.5 + 24;
    }

    s += '</svg>';

    // Inject SVG into DOM
    wrap.innerHTML = s;

    // --- Tooltip (hover) ---
    var tooltip = document.createElement('div');
    tooltip.style.cssText = 'position:absolute;background:#0f3460;border:1px solid #555;border-radius:4px;padding:6px 10px;font-size:0.82em;color:#eee;pointer-events:none;z-index:100;max-width:280px;display:none;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
    wrap.style.position = 'relative';
    wrap.appendChild(tooltip);

    var planSlotEls = wrap.querySelectorAll('.plan-slot');
    for (var psi = 0; psi < planSlotEls.length; psi++) {
        planSlotEls[psi].addEventListener('mouseenter', function() {
            var idx = parseInt(this.getAttribute('data-idx'));
            var pslot = window._planSlots && window._planSlots[idx];
            if (!pslot) return;
            var short = pslot.explanation_short || '';
            var ttime = '';
            if (pslot.start_iso) {
                try { ttime = new Date(pslot.start_iso).getHours() + ':00'; } catch(ex) {}
            }
            tooltip.innerHTML = '<div style="color:#00d4ff;font-size:0.9em;margin-bottom:4px;">' + ttime + '</div>' + escapeHtml(short);
            tooltip.style.display = 'block';
        });
        planSlotEls[psi].addEventListener('mousemove', function(e) {
            var rect = wrap.getBoundingClientRect();
            var x = e.clientX - rect.left + 12;
            var y = e.clientY - rect.top - 12;
            if (x + 290 > rect.width) x = x - 302;
            if (y < 0) y = 0;
            tooltip.style.left = x + 'px';
            tooltip.style.top = y + 'px';
        });
        planSlotEls[psi].addEventListener('mouseleave', function() {
            tooltip.style.display = 'none';
        });
        planSlotEls[psi].addEventListener('click', function() {
            var idx = parseInt(this.getAttribute('data-idx'));
            var cslot = window._planSlots && window._planSlots[idx];
            if (!cslot) return;
            var detail = $('planDetail');
            if (!detail) return;

            var ctimeStr = '';
            if (cslot.start_iso) {
                try {
                    var cd = new Date(cslot.start_iso);
                    ctimeStr = (cd.getHours() < 10 ? '0' : '') + cd.getHours() + ':' + (cd.getMinutes() < 10 ? '0' : '') + cd.getMinutes();
                } catch(ex) { ctimeStr = cslot.start_iso; }
            }

            var actionLabel = '';
            if ((cslot.bat_charge_kw || 0) > 0.1) actionLabel = '<span style="color:#00ff88;">Batterie laden (' + (cslot.bat_charge_kw || 0).toFixed(1) + ' kW)</span>';
            else if ((cslot.bat_discharge_kw || 0) > 0.1) actionLabel = '<span style="color:#ff8800;">Batterie entladen (' + (cslot.bat_discharge_kw || 0).toFixed(1) + ' kW)</span>';
            else if ((cslot.ev_charge_kw || 0) > 0.1) actionLabel = '<span style="color:#4488ff;">EV laden (' + (cslot.ev_charge_kw || 0).toFixed(1) + ' kW)</span>';
            else actionLabel = '<span style="color:#888;">Halten / Idle</span>';

            var dh = '<div style="background:#16213e;border-radius:8px;padding:14px;border-left:3px solid #00d4ff;">';
            dh += '<div style="font-size:1.05em;font-weight:bold;color:#00d4ff;margin-bottom:10px;">' + ctimeStr + ' \u2014 ' + actionLabel + '</div>';
            dh += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:0.9em;margin-bottom:12px;">';
            dh += '<div style="background:#0f3460;padding:8px;border-radius:6px;"><div style="color:#888;font-size:0.8em;">Strompreis</div><div style="color:#ff4444;">' + (cslot.price_ct || 0).toFixed(1) + ' ct/kWh</div></div>';
            if ((cslot.pv_kw || 0) > 0.1) {
                dh += '<div style="background:#0f3460;padding:8px;border-radius:6px;"><div style="color:#888;font-size:0.8em;">PV-Erzeugung</div><div style="color:#ffd700;">' + (cslot.pv_kw || 0).toFixed(1) + ' kW</div></div>';
            }
            if (cslot.bat_soc_pct != null) {
                dh += '<div style="background:#0f3460;padding:8px;border-radius:6px;"><div style="color:#888;font-size:0.8em;">Batterie SoC</div><div style="color:#00ff88;">' + (cslot.bat_soc_pct || 0).toFixed(0) + '%</div></div>';
            }
            if (cslot.departure_hours != null) {
                dh += '<div style="background:#0f3460;padding:8px;border-radius:6px;"><div style="color:#888;font-size:0.8em;">Bis Abfahrt</div><div style="color:#00d4ff;">' + (cslot.departure_hours || 0).toFixed(1) + ' h</div></div>';
            }
            dh += '</div>';
            dh += '<div style="font-size:0.92em;line-height:1.6;color:#ccc;">' + escapeHtml(cslot.explanation_long || cslot.explanation_short || '') + '</div>';
            dh += '</div>';

            detail.innerHTML = dh;
            detail.style.display = '';
            detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    }
}

/**
 * Fetch /plan and render the SVG Gantt chart if data is available.
 * Shows planNoData element if plan is not available.
 */
function fetchAndRenderPlan() {
    fetchJSON('/plan').then(function(data) {
        if (!data || !data.available || !data.slots || !data.slots.length) {
            var noData = $('planNoData');
            var chartWrap = $('planChartWrap');
            if (noData) noData.style.display = '';
            if (chartWrap) chartWrap.style.display = 'none';
            return;
        }
        var noData = $('planNoData');
        var chartWrap = $('planChartWrap');
        if (noData) noData.style.display = 'none';
        if (chartWrap) chartWrap.style.display = '';
        window._planSlots = data.slots;
        renderPlanGantt(data.slots, data.computed_at);
    });
}

// =============================================================================
// Kick off
// =============================================================================

refresh();
setInterval(refresh, 60000);

// v7: Initial forecast chart load
fetchJSON('/forecast').then(function(data) {
    if (data) {
        renderForecastChart(data);
        updateForecastMeta(data);
        updateHaWarnings(data.ha_warnings || []);
    }
});

// v6: Start SSE for live updates between polls
if (typeof EventSource !== 'undefined') {
    startSSE();
    // Update age labels every 60 seconds even when no new data arrives
    setInterval(updateAgeLabels, 60000);
} else {
    setSseIndicator('error');
}
