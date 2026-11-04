/* Provenance GUI front end. Plain JS, no build step. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const S = { sid: null, session: null, settings: null, bbox: null, result: null, sel: 0,
  which: 'orig', view: null, adsbPath: null, demPath: null, author: null };

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
  return r.json();
}
const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function pollJob(id, onUpdate) {
  return new Promise((resolve, reject) => {
    let since = 0;
    const tick = async () => {
      try {
        const j = await api(`/api/jobs/${id}?since=${since}`);
        since = j.n_log; onUpdate && onUpdate(j);
        if (j.status === 'done') return resolve(j.result);
        if (j.status === 'error') return reject(new Error(j.error));
        setTimeout(tick, 700);
      } catch (e) { reject(e); }
    };
    tick();
  });
}
const fmtT = (s) => { s = Math.max(0, s); const m = Math.floor(s / 60); return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`; };
const toLocalInput = (u) => u == null ? '' : new Date(u * 1000).toISOString().slice(0, 19);
const fromLocalInput = (v) => v ? Date.parse(v + 'Z') / 1000 : null;

/* ---------------- tabs and steps */
$$('.tab').forEach(b => b.onclick = () => {
  $$('.tab').forEach(x => x.classList.toggle('active', x === b));
  $('#tab-locate').classList.toggle('hidden', b.dataset.tab !== 'locate');
  $('#tab-audit').classList.toggle('hidden', b.dataset.tab !== 'audit');
  $('#tab-enf').classList.toggle('hidden', b.dataset.tab !== 'enf');
  $('#tab-help').classList.toggle('hidden', b.dataset.tab !== 'help');
});
function go(n) {
  $$('.step').forEach(b => { b.classList.toggle('active', +b.dataset.step === n); });
  for (let i = 1; i <= 5; i++) $(`#step-${i}`).classList.toggle('hidden', i !== n);
  if (n === 3) setTimeout(() => { setMap.invalidateSize(); if (boxLayer) setMap.fitBounds(boxLayer.getBounds(), { padding: [20, 20] }); }, 60);
  if (n === 5) setTimeout(() => { resMap.invalidateSize(); drawSpec(true); }, 50);
}
function markDone(n) { const b = $(`.step[data-step="${n}"]`); b.classList.add('done'); }
$$('.step').forEach(b => b.onclick = () => { if (!b.disabled) go(+b.dataset.step); });
function enableSteps(max) { $$('.step').forEach(b => b.disabled = +b.dataset.step > max); }
enableSteps(1);

/* ---------------- step 1: load */
async function loadSamples() {
  const list = await api('/api/samples');
  $('#samples').innerHTML = '';
  list.forEach(s => {
    const c = document.createElement('div'); c.className = 'card';
    c.innerHTML = `<b>${s.name}</b><p>${s.note}</p>${s.available ? '' : '<p class="c-low">not prepared on this machine</p>'}`;
    if (s.available || s.id === 'demo') c.onclick = () => loadSample(s.id);
    $('#samples').appendChild(c);
  });
}
async function loadSample(id) {
  status('#loadStatus', 'loading sample…');
  try { const r = await post('/api/load_sample', { id }); afterLoad(r.session, r.settings); }
  catch (e) { status('#loadStatus', e.message, true); }
}
function status(sel, msg, err) { const el = $(sel); el.textContent = msg; el.classList.toggle('err', !!err); }
const drop = $('#drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]); });
$('#fileIn').onchange = e => e.target.files[0] && uploadFile(e.target.files[0]);
async function uploadFile(f) {
  status('#loadStatus', `uploading ${f.name} (${(f.size / 1e6).toFixed(1)} MB) and extracting audio…`);
  const fd = new FormData(); fd.append('file', f);
  try { const r = await api('/api/upload', { method: 'POST', body: fd }); afterLoad(r.session, null); }
  catch (e) { status('#loadStatus', e.message, true); }
}
function afterLoad(sess, settings) {
  S.sid = sess.id; S.session = sess; S.which = 'orig'; S.result = null;
  $('#sessInfo').textContent = `${sess.name} · ${fmtT(sess.duration)} · ${sess.sr} Hz`;
  $('#auditFile').textContent = `file: ${sess.name} (${fmtT(sess.duration)})`;
  status('#loadStatus', `loaded ${sess.name}: ${sess.duration.toFixed(0)} s`);
  $('#trimB').placeholder = sess.duration.toFixed(0);
  $('#specBefore').src = specUrl('orig', 0, sess.duration, 30, 400, 1400, 260, 'db');
  $('#specAfter').removeAttribute('src');
  $('#player').src = `/api/audio/${S.sid}/orig.wav`;
  if (settings) applySettings(settings);
  markDone(1); enableSteps(3); go(2);
}
function specUrl(which, t0, t1, f0, f1, w, h, mode) {
  return `/api/spec.png?sid=${S.sid}&which=${which}&t0=${t0}&t1=${t1}&f0=${f0}&f1=${f1}&w=${w}&h=${h}&mode=${mode || 'bright'}&_=${Date.now()}`;
}

/* ---------------- step 2: clean */
const outs = { hp: ['#hpV', v => +v ? v + ' Hz' : 'off'], lp: ['#lpV', v => +v ? v + ' Hz' : 'off'],
  dn: ['#dnV', v => (+v).toFixed(2)], gain: ['#gV', v => v + ' dB'] };
let cleanTimer = null;
Object.entries(outs).forEach(([id, [o, f]]) => {
  $('#' + id).oninput = e => { $(o).textContent = f(e.target.value); scheduleClean(); };
});
['#steady', '#trimA', '#trimB'].forEach(s => $(s).onchange = scheduleClean);
function scheduleClean() { clearTimeout(cleanTimer); cleanTimer = setTimeout(applyClean, 900); }
$('#applyClean').onclick = applyClean;
$('#skipClean').onclick = () => { S.which = 'orig'; markDone(2); go(3); };
async function applyClean() {
  if (!S.sid) return;
  const body = { sid: S.sid, trim_start: +$('#trimA').value || 0, trim_end: +$('#trimB').value || null,
    highpass_hz: +$('#hp').value, lowpass_hz: +$('#lp').value, remove_steady: $('#steady').checked,
    denoise: +$('#dn').value, gain_db: +$('#gain').value };
  status('#cleanStatus', 'cleaning… (runs in the background)');
  try {
    const { job } = await post('/api/clean', body);
    const r = await pollJob(job, j => status('#cleanStatus', (j.log.slice(-1)[0] || 'working…').replace(/^\[.*?\] /, '')));
    S.session = r.session; S.which = 'clean';
    const dur = (body.trim_end || S.session.duration) - body.trim_start;
    $('#specAfter').src = specUrl('clean', 0, dur, 30, 400, 1400, 260, 'db');
    $('#player').src = `/api/audio/${S.sid}/clean.wav?_=${Date.now()}`;
    status('#cleanStatus', 'clean-up applied. The analysis will use the cleaned audio.');
    markDone(2);
  } catch (e) { status('#cleanStatus', e.message, true); }
}

/* ---------------- step 3: settings and map */
// Keyless base maps. Dark grey is the default; streets is OSM with a dark CSS filter.
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
function baseLayers(map) {
  const dark = L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 16, maxZoom: 19, attribution: 'Esri, HERE, Garmin, © OpenStreetMap' });
  const labels = L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 16, maxZoom: 19 });
  const darkL = L.layerGroup([dark, labels]);
  const streets = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'tiles-night', attribution: '© OpenStreetMap contributors' });
  const sat = L.tileLayer(ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Esri, Maxar, Earthstar Geographics' });
  darkL.addTo(map);
  L.control.layers({ 'Dark': darkL, 'Streets (night)': streets, 'Satellite': sat }, null, { position: 'topright' }).addTo(map);
}
const setMap = L.map('setMap', { zoomControl: true }).setView([39.5, -98.35], 4);
baseLayers(setMap);
let boxLayer = null, drawing = null;
const PRESETS = { 'Demo scene (Ohio, simulated)': [40.0302, 40.5698, -83.0538, -82.3462],
  'Long Island North Shore (reference)': [40.60, 41.10, -73.90, -73.20],
  'San Francisco Bay': [37.4, 38.0, -122.6, -121.9] };
