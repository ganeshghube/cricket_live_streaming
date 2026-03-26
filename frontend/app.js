/**
 * SportsCaster Pro - Frontend (Fixed)
 *
 * FIXES:
 * 1. Session persistence — token saved in localStorage, sent on every request
 * 2. Camera preview — shows actual MJPEG feed for IP/mobile cameras
 * 3. Overlay sync — sport-specific WS data drives overlay iframe
 * 4. Streaming — shows device list, validates camera before stream
 * 5. Recording — proper start/stop with status
 * 6. Replay — loads /api/recording/list, direct video URLs
 * 7. Player management — save/load players per team from DB
 * 8. Reviews — correct save + list + play
 */
'use strict';

const API    = `http://${location.hostname}:8000/api`;
const WS_URL = `${location.protocol==='https:'?'wss':'ws'}://${location.hostname}:8000/ws`;
const LS_TOKEN_KEY = 'sc_session_token';   // FIX: localStorage key for session

// ── State ────────────────────────────────────────────────────────────────────
let token       = null;
let ws          = null;
let matchId     = null;
let matchState  = {};
let activeSport = 'cricket';
let streamSettings = { platform:'youtube', key:'', url:'', bitrate:'2500k' };
let popupTimer  = null;
let _deviceList = [];   // cached camera device names

const $ = id => document.getElementById(id);
// replay_vid and review_vid defined below setSpeed/stepFrame

// ════════════════════════════════════════════════════════════════════════════
// SESSION — FIX: persist across refresh
// ════════════════════════════════════════════════════════════════════════════
function saveToken(t)    { token = t; localStorage.setItem(LS_TOKEN_KEY, t); }
function clearToken()    { token = null; localStorage.removeItem(LS_TOKEN_KEY); }
function loadToken()     { return localStorage.getItem(LS_TOKEN_KEY); }

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (token) h['X-Session-Token'] = token;
  return h;
}

async function checkSession() {
  const saved = loadToken();
  if (!saved) return false;
  try {
    const r = await fetch(`${API}/auth/me`, {
      credentials:'include',
      headers: { 'X-Session-Token': saved }
    });
    if (r.ok) { token = saved; return true; }
  } catch(e) {}
  clearToken();
  return false;
}

// ── API helpers ───────────────────────────────────────────────────────────
async function apiGet(path) {
  const r = await fetch(`${API}${path}`, {
    credentials:'include', headers: authHeaders()
  });
  if (!r.ok) { const t=await r.text(); throw new Error(t); }
  return r.json();
}

async function apiPost(path, body={}) {
  const r = await fetch(`${API}${path}`, {
    method:'POST', credentials:'include',
    headers: authHeaders(), body: JSON.stringify(body)
  });
  if (!r.ok) { const t=await r.text(); throw new Error(t); }
  return r.json();
}

async function apiDel(path) {
  return fetch(`${API}${path}`, {
    method:'DELETE', credentials:'include', headers: authHeaders()
  });
}

// ════════════════════════════════════════════════════════════════════════════
// AUTH
// ════════════════════════════════════════════════════════════════════════════
async function doLogin() {
  const u=$('u').value, p=$('p').value;
  try {
    const data = await apiPost('/auth/login', {username:u, password:p});
    saveToken(data.token);
    $('login-screen').style.display = 'none';
    $('app').style.display = 'flex';
    initApp();
  } catch(e) {
    $('login-err').textContent = 'Invalid credentials';
  }
}

async function doLogout() {
  try { await apiPost('/auth/logout',{}); } catch(e){}
  clearToken();
  location.reload();
}

$('p').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });

// ════════════════════════════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════════════════════════════
async function bootApp() {
  // FIX: check saved session before showing login
  const ok = await checkSession();
  if (ok) {
    $('login-screen').style.display = 'none';
    $('app').style.display = 'flex';
    initApp();
  }
  // else login screen stays visible
}

function initApp() {
  connectWS();
  loadSettings();
  loadSavedCams();
  syncStreamStatus();
  syncRecordingStatus();
  loadCameraDevices();
  goTo('scoring','cricket');
}

bootApp();

// ════════════════════════════════════════════════════════════════════════════
// WEBSOCKET
// ════════════════════════════════════════════════════════════════════════════
function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen  = () => console.log('[WS] connected');
  ws.onclose = () => setTimeout(connectWS, 2000);
  ws.onerror = () => ws.close();
  ws.onmessage = e => {
    try { handleWS(JSON.parse(e.data)); } catch(ex) {}
  };
}

function handleWS(msg) {
  switch(msg.type) {
    case 'INIT':
      if (msg.payload.score)              { matchState=msg.payload.score; renderAllScoreboards(); }
      if (msg.payload.stream_status)        updateStreamBadge(msg.payload.stream_status==='live');
      if (msg.payload.recording_status)     updateRecBadge(msg.payload.recording_status==='recording');
      break;
    case 'SCORE_UPDATE':
      matchState = msg.payload.state || msg.payload;
      renderAllScoreboards();
      if (msg.payload.popup) showPopup(msg.payload.popup);
      break;
    case 'MATCH_STARTED': case 'CRICKET_UPDATE':
      matchState = msg.payload;
      matchId    = msg.payload.match_id || matchId;
      activeSport= msg.payload.sport || 'cricket';
      renderAllScoreboards();
      break;
    case 'STREAM_STATUS':
      updateStreamBadge(msg.payload.status==='live');
      break;
    case 'RECORDING_STATUS':
      updateRecBadge(msg.payload.status==='recording');
      if (msg.payload.file) setTxt('rec-file-display', msg.payload.file);
      break;
    case 'AI_UPDATE':
      updateAIDisplay(msg.payload);
      break;
    case 'CAMERA_CHANGED':
      updateCameraPreviewAll(msg.payload.url);
      break;
  }
}

function wsSend(data) {
  if (ws && ws.readyState===1) ws.send(JSON.stringify(data));
}

