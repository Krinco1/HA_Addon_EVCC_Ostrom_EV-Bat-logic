/**
 * EVCC-Smartload Dashboard v4.3.7
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
    // Check if we have solar data
    var hasSolar = data.has_solar_forecast || false;
    var maxSolar = hasSolar ? Math.max.apply(null, prices.map(function(p){ return p.solar_kw || 0; }).concat([1])) : 0;

    for (var i = 0; i < prices.length; i++) {
        var p = prices[i];
        var h = Math.max(2, (p.price_ct / maxPrice) * 120);
        var col = priceColor(p.price_ct);
        var cls = p.is_now ? ' now' : '';
        var solarKw = p.solar_kw || 0;
        var title = p.hour + ': ' + p.price_ct.toFixed(1) + 'ct';
        if (solarKw > 0) title += ' | \u2600\uFE0F ' + solarKw.toFixed(1) + 'kW';

        html += '<div class="chart-bar' + cls + '" style="height:' + h + 'px;background:' + col + ';" title="' + title + '">';
        html += '<span class="bar-value" style="color:' + col + ';">' + p.price_ct.toFixed(1) + '</span>';
        html += '<span class="bar-label">' + p.hour + '</span>';
        html += '</div>';
    }
    $('chartBars').innerHTML = html;

    // Limit lines + solar cleanup
    var wrap = $('chartWrap');
    var existing = wrap.querySelectorAll('.chart-limit,.solar-summary,.solar-overlay');
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

    // Solar forecast: SVG line + area overlay
    if (hasSolar && maxSolar > 0.1) {
        var bars = $('chartBars');
        var barEls = bars.querySelectorAll('.chart-bar');
        if (barEls.length > 0) {
            var svgNS = 'http://www.w3.org/2000/svg';
            var svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('class', 'solar-overlay');
            svg.style.cssText = 'position:absolute;left:0;right:0;bottom:22px;height:120px;pointer-events:none;z-index:5;overflow:visible;';

            var points = [];
            for (var si = 0; si < prices.length; si++) {
                var skw = prices[si].solar_kw || 0;
                var barEl = barEls[si];
                if (!barEl) continue;
                var xCenter = barEl.offsetLeft + barEl.offsetWidth / 2;
                var yVal = 120 - (skw / maxSolar) * 105;
                points.push({x: xCenter, y: yVal, kw: skw});
            }

            if (points.length > 1) {
                // Filled area (subtle)
                var areaPts = points.map(function(pt){return pt.x+','+pt.y;}).join(' ');
                areaPts += ' ' + points[points.length-1].x + ',120 ' + points[0].x + ',120';
                var area = document.createElementNS(svgNS, 'polygon');
                area.setAttribute('points', areaPts);
                area.setAttribute('fill', 'rgba(255,221,0,0.10)');
                svg.appendChild(area);

                // Line (clear yellow)
                var linePts = points.map(function(pt){return pt.x+','+pt.y;}).join(' ');
                var line = document.createElementNS(svgNS, 'polyline');
                line.setAttribute('points', linePts);
                line.setAttribute('fill', 'none');
                line.setAttribute('stroke', '#ffdd00');
                line.setAttribute('stroke-width', '2.5');
                line.setAttribute('stroke-linejoin', 'round');
                line.setAttribute('stroke-linecap', 'round');
                svg.appendChild(line);

                // Dots at each data point
                for (var di = 0; di < points.length; di++) {
                    if (points[di].kw > 0.1) {
                        var dot = document.createElementNS(svgNS, 'circle');
                        dot.setAttribute('cx', points[di].x);
                        dot.setAttribute('cy', points[di].y);
                        dot.setAttribute('r', '3');
                        dot.setAttribute('fill', '#ffdd00');
                        dot.setAttribute('stroke', '#1a1a2e');
                        dot.setAttribute('stroke-width', '1.5');
                        svg.appendChild(dot);
                    }
                }

                // Max kW label
                var maxLabel = document.createElementNS(svgNS, 'text');
                maxLabel.setAttribute('x', points[points.length-1].x - 5);
                maxLabel.setAttribute('y', '12');
                maxLabel.setAttribute('fill', '#ffdd00');
                maxLabel.setAttribute('font-size', '10');
                maxLabel.setAttribute('text-anchor', 'end');
                maxLabel.setAttribute('font-family', '-apple-system, sans-serif');
                maxLabel.textContent = '\u2600 max ' + maxSolar.toFixed(1) + 'kW';
                svg.appendChild(maxLabel);
            }

            wrap.appendChild(svg);
        }
    }

    // Solar summary line below chart
    var pvKw = data.pv_now_kw || 0;
    var summaryEl = document.createElement('div');
    summaryEl.className = 'solar-summary';
    summaryEl.style.cssText = 'display:flex;justify-content:space-between;font-size:0.85em;margin-top:4px;flex-wrap:wrap;gap:8px;';
    var summaryHtml = '';
    if (pvKw > 0) summaryHtml += '<span style="color:#ffdd00;">\u2600\uFE0F Aktuell: ' + pvKw.toFixed(1) + ' kW PV</span>';
    if (hasSolar) {
        var totalKwh = data.solar_total_kwh || 0;
        summaryHtml += '<span style="color:#ffdd00;">\u{1F4C8} Prognose: ' + totalKwh.toFixed(0) + ' kWh heute</span>';
    }
    if (summaryHtml) {
        summaryEl.innerHTML = summaryHtml;
        wrap.appendChild(summaryEl);
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

    // Battery-to-EV optimization card
    renderBatToEv(slots.battery_to_ev);
}

function renderBatToEv(b2e) {
    var card = $('batToEvCard');
    var content = $('batToEvContent');
    if (!card || !content || !b2e) { if (card) card.style.display = 'none'; return; }
    if (b2e.ev_need_kwh < 0.5) { card.style.display = 'none'; return; }

    card.style.display = '';
    var profitable = b2e.is_profitable;
    var borderColor = profitable ? '#00ff88' : '#555';
    card.style.borderLeft = '3px solid ' + borderColor;

    var h = '<div style="margin-bottom:10px;font-size:1.05em;">' + b2e.recommendation + '</div>';

    h += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:0.9em;">';
    h += '<div style="background:#0f3460;padding:8px;border-radius:6px;">';
    h += '<div style="color:#888;font-size:0.8em;">Batterie verfügbar</div>';
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
    h += '<div style="color:#888;font-size:0.75em;">Ø nächste 6h: ' + b2e.avg_upcoming_ct + 'ct</div></div>';
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

    // Dynamic discharge limits
    var dl = b2e.dynamic_limits;
    if (dl && b2e.dynamic_limit_enabled) {
        h += '<div style="margin-top:12px;padding:10px;background:#0f3460;border-radius:6px;">';
        h += '<div style="font-size:0.9em;font-weight:bold;margin-bottom:8px;color:#00d4ff;">\u{1F3AF} Dynamische Entladegrenze</div>';

        // Visual battery bar with zones
        h += '<div style="position:relative;height:28px;background:#1a1a2e;border-radius:14px;overflow:hidden;margin-bottom:8px;border:1px solid #333;">';
        // Priority zone (red) - 0 to prioritySoc
        h += '<div style="position:absolute;left:0;width:' + dl.priority_soc + '%;height:100%;background:rgba(255,68,68,0.3);"></div>';
        // Buffer zone (yellow) - prioritySoc to bufferSoc
        var bufferWidth = Math.max(0, dl.buffer_soc - dl.priority_soc);
        h += '<div style="position:absolute;left:' + dl.priority_soc + '%;width:' + bufferWidth + '%;height:100%;background:rgba(255,170,0,0.2);"></div>';
        // Available for EV zone (green) - bufferSoc to 100
        var evWidth = 100 - dl.buffer_soc;
        h += '<div style="position:absolute;left:' + dl.buffer_soc + '%;width:' + evWidth + '%;height:100%;background:rgba(0,255,136,0.15);"></div>';
        // Labels
        h += '<div style="position:absolute;left:' + (dl.priority_soc - 1) + '%;top:0;bottom:0;border-right:2px solid #ff4444;"></div>';
        h += '<div style="position:absolute;left:' + (dl.buffer_soc - 1) + '%;top:0;bottom:0;border-right:2px solid #00ff88;"></div>';
        h += '<div style="position:absolute;left:4px;top:50%;transform:translateY(-50%);font-size:0.7em;color:#ff8888;">\u{1F6E1} ' + dl.priority_soc + '%</div>';
        h += '<div style="position:absolute;right:4px;top:50%;transform:translateY(-50%);font-size:0.7em;color:#00ff88;">\u{1F50B}\u2192\u{1F697} ab ' + dl.buffer_soc + '%</div>';
        h += '</div>';

        // Refill reasoning
        h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.8em;">';
        if (dl.solar_refill_pct > 1) {
            h += '<div style="color:#ffdd00;">\u2600\uFE0F Solar: +' + dl.solar_refill_pct + '% (' + dl.solar_surplus_kwh + ' kWh)</div>';
        }
        if (dl.grid_refill_pct > 1) {
            h += '<div style="color:#00d4ff;">\u26A1 G\u00FCnstig-Netz: +' + dl.grid_refill_pct + '% (' + dl.cheap_hours + 'h)</div>';
        }
        h += '<div style="color:#ff88ff;">\u{1F697} EV braucht: ' + dl.ev_need_pct + '% (inkl. Verluste)</div>';
        h += '<div style="color:#888;">\u{1F6E1} Untergrenze: ' + dl.floor_soc + '%</div>';
        h += '</div>';

        h += '</div>';
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
        ['Roundtrip-Eff.', ((cfg.battery_charge_eff || 0.92) * (cfg.battery_discharge_eff || 0.92) * 100).toFixed(1) + '%'],
        ['Bat\u2192EV Min-Vorteil', (cfg.bat_to_ev_min_ct || 3) + 'ct'],
        ['Dynamische Grenze', cfg.bat_to_ev_dynamic ? '\u2705 aktiv' : '\u274C aus'],
        ['Entlade-Untergrenze', (cfg.bat_to_ev_floor || 20) + '%'],
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