Object.keys(PRESETS).forEach(k => { const o = document.createElement('option'); o.value = k; o.textContent = k; $('#presets').appendChild(o); });
$('#presets').onchange = e => { if (PRESETS[e.target.value]) setBbox(PRESETS[e.target.value], true); };
function setBbox(b, fit) {
  S.bbox = b.map(Number);
  if (boxLayer) boxLayer.remove();
  boxLayer = L.rectangle([[b[0], b[2]], [b[1], b[3]]], { color: '#19ff9c', weight: 1.5, fillOpacity: 0.06, dashArray: '4 4' }).addTo(setMap);
  if (fit) setMap.fitBounds(boxLayer.getBounds(), { padding: [20, 20] });
  const km = (b[1] - b[0]) * 111.2, km2 = (b[3] - b[2]) * 111.2 * Math.cos((b[0] + b[1]) / 2 * Math.PI / 180);
  $('#bboxTxt').textContent = `${b.map(v => v.toFixed(3)).join(', ')}  (${km.toFixed(0)}×${km2.toFixed(0)} km)`;
}
$('#drawBox').onclick = () => { drawing = []; $('#drawBox').textContent = 'click corner 1…'; setMap.getContainer().style.cursor = 'crosshair'; };
setMap.on('click', e => {
  if (!drawing) return;
  drawing.push(e.latlng);
  if (drawing.length === 1) { $('#drawBox').textContent = 'click corner 2…'; return; }
  const [a, b] = drawing; drawing = null; setMap.getContainer().style.cursor = '';
  $('#drawBox').textContent = 'Draw box';
  setBbox([Math.min(a.lat, b.lat), Math.max(a.lat, b.lat), Math.min(a.lng, b.lng), Math.max(a.lng, b.lng)], false);
});
$('#useView').onclick = () => { const z = setMap.getBounds(); setBbox([z.getSouth(), z.getNorth(), z.getWest(), z.getEast()], false); };
$$('input[name=tk]').forEach(r => r.onchange = () => $('#clipRow').classList.toggle('hidden', !(+document.querySelector('input[name=tk]:checked').value)));
$('#grid').oninput = e => $('#gridV').textContent = e.target.value + ' m';
$('#adsbFile').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  $('#adsbName').textContent = 'uploading…';
  const fd = new FormData(); fd.append('file', f);
  const r = await api('/api/upload_adsb', { method: 'POST', body: fd });
  S.adsbPath = r.path; $('#adsbName').textContent = r.name;
  document.querySelector('input[name=adsb][value=file]').checked = true;
};
function applySettings(st) {
  S.settings = st; S.adsbPath = st.adsb_path; S.demPath = st.dem_path; S.author = st.author_answer || null;
  $('#adsbName').textContent = st.adsb_path ? st.adsb_path.split('/').slice(-1)[0] : 'none';
  $('#wStart').value = toLocalInput(st.start); $('#wEnd').value = toLocalInput(st.end);
  $('#events').value = st.events || ''; $('#fmin').value = st.fmin; $('#fmax').value = st.fmax;
  $('#height').value = st.height; $('#grid').value = st.grid_m; $('#gridV').textContent = st.grid_m + ' m';
  $('#dem').value = st.dem_mode === 'file' ? 'file' : st.dem_mode;
  $('#adsbDate').value = new Date(st.start * 1000).toISOString().slice(0, 10);
  setBbox(st.bbox, true);
}
$('#goRun').onclick = startRun;