// ════════════════════════════════════════════════════════════════════════════
// NAVIGATION
// ════════════════════════════════════════════════════════════════════════════
const NAV_SECTIONS = ['scoring','camera','streaming','recording','replay','review','ai','settings'];

function toggleNav(section) {
  const isOpen = $(`sub-${section}`).classList.contains('open');
  NAV_SECTIONS.forEach(s => {
    $(`sub-${s}`)?.classList.remove('open');
    $(`nav-${s}`)?.classList.remove('expanded','active');
  });
  if (!isOpen) {
    $(`sub-${section}`).classList.add('open');
    $(`nav-${section}`).classList.add('expanded','active');
  }
}

function goTo(section, sub) {
  NAV_SECTIONS.forEach(s => {
    $(`sub-${s}`)?.classList.remove('open');
    $(`nav-${s}`)?.classList.remove('expanded','active');
  });
  $(`sub-${section}`)?.classList.add('open');
  $(`nav-${section}`)?.classList.add('expanded','active');

  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.subpage').forEach(sp=>sp.classList.remove('active'));
  $(`page-${section}`)?.classList.add('active');
  $(`sp-${section}-${sub}`)?.classList.add('active');

  document.querySelectorAll('.sub-item').forEach(si => {
    si.classList.toggle('active', si.getAttribute('onclick')?.includes(`'${section}','${sub}'`));
  });

  // Side effects
  if (section==='replay' && sub==='recordings') loadRecordings();
  if (section==='replay' && sub==='reviews')    loadReviews();
  if (section==='camera' && sub==='saved')      loadSavedCams();
  if (section==='ai'     && sub==='training')   loadSnapshots();
  if (section==='ai'     && sub==='models')     loadModels();
  if (section==='streaming' && sub==='live')    syncStreamStatus();
  if (section==='recording' && sub==='control') syncRecordingStatus();
}

function setTxt(id, v) { const el=$(id); if(el) el.textContent=v; }

// ════════════════════════════════════════════════════════════════════════════
// CAMERA — FIX: proper preview + device list
// ════════════════════════════════════════════════════════════════════════════
async function loadCameraDevices() {
  try {
    const data = await apiGet('/stream/list-devices');
    _deviceList = data.devices || [];
    // Populate USB select
    const sel = $('usb-index');
    if (sel && _deviceList.length > 0) {
      sel.innerHTML = _deviceList.map((d,i)=>
        `<option value="${i}">${d}</option>`
      ).join('');
    }
    const info = $('usb-device-info');
    if (info) info.textContent = _deviceList.length
      ? `${_deviceList.length} device(s) found`
      : 'No devices detected. Check FFmpeg installation.';
  } catch(e) {}
}

async function detectUSB() {
  await loadCameraDevices();
}

async function setUsbActive() {
  const sel = $('usb-index');
  if (!sel) return;
  const idx = sel.value;
  const label = _deviceList[idx] ? `USB: ${_deviceList[idx]}` : `USB Camera ${idx}`;
  // Save with actual device name for Windows
  const url = _deviceList[idx] || idx;
  try {
    const cams = await apiGet('/cameras/');
    let existing = (cams.cameras||[]).find(c=>c.url===String(idx)||c.url===url);
    if (!existing) {
      const saved = await apiPost('/cameras/', {label, url: String(idx), type:'usb'});
      existing = {id:saved.id};
    }
    await apiPost(`/cameras/${existing.id}/activate`, {});
    updateCameraPreviewAll(String(idx));
    toast('USB camera set as active');
  } catch(e) { toast('Error: '+e.message, true); }
}

function updateCameraPreviewAll(url) {
  // Update all preview elements
  ['usb-preview-wrap','ip-preview-wrap','mobile-preview-wrap','active-preview-wrap',
   'stream-preview-wrap','rec-preview-wrap','ai-preview-wrap'].forEach(id => {
    const el = $(id);
    if (el) setPreviewEl(el, url);
  });
}

/**
 * FIX: Camera preview.
 * - IP/HTTP/RTSP cameras: load as <img> (MJPEG streams work in <img> tag)
 * - USB cameras: show info message (browser can't access USB directly)
 */
function setPreviewEl(wrap, url) {
  if (!wrap) return;
  const label = wrap.querySelector('.preview-label')?.outerHTML || '<span class="preview-label">CAM</span>';
  if (!url || url==='' || /^\d$/.test(url)) {
    wrap.innerHTML = `${label}<div class="preview-err">
      <div style="font-size:2rem">📷</div>
      <div>USB Camera active</div>
      <div style="font-size:0.75rem;margin-top:4px">USB preview requires MJPEG server.<br>
      Use IP Webcam app for mobile preview.</div>
    </div>`;
  } else {
    wrap.innerHTML = `${label}
      <img src="${url}" alt="Camera feed"
        style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover"
        onerror="this.style.display='none';this.nextSibling.style.display='flex'"
      />
      <div class="preview-err" style="display:none">
        <div>⚠️ Cannot load preview</div>
        <div style="font-size:0.75rem">${url}</div>
      </div>`;
  }
}

function setPreview(wrapId, url) { setPreviewEl($(wrapId), url); }

async function testIpCam() {
  const url = $('ip-url')?.value?.trim();
  if (!url) return;
  const el = $('ip-test-result');
  if(el) { el.textContent='Testing...'; el.style.color='var(--text3)'; }
  try {
    const data = await apiGet(`/stream/test-camera?source=${encodeURIComponent(url)}`);
    if(el) {
      el.textContent = data.ok ? '✓ Camera reachable' : '✗ Cannot connect — check URL';
      el.style.color = data.ok ? 'var(--green)' : 'var(--red)';
    }
  } catch(e) {
    if(el) { el.textContent='✗ Test failed'; el.style.color='var(--red)'; }
  }
}

