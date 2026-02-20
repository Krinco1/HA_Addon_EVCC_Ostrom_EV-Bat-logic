/**
 * EVCC-Smartload Dashboard v5.0
 *
 * Fetches /status, /slots, /vehicles, /strategy, /chart-data,
 *         /rl-devices, /decisions, /sequencer
 * Auto-refreshes every 60 seconds.
 */

let currentVehicleId = '';
let currentSeqVehicle = '';

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
    var rows = [
        ['Batterie max', (cfg.battery_max_ct || 0) + 'ct'],
        ['EV max', (cfg.ev_max_ct || 0) + 'ct'],
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

refresh();
setInterval(refresh, 60000);