/* ---------------- step 4: run */
async function startRun() {
  if (!S.sid) return alert('Load a recording first.');
  if (!S.bbox) return alert('Choose a search region: draw a box, use the current view, or pick a preset.');
  const tk = +document.querySelector('input[name=tk]:checked').value === 1;
  const adsbMode = document.querySelector('input[name=adsb]:checked').value;
  const body = { sid: S.sid, use_clean: S.which === 'clean', bbox: S.bbox,
    start: fromLocalInput($('#wStart').value), end: fromLocalInput($('#wEnd').value),
    time_known: tk, clip_start: tk ? fromLocalInput($('#clipStart').value) : null,
    adsb_mode: adsbMode, adsb_path: S.adsbPath, adsb_date: $('#adsbDate').value,
    dem_mode: $('#dem').value, dem_path: S.demPath, grid_m: +$('#grid').value, events: $('#events').value,
    fmin: +$('#fmin').value, fmax: +$('#fmax').value, height: +$('#height').value,
    max_gap: S.settings ? S.settings.max_gap : (adsbMode === 'adsblol' ? 300 : 60),
    truth: S.settings ? S.settings.truth : null };
  if (!body.start || !body.end) return alert('Set the time window (UTC).');
  markDone(3); enableSteps(4); go(4);
  $('#log').textContent = ''; $('#bar').style.width = '2%'; $('#runState').textContent = 'starting…';
  try {
    const { job } = await post('/api/run', body);
    const res = await pollJob(job, j => {
      if (j.log.length) { $('#log').textContent += j.log.join('\n') + '\n'; $('#log').scrollTop = 1e9; }
      $('#bar').style.width = Math.round(100 * Math.max(0.03, j.progress)) + '%';
      $('#runState').textContent = j.status === 'running' ? 'running…' : j.status;
      $('#runTime').textContent = ` ${j.elapsed}s`;
    });
    $('#runState').textContent = 'done'; markDone(4); enableSteps(5);
    showResults(res); go(5);
  } catch (e) { $('#runState').textContent = 'error: ' + e.message; $('#runState').classList.add('c-low'); }
}

/* ---------------- step 5: results */
const resMap = L.map('resMap', { preferCanvas: true }).setView([39.5, -98.35], 4);
baseLayers(resMap);
let heatLayer = L.layerGroup().addTo(resMap), selLayer = L.layerGroup().addTo(resMap);
const ramp = (v) => { const a = [[11, 107, 63], [25, 255, 156], [45, 226, 255], [234, 255, 246]];
  const x = Math.min(0.999, Math.max(0, v)) * (a.length - 1), i = Math.floor(x), t = x - i;
  const c = a[i].map((q, k) => Math.round(q + (a[i + 1][k] - q) * t)); return `rgb(${c})`; };