function previewIpCam() { setPreview('ip-preview-wrap', $('ip-url')?.value?.trim()); }
function previewMobile() { setPreview('mobile-preview-wrap', $('mobile-url')?.value?.trim()); }

async function saveIpCam() {
  const label = $('ip-label')?.value || 'IP Camera';
  const url   = $('ip-url')?.value?.trim();
  if (!url) return;
  try {
    let id;
    try {
      const saved = await apiPost('/cameras/', {label, url, type:'ip'});
      id = saved.id;
    } catch(e) {
      const cams = await apiGet('/cameras/');
      const ex = (cams.cameras||[]).find(c=>c.url===url);
      if (ex) id=ex.id; else throw e;
    }
    await apiPost(`/cameras/${id}/activate`, {});
    updateCameraPreviewAll(url);
    loadSavedCams();
    const el=$('ip-test-result');
    if(el){el.textContent='✓ Saved & set active!';el.style.color='var(--green)';}
  } catch(e) { toast('Error: '+e.message, true); }
}

async function saveMobileCam() {
  const url = $('mobile-url')?.value?.trim();
  if (!url) return;
  try {
    let id;
    try {
      const saved = await apiPost('/cameras/', {label:'Mobile Camera',url,type:'mobile'});
      id=saved.id;
    } catch(e) {
      const cams=await apiGet('/cameras/');
      const ex=(cams.cameras||[]).find(c=>c.url===url);
      if(ex)id=ex.id; else throw e;
    }
    await apiPost(`/cameras/${id}/activate`,{});
    updateCameraPreviewAll(url);
    loadSavedCams();
    setPreview('mobile-preview-wrap',url);
    toast('Mobile camera saved & active');
  } catch(e){ toast('Error: '+e.message,true); }
}

async function loadSavedCams() {
  try {
    const data = await apiGet('/cameras/');
    const list = $('saved-cams-list');
    if (!list) return;
    if (!data.cameras?.length) {
      list.innerHTML='<div class="empty-state"><div class="empty-icon">📷</div>No saved cameras</div>';
      return;
    }
    list.innerHTML = data.cameras.map(c=>`
      <div class="cam-item ${c.active?'active-src':''}">
        <div class="cam-info">
          <div class="cam-label">${c.label} ${c.active?'<span style="color:var(--accent);font-size:0.75rem">● Active</span>':''}</div>
          <div class="cam-url">${c.url}</div>
        </div>
        <div class="cam-actions">
          <button class="btn btn-xs btn-accent" onclick="activateCam(${c.id},'${c.url}')">Set Active</button>
          <button class="btn btn-xs btn-ghost" onclick="deleteCam(${c.id})">🗑</button>
        </div>
      </div>`).join('');
    const active = data.cameras.find(c=>c.active);
    if (active) updateCameraPreviewAll(active.url);
  } catch(e) {}
}

async function activateCam(id, url) {
  await apiPost(`/cameras/${id}/activate`,{});
  updateCameraPreviewAll(url);
  loadSavedCams();
}
async function deleteCam(id) { await apiDel(`/cameras/${id}`); loadSavedCams(); }

// ════════════════════════════════════════════════════════════════════════════
// PLAYER MANAGEMENT — FIX: save/load players per team
// ════════════════════════════════════════════════════════════════════════════
async function savePlayers(teamName, playersText, sport='cricket') {
  const players = playersText.split('\n').map(s=>s.trim()).filter(Boolean);
  if (!players.length) return;
  await apiPost('/scoring/players/save', {team_name:teamName, players, sport});
  toast(`Players saved for ${teamName}`);
}

async function loadPlayers(teamName, targetTextareaId, sport='cricket') {
  try {
    const data = await apiGet(`/scoring/players/${encodeURIComponent(teamName)}?sport=${sport}`);
    const el = $(targetTextareaId);
    if (el && data.players) el.value = data.players.join('\n');
    return data.players || [];
  } catch(e) { return []; }
}

async function loadSavedTeams(selectId, sport='cricket') {
  try {
    const data = await apiGet(`/scoring/players/teams/list?sport=${sport}`);
    const sel = $(selectId);
    if (!sel) return;
    sel.innerHTML = '<option value="">-- Select saved team --</option>' +
      (data.teams||[]).map(t=>`<option value="${t}">${t}</option>`).join('');
  } catch(e) {}
}

// ════════════════════════════════════════════════════════════════════════════
// SCORING
// ════════════════════════════════════════════════════════════════════════════
async function startMatch(sport) {
  const cfg = buildMatchConfig(sport);
  try {
    const data = await apiPost('/scoring/match/new', cfg);
    matchId     = data.match_id;
    activeSport = sport;
    matchState  = data.state;
    showScoringUI(sport);
    renderAllScoreboards();
    // Save players to DB
    if (sport==='cricket') {
      const pa = $('cr-players-a')?.value||'';
      const pb = $('cr-players-b')?.value||'';
      if (pa) savePlayers(cfg.team_a, pa, sport);
      if (pb) savePlayers(cfg.team_b, pb, sport);
    }
  } catch(e) { toast('Failed to start match: '+e.message, true); }
}

function buildMatchConfig(sport) {
  const base = {sport};
  if (sport==='cricket') {
    base.team_a    = $('cr-team-a')?.value||'Team A';
    base.team_b    = $('cr-team-b')?.value||'Team B';
    base.overs     = parseInt($('cr-overs')?.value)||20;
    base.players_a = ($('cr-players-a')?.value||'').split('\n').map(s=>s.trim()).filter(Boolean);
    base.players_b = ($('cr-players-b')?.value||'').split('\n').map(s=>s.trim()).filter(Boolean);
  } else if (sport==='football') {
    base.team_a = $('fb-team-a')?.value||'Home';
    base.team_b = $('fb-team-b')?.value||'Away';
  } else if (sport==='hockey') {
    base.team_a = $('hk-team-a')?.value||'Team A';
    base.team_b = $('hk-team-b')?.value||'Team B';
  } else if (sport==='volleyball') {
    base.team_a = $('vb-team-a')?.value||'Team A';
    base.team_b = $('vb-team-b')?.value||'Team B';
  } else {
    base.team_a = $('cu-team-a')?.value||'Team A';
    base.team_b = $('cu-team-b')?.value||'Team B';
  }
  return base;
}

function showScoringUI(sport) {
  const formEl = $(`new-match-form-${sport}`);
  const uiEl   = $(`${sport}-scoring-ui`);
  if (formEl) formEl.style.display='none';
  if (uiEl)   uiEl.style.display='block';
}

async function scoreEvt(event) {
  if (!matchId) { toast('Start a match first', true); return; }
  try {
    const data = await apiPost('/scoring/event', {match_id:matchId, event, payload:{}});
    if (data.state) {
      matchState = data.state;
      renderAllScoreboards();
      const popup = matchState.last_event?.popup;
      if (popup) showPopup(popup);
    }
  } catch(e) { console.error(e); }
}

async function selectPlayer(role, name) {
  if (!matchId || !name) return;
  await apiPost('/scoring/player/select', {match_id:matchId, role, player_name:name}).catch(()=>{});
}

// ── Scoreboard renderers ──────────────────────────────────────────────────
function renderAllScoreboards() {
  if (!matchState?.sport) return;
  const sport = matchState.sport;
  if (sport==='cricket')    renderCricketSB();
  else if (sport==='football')   renderFootballSB();
  else if (sport==='hockey')     renderHockeySB();
  else if (sport==='volleyball') renderVolleyballSB();
  else renderCustomSB();
}

function setInner(id,v){ const el=$(id); if(el) el.innerHTML=v; }

function renderCricketSB() {
  const bt=matchState.batting_team||'a', sc=matchState.score||{a:{runs:0,wickets:0,overs:0,balls:0,extras:0},b:{runs:0,wickets:0,overs:0,balls:0,extras:0}};
  setTxt('cr-sb-a', matchState.team_a);
  setTxt('cr-sb-b', matchState.team_b);
  setTxt('cr-sb-sa', bt==='a'?`${sc.a.runs}/${sc.a.wickets}`:sc.a.runs);
  setTxt('cr-sb-sb', bt==='b'?`${sc.b.runs}/${sc.b.wickets}`:sc.b.runs);
  setTxt('cr-sb-meta', `Overs: ${sc[bt].overs}.${sc[bt].balls} | Inn: ${matchState.innings||1} | Extras: ${sc[bt].extras||0}`);
  const dots=(matchState.current_over||[]).map(b=>{
    const cls=b==='W'?'w':b==='4'?'four':b==='6'?'six':'';
    return `<div class="od ${cls}">${b}</div>`;
  }).join('');
  setInner('cr-over-dots', dots||'<span style="color:var(--text3);font-size:0.8rem">New over</span>');
  if ($('cr-striker') && document.activeElement!==$('cr-striker')) $('cr-striker').value=matchState.striker||'';
  if ($('cr-nonstriker') && document.activeElement!==$('cr-nonstriker')) $('cr-nonstriker').value=matchState.non_striker||'';
  if ($('cr-bowler') && document.activeElement!==$('cr-bowler')) $('cr-bowler').value=matchState.bowler||'';
}

function renderFootballSB() {
  setTxt('fb-sb-a',matchState.team_a); setTxt('fb-sb-b',matchState.team_b);
  setTxt('fb-sb-sa',matchState.score?.a??0); setTxt('fb-sb-sb',matchState.score?.b??0);
  setTxt('fb-sb-meta',`Half ${matchState.half||1}`);
  setTxt('fb-btn-a',matchState.team_a); setTxt('fb-btn-b',matchState.team_b);
}

function renderHockeySB() {
  setTxt('hk-sb-a',matchState.team_a); setTxt('hk-sb-b',matchState.team_b);
  setTxt('hk-sb-sa',matchState.score?.a??0); setTxt('hk-sb-sb',matchState.score?.b??0);
  setTxt('hk-sb-meta',`Quarter ${matchState.quarter||1}`);
}

function renderVolleyballSB() {
  const sw=matchState.sets_won||{a:0,b:0};
  const cur=(matchState.set_scores||[{a:0,b:0}])[(matchState.current_set||1)-1]||{a:0,b:0};
  setTxt('vb-sb-a',matchState.team_a); setTxt('vb-sb-b',matchState.team_b);
  setTxt('vb-sb-sa',sw.a); setTxt('vb-sb-sb',sw.b);
  setTxt('vb-sb-meta',`Set ${matchState.current_set||1}: ${cur.a} — ${cur.b}`);
}

function renderCustomSB() {
  setTxt('cu-sb-a',matchState.team_a); setTxt('cu-sb-b',matchState.team_b);
  setTxt('cu-sb-sa',matchState.score?.a??0); setTxt('cu-sb-sb',matchState.score?.b??0);
}

// ── Popup ─────────────────────────────────────────────────────────────────
function showPopup(text) {
  const el = $('event-popup'); if(!el) return;
  el.textContent=text; el.className='';
  const t=text.toLowerCase();
  if(t.includes('four'))   el.classList.add('green');
  else if(t.includes('six'))    el.classList.add('cyan');
  else if(t.includes('wicket')) el.classList.add('red');
  else if(t.includes('goal'))   el.classList.add('yellow');
  el.classList.add('show');
  clearTimeout(popupTimer);
  popupTimer=setTimeout(()=>el.classList.remove('show'),2800);
}

// ════════════════════════════════════════════════════════════════════════════
// STREAMING — FIX: device list + validate before start
// ════════════════════════════════════════════════════════════════════════════
function onPlatformChange() {
  const p=$('st-platform')?.value;
  const row=$('custom-url-row');
  if(row) row.style.display=p==='custom'?'block':'none';
}