function showResults(r) {
  S.result = r; S.sel = 0;
  if (!r.ok) { $('#bestBox').innerHTML = `<b class="c-low">${r.message}</b>`; return; }
  heatLayer.clearLayers();
  const ren = L.canvas({ padding: 0.3 });
  r.heat.slice().reverse().forEach(([la, lo, v]) => L.circleMarker([la, lo], { renderer: ren, radius: 2 + 4 * v, stroke: false, fillColor: ramp(v), fillOpacity: 0.25 + 0.6 * v }).addTo(heatLayer));
  r.fine.forEach(([la, lo, v]) => { if (v > 0.6) L.circleMarker([la, lo], { renderer: ren, radius: 3, stroke: false, fillColor: ramp(v), fillOpacity: 0.5 * v }).addTo(heatLayer); });
  const b = r.bbox; L.rectangle([[b[0], b[2]], [b[1], b[3]]], { color: '#16342a', weight: 1, fill: false }).addTo(heatLayer);
  r.ranking.forEach((c, i) => L.circleMarker([c.lat, c.lon], { radius: 5, color: '#2de2ff', weight: 1, fillOpacity: 0 })
    .bindTooltip(`#${c.rank} ${c.callsign1 || c.flight1}${c.callsign2 ? ' + ' + c.callsign2 : ''} · ${c.total.toFixed(2)}`).on('click', () => select(i)).addTo(heatLayer));
  if (r.truth) L.marker([r.truth[0], r.truth[1]]).bindTooltip('hidden truth (demo)').addTo(heatLayer);
  if (S.author) L.circleMarker(S.author, { radius: 9, color: '#ffcc4d', weight: 2, fillOpacity: 0 }).bindTooltip("author's stated answer").addTo(heatLayer);
  const tb = $('#rankTbl tbody'); tb.innerHTML = '';
  r.ranking.forEach((c, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${c.rank}</td><td>${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}</td><td>${c.total.toFixed(2)}</td><td class="c-${c.confidence}">${c.confidence}</td><td>${c.callsign1 || c.flight1}${c.callsign2 || c.flight2 ? ' + ' + (c.callsign2 || c.flight2) : ''}</td>`;
    tr.onclick = () => select(i); tb.appendChild(tr);
  });
  $('#evBox').innerHTML = r.events.map(e => `<div><span class="c-high">${e.name}</span> ${e.t_start.toFixed(0)}–${e.t_end.toFixed(0)} s · ${e.f0.toFixed(1)} Hz · ${e.speed.toFixed(0)} m/s [${e.speed_range.map(v => v.toFixed(0)).join('–')}] · ${(e.slant_cpa / 1000).toFixed(2)} km [${e.slant_range.map(v => (v / 1000).toFixed(1)).join('–')}] · CPA ${e.t_cpa.toFixed(1)} s</div>`).join('');
  $('#funnel').innerHTML = r.stages.map(([n, v]) => `<div>${String(v.toLocaleString()).padStart(10, '\u00a0')} · ${n}</div>`).join('');
  ['exMd:report.md', 'exJson:result.json', 'exPng:map.png', 'exZip:report.zip'].forEach(s => { const [id, k] = s.split(':'); $('#' + id).href = `/api/export/${S.sid}/${k}`; });
  const v = $('#verdict'); v.textContent = `confidence: ${r.best.confidence}`; v.className = `pill c-${r.best.confidence}`;
  const e0 = r.events[0], eN = r.events[r.events.length - 1];
  S.view = { t0: Math.max(0, e0.t_start - 20), t1: eN.t_end + 20, f0: Math.max(20, e0.fmin - 10), f1: Math.min(400, e0.fmax + 40) };
  select(0, true);
}
function select(i, fit) {
  S.sel = i; const r = S.result, c = r.ranking[i];
  $$('#rankTbl tbody tr').forEach((tr, k) => tr.classList.toggle('sel', k === i));
  selLayer.clearLayers();
  if (c.track1) L.polyline(c.track1, { color: '#ff9f1c', weight: 2, opacity: 0.9 }).bindTooltip(`event 1: ${c.callsign1 || c.flight1} (${c.type1 || '?'})`).addTo(selLayer);
  if (c.track2 && c.track2.length) L.polyline(c.track2, { color: '#ff4fd8', weight: 2, opacity: 0.9 }).bindTooltip(`event 2: ${c.callsign2 || c.flight2} (${c.type2 || '?'})`).addTo(selLayer);
  const pt = i === 0 ? [r.best.fine_lat, r.best.fine_lon] : [c.lat, c.lon];
  L.circleMarker(pt, { radius: 8, color: '#19ff9c', weight: 2, fillColor: '#19ff9c', fillOpacity: 0.35 }).addTo(selLayer);
  if (fit || i !== 0) resMap.setView(pt, Math.max(resMap.getZoom(), fit ? 12 : 13));
  const gm = `https://www.google.com/maps?q=${pt[0].toFixed(5)},${pt[1].toFixed(5)}`;
  const err = (i === 0 && r.summary_error_m != null) ? `<div class="small">error vs hidden truth: <b>${r.summary_error_m.toFixed(0)} m</b></div>` : '';
  const auth = S.author ? `<div class="small">distance to author's answer: <b>${hav(pt, S.author).toFixed(0)} m</b></div>` : '';
  $('#bestBox').innerHTML = `<div class="dim small">${i === 0 ? 'BEST ESTIMATE' : 'CANDIDATE #' + c.rank}</div>
    <div class="coord">${pt[0].toFixed(5)}, ${pt[1].toFixed(5)}</div>
    <div class="small">confidence <b class="c-${c.confidence}">${c.confidence}</b> · score ${c.total.toFixed(2)} (event 1 ${c.s1.toFixed(2)}, event 2 ${c.s2.toFixed(2)})</div>
    <div class="small">flights: <span style="color:#ff9f1c">${c.callsign1 || c.flight1} ${c.type1 || ''}</span>${c.flight2 ? ` + <span style="color:#ff4fd8">${c.callsign2 || c.flight2} ${c.type2 || ''}</span>` : ''}</div>
    ${err}${auth}<div class="small"><a class="c-high" href="${gm}" target="_blank" rel="noopener">open in maps ↗</a></div>`;
  drawSpec(true);
}
function hav(a, b) { const R = 6371008.8, la = (a[0] + b[0]) / 2 * Math.PI / 180;
  return Math.hypot((a[0] - b[0]) * Math.PI / 180 * R, (a[1] - b[1]) * Math.PI / 180 * R * Math.cos(la)); }

/* spectrogram viewer */
const cv = $('#specCanvas'), cx = cv.getContext('2d');
let img = null, imgView = null, imgTimer = null;
function slc(t, f0, v, d, tc, c = 343) {  // straight-line Doppler curve (same as physics.py)
  v = Math.min(Math.abs(v), 0.95 * c); d = Math.max(Math.abs(d), 1);
  const te0 = tc - d / c, T = t - te0, a = c * c - v * v;
  const u = (c * c * T - Math.sqrt(v * v * c * c * T * T + a * d * d)) / a;
  const vr = v * v * u / Math.sqrt(v * v * u * u + d * d); return f0 * c / (c + vr);
}
function drawSpec(reload) {
  if (!S.result || !S.result.ok || !S.view) return;
  const W = cv.clientWidth, H = cv.clientHeight; cv.width = W; cv.height = H;
  const V = S.view, X = t => (t - V.t0) / (V.t1 - V.t0) * W, Y = f => H - (f - V.f0) / (V.f1 - V.f0) * H;
  cx.fillStyle = '#000'; cx.fillRect(0, 0, W, H);
  if (img && imgView) {  // draw last image re-mapped to the current view while the new one loads
    const iv = imgView;
    cx.drawImage(img, X(iv.t0), Y(iv.f1), X(iv.t1) - X(iv.t0), Y(iv.f0) - Y(iv.f1));
  }
  // grid
  cx.strokeStyle = 'rgba(25,255,156,0.10)'; cx.fillStyle = '#5f8a77'; cx.font = '10px monospace';
  const ts = niceStep((V.t1 - V.t0) / 8), fs = niceStep((V.f1 - V.f0) / 6);
  for (let t = Math.ceil(V.t0 / ts) * ts; t < V.t1; t += ts) { cx.beginPath(); cx.moveTo(X(t), 0); cx.lineTo(X(t), H); cx.stroke(); cx.fillText(t.toFixed(ts < 1 ? 1 : 0) + 's', X(t) + 2, H - 3); }
  for (let f = Math.ceil(V.f0 / fs) * fs; f < V.f1; f += fs) { cx.beginPath(); cx.moveTo(0, Y(f)); cx.lineTo(W, Y(f)); cx.stroke(); cx.fillText(f.toFixed(0) + ' Hz', 3, Y(f) - 2); }
  const r = S.result;
  if ($('#ovRidge').checked) r.events.forEach(e => { cx.fillStyle = 'rgba(45,226,255,0.85)'; e.ridge.forEach(([t, f]) => cx.fillRect(X(t) - 1, Y(f) - 1, 2, 2)); });
  if ($('#ovFit').checked) r.events.forEach(e => { cx.strokeStyle = 'rgba(255,255,255,0.7)'; cx.setLineDash([4, 4]); cx.beginPath();
    for (let t = e.t_start; t <= e.t_end; t += 0.5) { const f = slc(t, e.f0, e.speed, e.slant_cpa, e.t_cpa); t === e.t_start ? cx.moveTo(X(t), Y(f)) : cx.lineTo(X(t), Y(f)); } cx.stroke(); cx.setLineDash([]); });
  const c = r.ranking[S.sel];
  if ($('#ovPred').checked && c && c.curves) c.curves.forEach((cur, k) => {
    cx.strokeStyle = k === 0 ? '#ff9f1c' : '#ff4fd8'; cx.lineWidth = 1.6; cx.shadowColor = cx.strokeStyle; cx.shadowBlur = 4; cx.beginPath();
    cur.forEach(([t, f], j) => j ? cx.lineTo(X(t), Y(f)) : cx.moveTo(X(t), Y(f))); cx.stroke(); cx.shadowBlur = 0; cx.lineWidth = 1; });
  r.events.forEach(e => { cx.fillStyle = 'rgba(25,255,156,0.8)'; cx.fillText(e.name, X(e.t_start) + 3, 12); });
  if (reload) { clearTimeout(imgTimer); imgTimer = setTimeout(loadSpecImg, 160); }
}
function niceStep(x) { const p = Math.pow(10, Math.floor(Math.log10(x))), m = x / p; return (m < 2 ? 1 : m < 5 ? 2 : 5) * p; }
function loadSpecImg() {
  const V = { ...S.view }, W = cv.clientWidth, H = cv.clientHeight;
  const im = new Image();
  im.onload = () => { img = im; imgView = V; drawSpec(false); };
  im.src = specUrl(S.which, V.t0, V.t1, V.f0, V.f1, W, H, 'bright');
}
cv.addEventListener('wheel', e => {
  e.preventDefault(); if (!S.view) return;
  const V = S.view, rect = cv.getBoundingClientRect(), k = e.deltaY > 0 ? 1.25 : 0.8;
  if (e.shiftKey) { const f = V.f1 - (e.clientY - rect.top) / rect.height * (V.f1 - V.f0);
    V.f0 = Math.max(0, f - (f - V.f0) * k); V.f1 = Math.min(500, f + (V.f1 - f) * k); }
  else { const t = V.t0 + (e.clientX - rect.left) / rect.width * (V.t1 - V.t0);
    V.t0 = Math.max(0, t - (t - V.t0) * k); V.t1 = t + (V.t1 - t) * k; }
  drawSpec(true);
}, { passive: false });
let drag = null;
cv.addEventListener('mousedown', e => { drag = { x: e.clientX, y: e.clientY, v: { ...S.view } }; cv.style.cursor = 'grabbing'; });
window.addEventListener('mouseup', () => { if (drag) { drag = null; cv.style.cursor = 'grab'; drawSpec(true); } });
cv.addEventListener('mousemove', e => {
  const rect = cv.getBoundingClientRect(), V = S.view; if (!V) return;
  if (drag) { const dt = (e.clientX - drag.x) / rect.width * (drag.v.t1 - drag.v.t0), df = (e.clientY - drag.y) / rect.height * (drag.v.f1 - drag.v.f0);
    V.t0 = drag.v.t0 - dt; V.t1 = drag.v.t1 - dt; V.f0 = drag.v.f0 + df; V.f1 = drag.v.f1 + df; drawSpec(false); }
  const t = V.t0 + (e.clientX - rect.left) / rect.width * (V.t1 - V.t0), f = V.f1 - (e.clientY - rect.top) / rect.height * (V.f1 - V.f0);
  const tip = $('#specTip'); tip.style.display = 'block'; tip.style.left = (e.clientX - rect.left + 12) + 'px'; tip.style.top = (e.clientY - rect.top + 12) + 'px';
  tip.textContent = `${t.toFixed(1)} s · ${f.toFixed(1)} Hz`;
});
cv.addEventListener('mouseleave', () => $('#specTip').style.display = 'none');
['#ovRidge', '#ovFit', '#ovPred'].forEach(s => $(s).onchange = () => drawSpec(false));
const zoomTo = (e) => { S.view = { t0: e.t_start - 10, t1: e.t_end + 10, f0: Math.max(20, e.f0 * 0.6), f1: Math.min(450, e.f0 * 1.75) }; drawSpec(true); };
$('#zoomE1').onclick = () => S.result && zoomTo(S.result.events[0]);
$('#zoomE2').onclick = () => S.result && S.result.events[1] && zoomTo(S.result.events[1]);
$('#zoomAll').onclick = () => { if (!S.result) return; const ev = S.result.events; S.view = { t0: Math.max(0, ev[0].t_start - 30), t1: ev[ev.length - 1].t_end + 30, f0: 30, f1: 300 }; drawSpec(true); };
$('#exSpec').onclick = () => { const a = document.createElement('a'); a.href = cv.toDataURL('image/png'); a.download = 'provenance_spectrogram.png'; a.click(); };
window.addEventListener('resize', () => drawSpec(true));

/* ---------------- audit tab */
$('#runAudit').onclick = async () => {
  if (!S.sid) return alert('Load a recording first (Locate → 01).');
  $('#auditOut').innerHTML = '<div class="status">scanning…</div>';
  try {
    const { job } = await post('/api/audit', { sid: S.sid, use_clean: $('#auditClean').checked, highpass: +$('#auditHp').value });
    const r = await pollJob(job);
    $('#auditOut').innerHTML = `<div class="lvl ${r.level}">EXPOSURE: ${r.level}</div><div class="auditlines">${r.lines.map(esc).join('\n')}</div>`;
    const im = $('#auditSpec'); im.classList.remove('hidden');
    im.src = specUrl(r.which, 0, r.duration, 30, 400, 1600, 300, 'bright');
  } catch (e) { $('#auditOut').innerHTML = `<div class="status err">${esc(e.message)}</div>`; }
};
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

loadSamples();

/* ---------------- ENF tab (raw audio only) */
const E = { eid: null, refPath: null };
const enfDrop = $('#enfDrop');
['dragenter', 'dragover'].forEach(ev => enfDrop.addEventListener(ev, e => { e.preventDefault(); enfDrop.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => enfDrop.addEventListener(ev, e => { e.preventDefault(); enfDrop.classList.remove('over'); }));
enfDrop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) enfUpload(e.dataTransfer.files[0]); });
$('#enfFile').onchange = e => { if (e.target.files[0]) enfUpload(e.target.files[0]); };
function enfShowFile(r) {
  E.eid = r.id; const m = r.meta || {};
  const tg = m.tags || {}; const ct = tg['com.apple.quicktime.creationdate'] || tg.creation_time || tg.date;
  $('#enfFileInfo').textContent = `${r.name} · ${(m.duration || 0).toFixed(0)} s · ${m.has_video ? (m.n_audio === 0 ? 'VIDEO, no audio track (picture flicker only)' : 'VIDEO (audio + picture flicker)') : 'audio'} · ${m.audio_codec || ''} ${m.audio_sr ? m.audio_sr + ' Hz' : ''} · ${ct ? 'metadata time ' + ct : 'no creation time in metadata'}`;
}
async function enfUpload(f) {
  status('#enfFileInfo', `uploading ${f.name}…`);
  const fd = new FormData(); fd.append('file', f);
  try { enfShowFile(await api('/api/enf/upload', { method: 'POST', body: fd })); } catch (e) { status('#enfFileInfo', e.message, true); }
}
$('#enfUseSess').onclick = async () => {
  if (!S.sid) return status('#enfFileInfo', 'no file loaded in Locate yet', true);
  try { enfShowFile(await post('/api/enf/from_session', { sid: S.sid })); } catch (e) { status('#enfFileInfo', e.message, true); }
};
const enfRefKind = () => { const v = document.querySelector('input[name=enfRef]:checked').value; return v === 'grid' ? 'grid:' + $('#enfGrid').value : v; };
function enfRefUI() {
  const k = enfRefKind();
  $('#enfRefFileRow').classList.toggle('hidden', k !== 'file');
}
$$('input[name=enfRef]').forEach(r => r.onchange = enfRefUI);
$('#enfRefFile').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  try { const r = await api('/api/enf/upload_ref', { method: 'POST', body: fd }); E.refPath = r.path;
    $('#enfRefName').textContent = `${r.name} · ${r.info.nominal} Hz · ${r.info.hours} h${r.info.start ? ' from ' + r.info.start : ' (undated)'}`;
  } catch (er) { $('#enfRefName').textContent = er.message; }
};
async function enfSamples() {
  const list = await api('/api/enf/samples');
  $('#enfSamples').innerHTML = list.map(s => `<div class="card ${s.available ? '' : 'off'}" data-id="${s.id}"><b>${esc(s.name)}</b><p>${esc(s.note)}</p></div>`).join('');
  $$('#enfSamples .card').forEach(c => c.onclick = async () => {
    try {
      const r = await post('/api/enf/load_sample', { id: c.dataset.id }); enfShowFile(r);
      const st = r.settings; const rk = (st.ref_kind || 'gb');
      document.querySelector(`input[name=enfRef][value=${rk.startsWith('grid:') ? 'grid' : rk}]`).checked = true;
      if (rk.startsWith('grid:')) $('#enfGrid').value = rk.slice(5);
      $('#enfCross').checked = !!st.cross_nominal; $('#enfSeisOnly').checked = (st.exclude_logs || []).includes('zenodo_wecc_2024'); $('#enfRace').checked = st.race !== false; enfRefUI();
      if (st.ref_path) { E.refPath = st.ref_path; $('#enfRefName').textContent = st.ref_name; }
      $('#enfStart').value = st.start || ''; $('#enfEnd').value = st.end || '';
      $('#enfNominal').value = st.nominal ? String(st.nominal) : '';
      $('#enfVideo').value = st.video || 'auto'; $('#enfReadout').value = st.readout_ms || ''; enfCovDraw();
    } catch (e) { status('#enfFileInfo', e.message, true); }
  });
}
const badge = (txt, cls) => `<span class="badge ${cls}">${esc(txt)}</span>`;
const lvlCls = v => ({ present: 'good', strong: 'good', HIGH: 'bad', moderate: 'good', weak: 'warn', MEDIUM: 'warn', LOW: 'good', absent: 'dim' }[v] || 'dim');
$('#enfReadoutPick').onchange = e => { if (e.target.value) $('#enfReadout').value = e.target.value; e.target.value = ''; };
$('#enfRun').onclick = async () => {
  if (!E.eid) return status('#enfStatus', 'drop a file or pick a sample first', true);
  const k = enfRefKind();
  if (k === 'file' && !E.refPath) return status('#enfStatus', 'choose a reference file', true);
  const body = { eid: E.eid, ref_kind: k, ref_path: k === 'file' ? E.refPath : null,
    start: $('#enfStart').value ? $('#enfStart').value + 'Z' : null, end: $('#enfEnd').value ? $('#enfEnd').value + 'Z' : null,
    nominal: $('#enfNominal').value ? +$('#enfNominal').value : null,
    race: $('#enfRace').checked, use_meta: $('#enfMeta').checked, cross_nominal: $('#enfCross').checked,
    exclude_logs: $('#enfSeisOnly').checked ? ['zenodo_wecc_2024'] : [],
    video: $('#enfVideo').value, readout_ms: $('#enfReadout').value ? +$('#enfReadout').value : null };
  const lg = $('#enfLog'); lg.classList.remove('hidden'); lg.textContent = '';
  status('#enfStatus', 'analysing…');
  try {
    const { job } = await post('/api/enf/run', body);
    const r = await pollJob(job, j => { lg.textContent += j.log.join('\n') + (j.log.length ? '\n' : ''); lg.scrollTop = 1e9; status('#enfStatus', `analysing… ${Math.round(j.progress * 100)}%`); });
    status('#enfStatus', `done in ${r.elapsed_s} s`); enfShow(r);
  } catch (e) { status('#enfStatus', e.message, true); }
};
function enfShow(r) {
  const d = r.detect, m = r.match, p = r.privacy, g = r.grid, rc = r.race, gf = r.grid_final || {};
  const gcls = gf.method === 'grid race' ? (gf.confidence === 'decisive' ? 'good' : 'warn') : (gf.method === 'statistics' ? 'warn' : 'dim');
  let h = `<div class="row wrap">${badge('HUM ' + (d.verdict === 'absent' ? 'no usable' : (r.scan.nominal || r.grid.nominal) + ' Hz' + (r.scan.nominal ? '' : ' (faint)')), d.verdict === 'absent' ? 'dim' : 'good')}
    ${badge('ENF ' + d.verdict.toUpperCase(), lvlCls(d.verdict))}
    ${badge('GRID ' + (gf.grid || 'UNKNOWN') + (gf.grid ? ' · ' + gf.confidence : ''), gcls)}
    ${m ? badge('MATCH ' + m.label.toUpperCase(), lvlCls(m.label)) : ''}
    ${badge('PRIVACY ' + p.level, lvlCls(p.level))}</div>`;
  if (m) h += `<div class="enfbig mono">${esc(m.start_label)}</div>
    <div class="mono small">r = ${m.ncc} · runner-up ${m.second_ncc} (${esc(m.second_start_label || '-')}) · false-match chance ≈ ${Number(m.p_false).toPrecision(2)} · RMSE ${m.rmse_mhz} mHz · offset ${m.offset_mhz} mHz · continuity: ${esc(r.continuity ? r.continuity.verdict : '-')}</div>
    ${(m.warnings || []).map(w => `<div class="status err small">! ${esc(w)}</div>`).join('')}
    <div class="dim small">reference: ${esc(m.reference.name)} · ${esc(m.reference.source)}${m.reference.start ? ' · ' + esc(m.reference.start) + ' → ' + esc(m.reference.end) : ''}</div>`;
  else if (r.match_error) h += `<div class="status err">match skipped: ${esc(r.match_error)}</div>`;
  h += `<h3>Which grid?</h3><div class="enfbig mono" style="font-size:20px">${esc(gf.name || '')}</div><div class="mono small">${esc(gf.method === 'none' ? 'no grid answer' : 'by ' + gf.method)} · ${esc(gf.reason || '')}</div>`;
  h += enfVideoHtml(r);
  if (rc) {
    h += `<h4>Grid race <span class="dim small">(${esc(rc.window_source || '')})</span> ${badge(rc.decision.toUpperCase(), rc.decision === 'decisive' ? 'good' : rc.decision === 'likely' ? 'warn' : 'dim')}</h4>`;
    if ((rc.ranking || []).length) h += `<table class="racetbl mono small"><tr><th>#</th><th>grid</th><th>r (level-gated)</th><th>raw r</th><th>level offset</th><th>false-alarm p</th><th>best start (UTC)</th><th>reference</th></tr>${rc.ranking.map((x, i) => `<tr class="${x.grid === rc.winner ? 'win' : ''}"><td>${i + 1}</td><td>${esc(x.name)}</td><td>${x.r.toFixed(3)}</td><td>${x.raw_r == null ? '-' : x.raw_r.toFixed(3)}</td><td>${x.offset_mhz == null ? '-' : x.offset_mhz.toFixed(1) + ' mHz'}</td><td>${Number(x.p_false).toPrecision(2)}</td><td>${esc(x.best_start)}</td><td>${esc(x.source)}${x.trust != null && x.trust < 0.8 ? ' · <b class="warnc">low trust</b>' : ''}${x.tz_shift_h ? ' · clock ' + (x.tz_shift_h > 0 ? '+' : '') + x.tz_shift_h + ' h' : ''}${x.nominal && x.nominal !== rc.nominal ? ' · ' + x.nominal + ' Hz grid (control)' : ''}${/seismic/.test(x.source || '') ? ' · <b class="goodc">seismometer consensus</b>' : ''}</td></tr>`).join('')}${(rc.not_covered || []).map(x => `<tr class="off"><td>-</td><td>${esc(x.name)}</td><td colspan="6">no free reference for this time · ${esc(x.sources)}</td></tr>`).join('')}</table>`;
    h += `<div class="mono small">margin ${rc.margin == null ? '-' : rc.margin.toFixed(2)} · Fisher-z margin ${rc.dz == null ? '-' : rc.dz.toFixed(2)} · rule: likely = r ≥ 0.60, z-margin ≥ 0.5, p < 0.5; decisive = r ≥ 0.80, z-margin ≥ 1.0, p < 0.01; otherwise abstain</div>`;
    if (rc.segments && rc.segments.segments && rc.segments.segments.length) h += `<div class="mono small dim">300 s pieces: ${rc.segments.segments.map(s => `${s.t0 / 60}′ ${s.grid} r=${s.r}${s.vote ? '✓' : ''}`).join(' · ')}</div>`;
    if (r.png.race) h += `<img class="specimg" src="${r.png.race}">`;
  }
  h += `<h4>Statistical grid guess <span class="dim small">(fallback when time is unknown)</span></h4><div class="mono small">${esc(g.verdict)}</div>`;
  if (g.note) h += `<div class="dim small">${esc(g.note)}</div>`;
  if (g.probs && Object.keys(g.probs).length) h += `<div class="mono small dim">${Object.entries(g.probs).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(k)} ${(v * 100).toFixed(0)}%`).join(' · ')}</div>`;
  h += `<h3>Why (detector)</h3><div class="auditlines">${d.reasons.map(esc).join('\n')}</div>`;
  h += `<h3>Privacy verdict</h3><div class="lvl ${p.level}">TIME/GRID LEAK: ${p.level}</div><div class="auditlines">${p.lines.map(esc).join('\n')}${p.fixes.length ? '\n\nFixes:\n- ' + p.fixes.map(esc).join('\n- ') : ''}</div>`;
  if (r.png.spec) h += `<h3>Spectrogram around the hum harmonics</h3><img class="specimg" src="${r.png.spec}">`;
  if (r.png.trace) h += `<h3>${r.primary_source === 'video' ? 'ENF trace from the light flicker' : 'ENF trace'}</h3><img class="specimg" src="${r.png.trace}">`;
  if (r.png.match) h += `<h3>Recording vs reference at the best fit</h3><img class="specimg" src="${r.png.match}">`;
  h += `<div class="row"><a class="btn small" href="/api/enf/result/${E.eid}.json">JSON result</a></div>`;
  $('#enfOut').innerHTML = h;
}
// ---- video light flicker: status, audio vs picture, the picture's own race
const agCls = v => ({ 'agree': 'good', 'agree with an offset': 'warn', 'partly disagree': 'bad', 'disagree': 'bad' }[v] || 'dim');
function enfVideoHtml(r) {
  const v = r.video; if (!v) return '';
  const pv = (v.presence || {}).verdict || 'absent', ag = r.av_agreement;
  let h = `<h3>Picture: mains light flicker ${badge('VIDEO ' + pv.toUpperCase(), lvlCls(pv))} ${ag ? badge('AUDIO vs PICTURE ' + ag.verdict.toUpperCase(), agCls(ag.verdict)) : ''}</h3>`;
  h += `<div class="mono small">${esc(v.status || '')}${v.path_used ? ' · ' + esc(v.path_used) + ' path · ' + v.nominal + ' Hz mains (' + 2 * v.nominal + ' Hz flicker)' : ''}`
    + `${v.readout_ms ? ' · read-out ' + v.readout_ms + ' ms (' + esc(v.readout_source) + ')' : ''}`
    + `${v.readout_search ? ' · band contrast ' + v.readout_search.contrast_db + ' dB' : ''}`
    + `${v.alias_hz != null ? ' · alias ' + v.alias_hz + ' Hz' : ''}`
    + `${v.dropped != null ? ' · dropped ' + Math.round(v.dropped * 100) + '% of frames (motion / exposure)' : ''}`
    + `${v.keyframes && v.keyframes.gop_s ? ' · keyframe every ' + v.keyframes.gop_s + ' s' : ''}</div>`;
  if (v.info) h += `<div class="dim small">${v.info.width}×${v.info.height} · ${esc(String(v.info.fps_exact))} fps · ${esc(v.info.codec || '')}${v.info.rotation ? ' · rotated ' + v.info.rotation + '°' : ''}</div>`;
  h += `<div class="auditlines">${((v.presence || {}).reasons || []).map(esc).join('\n')}</div>`;
  if (ag) {
    h += `<div class="mono small">r = ${ag.r_best ?? '-'} at lag ${ag.best_lag_s ?? '-'} s · offset ${ag.offset_mhz ?? '-'} mHz · overlap ${ag.overlap_s ?? '-'} s</div><div class="status small">${esc(ag.hint || ag.reason || '')}</div>`;
    (ag.cross_checks || []).forEach(c => h += `<div class="status err small">! ${esc(c)}</div>`);
  }
  if (r.png.video) h += `<img class="specimg" src="${r.png.video}">`;
  const vr = v.race;
  if (vr) {
    h += `<h4>Picture's own grid race ${badge(vr.decision.toUpperCase(), vr.decision === 'decisive' ? 'good' : vr.decision === 'likely' ? 'warn' : 'dim')}</h4>`;
    if ((vr.ranking || []).length) h += `<table class="racetbl mono small"><tr><th>#</th><th>grid</th><th>r</th><th>level offset</th><th>false-alarm p</th><th>best start (UTC)</th></tr>${vr.ranking.map((x, i) => `<tr class="${x.grid === vr.winner ? 'win' : ''}"><td>${i + 1}</td><td>${esc(x.name)}</td><td>${x.r.toFixed(3)}</td><td>${x.offset_mhz == null ? '-' : x.offset_mhz.toFixed(1) + ' mHz'}</td><td>${Number(x.p_false).toPrecision(2)}</td><td>${esc(x.best_start)}</td></tr>`).join('')}</table>`;
    h += `<div class="mono small dim">${esc(vr.reason || '')}</div>`;
    if (r.png.vrace) h += `<img class="specimg" src="${r.png.vrace}">`;
  }
  if (v.match) h += `<div class="mono small">picture time match: ${esc(v.match.start_label)} · r = ${v.match.ncc} · ${esc(v.match.label)}</div>`;
  return h;
}
// ---- coverage: which grid logs exist when (so users see when a US race is possible)
let COV = null;
const yr = d => { const t = Date.parse(d + 'T00:00:00Z'); return 1970 + t / 3.15576e10; };
function enfCovDraw() {
  if (!COV) return;
  const Y0 = 2014, Y1 = new Date().getUTCFullYear() + 1, W = Math.max(300, ($('#enfCov').clientWidth || 320) - 4), X = y => 70 + (y - Y0) / (Y1 - Y0) * (W - 80);
  const ws = $('#enfStart').value ? Date.parse($('#enfStart').value + 'Z') : null;
  const we = $('#enfEnd').value ? Date.parse($('#enfEnd').value + 'Z') : ws;
  const inWin = sp => ws && Date.parse(sp.start + 'T00:00:00Z') <= we && Date.parse(sp.end + 'T23:59:59Z') >= ws;
  let svg = `<svg width="${W}" height="${COV.length * 22 + 24}" class="covsvg">`;
  for (let y = Y0; y <= Y1; y += (W < 450 ? 4 : 2)) svg += `<line x1="${X(y)}" x2="${X(y)}" y1="0" y2="${COV.length * 22}" stroke="#334"/><text x="${X(y)}" y="${COV.length * 22 + 14}" fill="#889" font-size="10" text-anchor="middle">${y}</text>`;
  COV.forEach((g, i) => {
    const yy = i * 22 + 4, hit = (g.spans || []).some(inWin) || (g.live && ws && ['GB', 'CE'].includes(g.grid));
    svg += `<text x="0" y="${yy + 11}" fill="${hit ? '#7fdc7f' : '#ccd'}" font-size="11">${esc(g.grid)}${hit ? ' ✓' : ''}</text>`;
    if (g.live) { const a = { GB: 2014, CE: 2022.33, NORDIC: 2015 }[g.grid] || Y0; svg += `<rect x="${X(a)}" y="${yy}" width="${X(Y1 - 0.9) - X(a)}" height="14" fill="#3a6ea5" opacity=".55"><title>${esc(g.live)}</title></rect>`; }
    (g.spans || []).forEach(sp => {
      const x0 = X(yr(sp.start)), x1 = Math.max(x0 + 3, X(yr(sp.end) + 1 / 365));
      const col = sp.duplicate_of ? '#666' : sp.trust < 0.8 ? '#c9a227' : sp.tz_uncertain ? '#d08a4a' : '#5fbf7f';
      svg += `<rect x="${x0}" y="${yy}" width="${x1 - x0}" height="14" fill="${col}"><title>${esc(sp.source)}: ${sp.start} to ${sp.end}, ${sp.good_hours} h, ${sp.resolution_s} s, trust ${sp.trust}${sp.tz_uncertain ? ', clock offset inferred' : ''}</title></rect>`;
    });
  });
  svg += '</svg>';
  const rows = COV.filter(g => g.nominal === 60).map(g => (g.spans || []).filter(s => !s.duplicate_of).map(sp =>
    `<tr class="${inWin(sp) ? 'covhit' : ''}"><td>${esc(g.grid)}</td><td title="${esc(sp.source)}">${esc(sp.source.split(' (')[0].split(',')[0])}</td><td class="mono nw">${sp.start}<br>→ ${sp.end}</td><td class="mono nw">${Math.round(sp.good_hours)} h<br>${sp.resolution_s} s</td><td>${sp.trust < 0.8 ? 'low' : sp.tz_uncertain ? 'clock inferred' : 'measured'}</td></tr>`).join('')).join('');
  $('#enfCov').innerHTML = svg + `<div class="dim small">green = measured 1 s log · orange = clock offset inferred · gold = low trust (FNET gauge scrape) · blue = live/archived European feeds · ✓ = covers your search window</div>
    <table class="covtab"><tr><th>grid</th><th>US source</th><th>dates (UTC)</th><th>hours, step</th><th>quality</th></tr>${rows}</table>`;
}
async function enfCoverage() { try { COV = await api('/api/enf/coverage'); enfCovDraw(); } catch (e) { $('#enfCov').textContent = 'coverage unavailable: ' + e.message; } }
['#enfStart', '#enfEnd'].forEach(id => $(id).addEventListener('change', enfCovDraw));
enfRefUI(); enfSamples(); enfCoverage();

// Help tab: the contents list scrolls to each section
$$('#helpToc a').forEach(a => a.onclick = ev => { ev.preventDefault(); const t = document.getElementById(a.dataset.go); if (t) t.scrollIntoView({behavior: 'smooth', block: 'start'}); });