async function loadStreamDevices() {
  try {
    const data = await apiGet('/stream/list-devices');
    const el=$('stream-devices-info');
    if (el) {
      if (data.devices?.length) {
        el.innerHTML='<strong>Available cameras:</strong><br>'+
          data.devices.map((d,i)=>`<span style="color:var(--accent)">${i}: ${d}</span>`).join('<br>');
      } else {
        el.innerHTML = data.platform==='linux'
          ? 'Linux: cameras at /dev/video0, /dev/video1...'
          : 'No DirectShow devices found. Check camera connection.';
      }
    }
    // Fill camera source select if present
    const sel = $('stream-cam-select');
    if (sel && data.devices?.length) {
      sel.innerHTML = data.devices.map((d,i)=>
        `<option value="${i}">${i}: ${d}</option>`
      ).join('');
    }
  } catch(e) {}
}

function saveStreamSettings() {
  streamSettings.platform = $('st-platform')?.value||'youtube';
  streamSettings.key      = $('st-key')?.value||'';
  streamSettings.url      = $('st-url')?.value||'';
  streamSettings.bitrate  = $('st-bitrate')?.value||'2500k';
  apiPost('/settings/', {stream_key:streamSettings.key, stream_url:streamSettings.url}).catch(()=>{});
  setTxt('stream-platform-display', `Platform: ${streamSettings.platform.toUpperCase()}`);
  toast('Stream settings saved!');
}

async function startStream() {
  if (!streamSettings.key.trim() && !streamSettings.url.trim()) {
    goTo('streaming','rtmp');
    toast('Configure stream key in RTMP Settings first', true);
    return;
  }
  const camSrc = app_state_get_camera() || '0';
  const btnGo=$('btn-go-live');
  if(btnGo){btnGo.disabled=true;btnGo.textContent='Starting...';}
  try {
    const data = await apiPost('/stream/start', {
      platform:      streamSettings.platform,
      stream_key:    streamSettings.key,
      stream_url:    streamSettings.url,
      bitrate:       streamSettings.bitrate,
      camera_source: camSrc,
    });
    if (data.status==='live') { updateStreamBadge(true); toast('Stream started!'); }
  } catch(e) {
    toast('Stream failed: '+e.message.substring(0,120), true);
  } finally {
    if(btnGo){btnGo.disabled=false;btnGo.textContent='▶ Go Live';}
  }
}

async function stopStream() {
  await apiPost('/stream/stop',{}).catch(()=>{});
  updateStreamBadge(false);
  toast('Stream stopped');
}

async function loadStreamLog() {
  try {
    const data=await apiGet('/stream/log');
    const el=$('stream-log-output');
    if(el) el.textContent=(data.lines||[]).join('\n')||'No log yet.';
  } catch(e){}
}

function updateStreamBadge(live) {
  const badge=$('stream-badge'), pill=$('live-pill');
  const btnGo=$('btn-go-live'), btnStop=$('btn-stop-live');
  if(badge){badge.className=`badge ${live?'badge-live':'badge-idle'}`;badge.textContent=live?'● Live':'● Idle';}
  if(pill) pill.className=`live-pill ${live?'on':''}`;
  if(btnGo)  btnGo.disabled=live;
  if(btnStop) btnStop.disabled=!live;
}

async function syncStreamStatus() {
  try {
    const data=await apiGet('/stream/status');
    updateStreamBadge(data.running);
  } catch(e){}
}

function app_state_get_camera() {
  // Get active camera from saved list
  return null; // backend reads from app_state
}

// ════════════════════════════════════════════════════════════════════════════
// RECORDING — FIX
// ════════════════════════════════════════════════════════════════════════════
async function startRecording() {
  const btn=$('btn-start-rec');
  if(btn){btn.disabled=true;btn.textContent='Starting...';}
  try {
    const data=await apiPost('/recording/start',{});
    updateRecBadge(true);
    if(data.file) setTxt('rec-file-display',data.file);
    toast('Recording started!');
  } catch(e) {
    toast('Recording failed: '+e.message.substring(0,100), true);
  } finally {
    if(btn){btn.disabled=false;btn.textContent='⏺ Start Recording';}
  }
}

async function stopRecording() {
  const data=await apiPost('/recording/stop',{}).catch(e=>({status:'error',message:e.message}));
  updateRecBadge(false);
  if(data.file) setTxt('rec-file-display',`Saved: ${data.file}`);
  loadRecordings();
  toast(data.file ? `Saved: ${data.file}` : 'Recording stopped');
}

function updateRecBadge(recording) {
  const badge=$('rec-badge'), pill=$('rec-pill');
  const btnStart=$('btn-start-rec'), btnStop=$('btn-stop-rec');
  if(badge){badge.className=`badge ${recording?'badge-rec':'badge-idle'}`;badge.textContent=recording?'⏺ Recording':'● Idle';}
  if(pill)  pill.className=`rec-pill ${recording?'on':''}`;
  if(btnStart) btnStart.disabled=recording;
  if(btnStop)  btnStop.disabled=!recording;
}

async function syncRecordingStatus() {
  try {
    const data=await apiGet('/recording/status');
    updateRecBadge(data.status==='recording');
    if(data.file) setTxt('rec-file-display',data.file);
  } catch(e){}
}

// ════════════════════════════════════════════════════════════════════════════
// REPLAY — FIX: loads from API, correct video URLs
// ════════════════════════════════════════════════════════════════════════════
async function loadRecordings() {
  try {
    const data=await apiGet('/recording/list');
    const el=$('rec-list-replay');
    if (!el) return;
    if (!data.recordings?.length) {
      el.innerHTML='<div class="empty-state"><div class="empty-icon">📹</div>No recordings yet</div>';
      return;
    }
    el.innerHTML='<div class="recording-list">' +
      data.recordings.map(r=>`
        <div class="rec-item">
          <div class="rec-item-info">
            <div class="rec-item-name">📹 ${r.name}</div>
            <div class="rec-item-meta">${r.size_mb} MB · ${r.created}</div>
          </div>
          <div class="rec-item-actions">
            <button class="btn btn-accent btn-xs" onclick="playRec('${r.url}','${r.name}')">▶ Play</button>
            <button class="btn btn-ghost btn-xs" onclick="delRec('${r.name}')">🗑</button>
          </div>
        </div>`).join('') + '</div>';
  } catch(e) { console.error('loadRecordings',e); }
}

function playRec(url, name) {
  const card=$('replay-player-card'), vid=replay_vid();
  if (!card||!vid) return;
  card.style.display='block';
  setTxt('replay-player-title', name);
  // FIX: use full URL with hostname for video src
  vid.src = `http://${location.hostname}:8000${url}`;
  vid.play().catch(()=>{});
  card.scrollIntoView({behavior:'smooth'});
}

async function delRec(name) {
  if(!confirm(`Delete ${name}?`)) return;
  await apiDel(`/recording/${name}`);
  loadRecordings();
}

function _getVid(vidRef) {
  if (typeof vidRef === 'function') return vidRef();
  if (typeof vidRef === 'string')   return document.getElementById(vidRef);
  if (vidRef instanceof HTMLElement) return vidRef;
  return null;
}
function setSpeed(vidRef, s) { const v=_getVid(vidRef); if(v) v.playbackRate=parseFloat(s); }
function stepFrame(vidRef, dir) { const v=_getVid(vidRef); if(!v) return; v.pause(); v.currentTime=Math.max(0,v.currentTime+dir/30); }
// Expose as named vars so HTML onclick can reference them
const replay_vid = () => document.getElementById('replay-video');
const review_vid_fn = () => document.getElementById('review-video');

// ════════════════════════════════════════════════════════════════════════════
// REVIEWS — FIX
// ════════════════════════════════════════════════════════════════════════════
async function saveReview() {
  const et=$('review-event-type')?.value||'wicket';
  const btn=$('btn-save-review');
  if(btn){btn.disabled=true;btn.textContent='⏳ Saving...';}
  try {
    const data=await apiPost(`/review/save?event_type=${et}&duration=12`,{});
    if(data.status==='saved') { setTimeout(loadReviews,500); toast('Review clip saved!'); }
    else toast('Review error: '+(data.error||'unknown'), true);
  } catch(e){ toast('Review failed: '+e.message, true); }
  finally { if(btn){btn.disabled=false;btn.textContent='💾 Save Last 12s';} }
}

async function loadReviews() {
  try {
    const data=await apiGet('/review/list');
    const el=$('rev-list');
    if (!el) return;
    if (!data.reviews?.length) {
      el.innerHTML='<div class="empty-state"><div class="empty-icon">🔍</div>No review clips</div>';
      return;
    }
    el.innerHTML='<div class="recording-list">' +
      data.reviews.map(r=>`
        <div class="rec-item">
          <div class="rec-item-info">
            <div class="rec-item-name">🔍 ${r.name}</div>
            <div class="rec-item-meta">${r.event} · ${r.size_mb} MB · ${r.created}</div>
          </div>
          <div class="rec-item-actions">
            <button class="btn btn-accent btn-xs" onclick="playRev('${r.url}')">▶ Review</button>
            <button class="btn btn-ghost btn-xs" onclick="delRev('${r.name}')">🗑</button>
          </div>
        </div>`).join('') + '</div>';
  } catch(e) {}
}

function playRev(url) {
  const card=$('review-player-card'), vid=review_vid();
  if(!card||!vid) return;
  card.style.display='block';
  setTxt('review-decision','');
  vid.src=`http://${location.hostname}:8000${url}`;
  vid.play().catch(()=>{});
  card.scrollIntoView({behavior:'smooth'});
}

async function delRev(name) { await apiDel(`/review/${name}`); loadReviews(); }

function decisionOut() {
  const el=$('review-decision');
  if(el){el.textContent='OUT';el.style.color='var(--red)';}
  showPopup('OUT! ✓');
}
function decisionNotOut() {
  const el=$('review-decision');
  if(el){el.textContent='NOT OUT';el.style.color='var(--green)';}
  showPopup('NOT OUT ✗');
}

// ════════════════════════════════════════════════════════════════════════════
// AI TRACKING
// ════════════════════════════════════════════════════════════════════════════
async function startAI() {
  await apiPost('/ai/start',{}).catch(()=>{});
  $('ai-dot')?.classList.add('on'); $('ball-ai-dot')?.classList.add('on');
  setTxt('ai-status-text','Active — detecting...');
  setTxt('ball-status-text','Active — tracking ball...');
}
async function stopAI() {
  await apiPost('/ai/stop',{}).catch(()=>{});
  $('ai-dot')?.classList.remove('on'); $('ball-ai-dot')?.classList.remove('on');
  setTxt('ai-status-text','Inactive');
  setTxt('ball-status-text','Tracking inactive');
  setInner('det-grid','<span style="color:var(--text3);font-size:0.82rem">No detections</span>');
}

function updateAIDisplay(payload) {
  const dets=payload.detections||[], pan=payload.pan||{};
  $('ai-dot')?.classList.toggle('on',dets.length>0);
  $('ball-ai-dot')?.classList.toggle('on',dets.some(d=>d.type==='ball'));
  setTxt('ai-status-text',dets.length?`Active — ${dets.length} detected`:'Active — scanning...');
  if(dets.length) {
    setInner('det-grid',dets.map(d=>`<span class="det-chip">${d.type==='ball'?'🏏':'👤'} ${d.type} ${Math.round(d.confidence*100)}%</span>`).join(''));
    const ball=dets.find(d=>d.type==='ball');
    if(ball) setTxt('ball-pos',`X:${ball.x} Y:${ball.y} R:${ball.r}`);
  }
  if(pan.x!==undefined){setTxt('pan-x',pan.x.toFixed(3));setTxt('pan-y',pan.y.toFixed(3));}
}

async function captureSnapshot() {
  const data=await apiPost('/ai/snapshot?event=manual',{}).catch(()=>({total:0}));
  setTxt('snapshot-count',data.total||0);
}
async function loadSnapshots() {
  try{const d=await apiGet('/ai/snapshots');setTxt('snapshot-count',d.count||0);}catch(e){}
}
async function triggerTraining() {
  setTxt('training-status','⏳ Training started in background...');
  await apiPost('/ai/train',{}).catch(()=>{});
  setTimeout(()=>{setTxt('training-status','✓ Check /models/ for output.');loadModels();},2000);
}
async function loadModels() {
  try {
    const data=await apiGet('/ai/models');
    const el=$('models-list');
    if(!el) return;
    if(!data.models?.length){el.innerHTML='<div class="empty-state"><div class="empty-icon">📦</div>No models</div>';return;}
    el.innerHTML=data.models.map(m=>`<div class="cam-item"><div class="cam-info"><div class="cam-label">📦 ${m}</div></div><div class="cam-actions"><button class="btn btn-xs btn-accent" onclick="loadAIModel('${m}')">Load</button></div></div>`).join('');
  } catch(e){}
}
async function loadAIModel(name) {
  await apiPost(`/ai/model/load/${name}`,{}).catch(()=>{});
  toast(`Model '${name}' loaded!`);
}
async function uploadModel() {
  const input=$('model-file');
  if(!input?.files[0]){toast('Select a .xml or .onnx file',true);return;}
  const form=new FormData(); form.append('file',input.files[0]);
  const r=await fetch(`${API}/ai/model/upload`,{method:'POST',credentials:'include',headers:token?{'X-Session-Token':token}:{},body:form});
  const data=await r.json();
  toast(`Uploaded: ${data.model}`);
  loadModels();
}

// ════════════════════════════════════════════════════════════════════════════
// SETTINGS
// ════════════════════════════════════════════════════════════════════════════
async function loadSettings() {
  try {
    const data=await apiGet('/settings/');
    if(data.stream_key && $('cfg-stream-key'))  $('cfg-stream-key').value=data.stream_key;
    if(data.stream_url && $('cfg-stream-url'))  $('cfg-stream-url').value=data.stream_url;
    if(data.hotspot_ssid && $('cfg-ssid'))      $('cfg-ssid').value=data.hotspot_ssid;
    if(data.hotspot_pass && $('cfg-pass'))      $('cfg-pass').value=data.hotspot_pass;
    if(data.stream_key && $('st-key'))          $('st-key').value=data.stream_key;
    if(data.stream_url && $('st-url'))          $('st-url').value=data.stream_url;
    streamSettings.key=data.stream_key||'';
    streamSettings.url=data.stream_url||'';
  } catch(e){}
}

async function saveSettings() {
  await apiPost('/settings/',{
    stream_key:   $('cfg-stream-key')?.value||'',
    stream_url:   $('cfg-stream-url')?.value||'',
    hotspot_ssid: $('cfg-ssid')?.value||'SportsCaster',
    hotspot_pass: $('cfg-pass')?.value||'broadcast1',
  });
  toast('Settings saved!');
}

// ════════════════════════════════════════════════════════════════════════════
// TOAST notifications
// ════════════════════════════════════════════════════════════════════════════
function toast(msg, isError=false) {
  let el=$('toast-container');
  if(!el){
    el=document.createElement('div');
    el.id='toast-container';
    el.style.cssText='position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px';
    document.body.appendChild(el);
  }
  const t=document.createElement('div');
  t.style.cssText=`background:${isError?'var(--red)':'var(--green)'};color:#fff;padding:10px 18px;border-radius:8px;font-size:0.85rem;font-family:var(--font-b);box-shadow:0 4px 20px rgba(0,0,0,.4);max-width:320px;animation:slideIn 0.2s ease`;
  t.textContent=msg;
  el.appendChild(t);
  setTimeout(()=>t.remove(),3500);
}

// Inject toast CSS
const s=document.createElement('style');
s.textContent='@keyframes slideIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}';
document.head.appendChild(s);

// Expose needed functions to inline onclick handlers
window.toggleNav=toggleNav; window.goTo=goTo;
window.doLogin=doLogin; window.doLogout=doLogout;
window.detectUSB=detectUSB; window.setUsbActive=setUsbActive;
window.testIpCam=testIpCam; window.previewIpCam=previewIpCam;
window.saveIpCam=saveIpCam; window.previewMobile=previewMobile;
window.saveMobileCam=saveMobileCam; window.activateCam=activateCam;
window.deleteCam=deleteCam; window.loadSavedCams=loadSavedCams;
window.startMatch=startMatch; window.scoreEvt=scoreEvt; window.selectPlayer=selectPlayer;
window.savePlayers=savePlayers; window.loadPlayers=loadPlayers; window.loadSavedTeams=loadSavedTeams;
window.onPlatformChange=onPlatformChange; window.saveStreamSettings=saveStreamSettings;
window.startStream=startStream; window.stopStream=stopStream;
window.loadStreamLog=loadStreamLog; window.loadStreamDevices=loadStreamDevices;
window.startRecording=startRecording; window.stopRecording=stopRecording;
window.loadRecordings=loadRecordings; window.playRec=playRec; window.delRec=delRec;
window.setSpeed=setSpeed; window.stepFrame=stepFrame;
window.review_vid=review_vid_fn;
window.replay_vid=replay_vid; window.review_vid=review_vid_fn;
window.saveReview=saveReview; window.loadReviews=loadReviews;
window.playRev=playRev; window.delRev=delRev;
window.decisionOut=decisionOut; window.decisionNotOut=decisionNotOut;
window.startAI=startAI; window.stopAI=stopAI;
window.captureSnapshot=captureSnapshot; window.triggerTraining=triggerTraining;
window.loadModels=loadModels; window.loadAIModel=loadAIModel; window.uploadModel=uploadModel;
window.saveSettings=saveSettings;

// ════════════════════════════════════════════════════════════════════════════
// V6 ADDITIONS — Camera detect dropdown, Storage, AI player/ball, admin links
// ════════════════════════════════════════════════════════════════════════════

// ── Stream camera dropdown ────────────────────────────────────────────────
async function loadStreamDevices() {
  const info = $('stream-devices-info');
  const sel  = $('stream-cam-select');
  if (info) info.textContent = 'Detecting cameras...';
  try {
    const data = await apiGet('/cameras/detect');
    if (sel) {
      sel.innerHTML = data.cameras.map(c =>
        `<option value="${encodeURIComponent(c.url)}" data-type="${c.type}">${c.label}</option>`
      ).join('');
    }
    if (info) info.textContent = `${data.cameras.length} source(s) — Platform: ${data.platform}`;
  } catch(e) {
    if (info) info.textContent = 'Detection failed. Check FFmpeg is installed.';
  }
}

async function applyStreamCamera() {
  const sel = $('stream-cam-select');
  if (!sel) return;
  const encoded = sel.value;
  let url = encoded ? decodeURIComponent(encoded) : '';
  const customEl = $('stream-custom-url');
  if ((!url || url === 'ip') && customEl) url = customEl.value.trim();
  if (!url) { toast('Select or enter a camera source', true); return; }

  const customRow = $('stream-custom-url-row');
  if (customRow) customRow.style.display = (!encoded || encoded === 'ip') ? 'block' : 'none';

  try {
    await fetch(`${API}/cameras/activate-url?url=${encodeURIComponent(url)}`, {
      method:'POST', credentials:'include', headers: authHeaders()
    });
    toast(`Camera set: ${url}`);
  } catch(e) { toast('Failed to set camera: '+e.message, true); }
}

// ── Disk storage info ─────────────────────────────────────────────────────
async function loadStorage() {
  try {
    const data = await apiGet('/cameras/storage');
    const infoEl = $('storage-info');
    const warnEl = $('storage-warning');
    if (infoEl) {
      infoEl.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;text-align:center">
          <div><div style="font-size:1.4rem;font-weight:700;color:var(--accent)">${data.total_gb}</div><div style="font-size:0.72rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Total GB</div></div>
          <div><div style="font-size:1.4rem;font-weight:700;color:var(--yellow)">${data.used_gb}</div><div style="font-size:0.72rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Used GB</div></div>
          <div><div style="font-size:1.4rem;font-weight:700;color:${data.warning?'var(--red)':'var(--green)'}">${data.free_gb}</div><div style="font-size:0.72rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Free GB</div></div>
        </div>`;
    }
    if (warnEl) {
      warnEl.style.display = data.warning ? 'block' : 'none';
      if (data.warning) warnEl.textContent = `⚠ ${data.message}`;
    }
  } catch(e) {
    const infoEl = $('storage-info');
    if (infoEl) infoEl.textContent = 'Could not load disk info';
  }
}

// ── AI — Player detection ─────────────────────────────────────────────────
async function uploadPlayerPhoto() {
  const input = $('player-photo-input');
  if (!input?.files[0]) { toast('Select a photo first', true); return; }
  const form = new FormData();
  form.append('file', input.files[0]);
  try {
    const r = await fetch(`${API}/ai/player/upload`, {
      method:'POST', credentials:'include',
      headers: token ? {'X-Session-Token': token} : {},
      body: form
    });
    const data = await r.json();
    toast(`Photo uploaded: ${data.file}`);
  } catch(e) { toast('Upload failed: '+e.message, true); }
}

// ── AI — Ball detection ───────────────────────────────────────────────────
async function setBallType(type) {
  try {
    await fetch(`${API}/ai/ball/type?ball_type=${type}`, {
      method:'POST', credentials:'include', headers: authHeaders()
    });
    toast(`Ball type: ${type}`);
  } catch(e) { toast('Failed: '+e.message, true); }
}

async function startBallTracking() {
  try {
    await fetch(`${API}/ai/ball/start`, {
      method:'POST', credentials:'include', headers: authHeaders()
    });
    $('ball-ai-dot')?.classList.add('on');
    setTxt('ball-status-text', 'Active — Ball Detection');
    toast('Ball detection started');
  } catch(e) { toast('Failed: '+e.message, true); }
}

async function uploadBallImages() {
  const input = $('ball-img-input');
  if (!input?.files.length) { toast('Select image(s) first', true); return; }
  let count = 0;
  for (const file of input.files) {
    const form = new FormData();
    form.append('file', file);
    await fetch(`${API}/ai/ball/upload`, {
      method:'POST', credentials:'include',
      headers: token ? {'X-Session-Token': token} : {},
      body: form
    }).catch(()=>{});
    count++;
  }
  toast(`${count} image(s) uploaded`);
  loadSnapshots();
}

// ── Auto-load on navigation ───────────────────────────────────────────────
// Wrap goTo to auto-load data when navigating to certain tabs
(function() {
  const _orig = window.goTo;
  window.goTo = function(section, sub) {
    _orig(section, sub);
    if (section === 'recording') setTimeout(loadStorage, 100);
    if (section === 'streaming' && sub === 'live') setTimeout(loadStreamDevices, 100);
  };
})();

// ── Expose new functions ──────────────────────────────────────────────────
window.loadStreamDevices  = loadStreamDevices;
window.applyStreamCamera  = applyStreamCamera;
window.loadStorage        = loadStorage;
window.uploadPlayerPhoto  = uploadPlayerPhoto;
window.setBallType        = setBallType;
window.startBallTracking  = startBallTracking;
window.uploadBallImages   = uploadBallImages;
