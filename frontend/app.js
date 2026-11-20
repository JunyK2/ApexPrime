import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const cfg = window.APEX_CONFIG || {};
const $ = (id) => document.getElementById(id);
const el = {
  loginPanel: $('login-panel'), dashboard: $('dashboard'), loginForm: $('login-form'),
  loginError: $('login-error'), logout: $('logout'), session: $('session-state'),
};
let supabase = null;
let deviceId = 'redmi6a-main';
let refreshTimer = null;
let lowBatteryNotificationArmed = true;

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function relative(value) {
  if (!value) return 'Sem heartbeat';
  const sec = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (sec < 60) return `há ${sec}s`;
  if (sec < 3600) return `há ${Math.floor(sec / 60)} min`;
  return `há ${Math.floor(sec / 3600)} h ${Math.floor((sec % 3600) / 60)} min`;
}
function duration(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min`;
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}
function uptime(sec) {
  if (sec == null) return '—';
  const days = Math.floor(sec / 86400), hours = Math.floor((sec % 86400) / 3600), mins = Math.floor((sec % 3600) / 60);
  return days ? `${days}d ${hours}h` : `${hours}h ${mins}m`;
}
function showLogin(message = '') {
  el.loginPanel.classList.remove('hidden'); el.dashboard.classList.add('hidden');
  el.logout.classList.add('hidden'); el.session.textContent = 'Desconectado'; el.session.className = 'pill muted';
  el.loginError.textContent = message;
}
function showDashboard(email) {
  el.loginPanel.classList.add('hidden'); el.dashboard.classList.remove('hidden');
  el.logout.classList.remove('hidden'); el.session.textContent = email || 'Administrador'; el.session.className = 'pill good';
}
async function verifyAdmin(user) {
  const { data, error } = await supabase.from('apex_admins').select('user_id').eq('user_id', user.id).maybeSingle();
  if (error || !data) throw new Error('Este usuário não está cadastrado como administrador em apex_admins.');
}

function renderTimeline(heartbeats, latestSeen) {
  const host = $('timeline');
  const now = Date.now();
  const points = [...(heartbeats || [])].sort((a,b) => new Date(a.seen_at)-new Date(b.seen_at));
  const threshold = 180000;
  if (!points.length) {
    if (latestSeen && now - new Date(latestSeen).getTime() > threshold) {
      const last = new Date(latestSeen).getTime();
      const from = Math.max(now - 24*3600*1000, last + threshold);
      host.innerHTML = `<div class="timeline-row off"><div class="timeline-state offline">OFFLINE</div><div><div class="timeline-time">${fmtDate(from)} — ${fmtDate(now)}</div><div class="timeline-bar"><i style="width:100%"></i></div></div><div class="timeline-duration">${duration((now-from)/1000)}</div></div>`;
    } else {
      host.innerHTML = '<div class="empty">Nenhum heartbeat recebido ainda.</div>';
    }
    return;
  }
  const rows = [];
  let start = new Date(points[0].seen_at).getTime();
  let end = start;
  for (let i=1; i<points.length; i++) {
    const t = new Date(points[i].seen_at).getTime();
    if (t - end > threshold) {
      rows.push({state:'online', start, end});
      rows.push({state:'offline', start:end + threshold, end:t});
      start = t;
    }
    end = t;
  }
  rows.push({state:'online', start, end});
  const last = latestSeen ? new Date(latestSeen).getTime() : end;
  if (now - last > threshold) rows.push({state:'offline', start:last + threshold, end:now});
  const windowStart = now - 24*3600*1000;
  const filtered = rows.map(r => ({...r, start:Math.max(r.start,windowStart), end:Math.max(Math.max(r.start,windowStart),r.end)})).filter(r => r.end >= windowStart);
  const html = filtered.slice(-48).reverse().map(r => {
    const sec = Math.max(0, (r.end-r.start)/1000);
    const offline = r.state === 'offline';
    return `<div class="timeline-row ${offline?'off':''}"><div class="timeline-state ${offline?'offline':'online'}">${offline?'OFFLINE':'ONLINE'}</div><div><div class="timeline-time">${fmtDate(r.start)} — ${fmtDate(r.end)}</div><div class="timeline-bar"><i style="width:100%"></i></div></div><div class="timeline-duration">${duration(sec)}</div></div>`;
  }).join('');
  host.innerHTML = html || '<div class="empty">Sem intervalos para exibir.</div>';
}

async function refreshDashboard() {
  if (!supabase) return;
  const { data: devices, error } = await supabase.from('apex_devices').select('*').order('last_seen_at', {ascending:false}).limit(1);
  if (error) throw error;
  const device = devices?.[0];
  if (!device) {
    $('device-model').textContent = 'Nenhuma telemetria recebida. Rode o worker no Redmi.';
    $('online-badge').textContent = 'Aguardando';
    $('online-badge').className = 'pill muted';
    renderTimeline([], null);
    return;
  }
  deviceId = device.device_id;
  const seen = device.last_seen_at;
  const online = !!seen && (Date.now() - new Date(seen).getTime() <= 180000);
  $('device-name').textContent = device.device_name || 'Redmi 6A';
  $('device-model').textContent = `${device.device_model || 'Modelo não identificado'} · Android ${device.android_version || '—'}`;
  $('online-badge').textContent = online ? 'ONLINE' : 'OFFLINE';
  $('online-badge').className = `pill ${online?'good':'bad'}`;
  const pct = device.battery_percentage;
  $('battery-value').textContent = pct == null ? '—%' : `${pct}%`;
  $('battery-bar').style.width = `${Math.max(0,Math.min(100,pct||0))}%`;
  $('battery-bar').style.background = pct != null && pct < 40 ? 'var(--red)' : 'var(--green)';
  const batteryStatus = String(device.battery_status || '').toUpperCase();
  $('charging-value').textContent = batteryStatus === 'FULL' ? 'Conectado · carga completa' : (device.is_charging ? 'Carregando' : (device.battery_status || 'Não carregando'));
  $('temp-value').textContent = device.battery_temperature_c == null ? '— °C' : `${Number(device.battery_temperature_c).toFixed(1)} °C`;
  $('wifi-name').textContent = device.wifi_ssid || 'Desconectado';
  $('wifi-detail').textContent = `${device.wifi_frequency_mhz ? `${device.wifi_frequency_mhz} MHz` : 'Frequência —'} · ${device.wifi_ip || 'IP —'}`;
  const rssi = device.wifi_rssi_dbm == null ? null : Number(device.wifi_rssi_dbm);
  const quality = rssi == null ? 'sem leitura' : (rssi >= -55 ? 'excelente' : rssi >= -67 ? 'bom' : rssi >= -75 ? 'regular' : 'fraco');
  $('wifi-rssi').textContent = rssi == null ? '— dBm' : `${rssi} dBm · ${quality}`;
  $('wifi-speed').textContent = device.wifi_link_speed_mbps == null ? 'Velocidade —' : `${device.wifi_link_speed_mbps} Mbps de link`;
  $('uptime-value').textContent = uptime(device.uptime_seconds);
  $('last-seen').textContent = fmtDate(seen);
  $('last-seen-relative').textContent = relative(seen);
  $('device-ip').textContent = `IP local: ${device.wifi_ip || '—'}`;
  $('device-health').textContent = `Bateria: ${device.battery_health || '—'} · Wi-Fi: ${device.wifi_connected ? 'conectado' : 'sem conexão'}`;
  const batteryLow = pct != null && pct < 40;
  $('battery-alert').classList.toggle('hidden', !batteryLow);
  if (pct != null && pct >= 45) lowBatteryNotificationArmed = true;
  if (batteryLow && lowBatteryNotificationArmed && 'Notification' in window && Notification.permission === 'granted') {
    new Notification('ApexPrime — bateria baixa', {body:`Redmi 6A em ${pct}%. Conecte o carregador.`, icon:'./icon-192.png'});
    lowBatteryNotificationArmed = false;
  }

  const since = new Date(Date.now()-24*3600*1000).toISOString();
  const { data: heartbeats, error: hbError } = await supabase.from('device_heartbeats').select('seen_at,metadata').eq('device_id',deviceId).gte('seen_at',since).order('seen_at',{ascending:true}).limit(3000);
  if (hbError) throw hbError;
  renderTimeline(heartbeats, seen);

  const { data: groq } = await supabase.from('service_checks').select('checked_at,status,details,message').eq('service','GROQ').order('checked_at',{ascending:false}).limit(1).maybeSingle();
  if (groq) {
    const text = groq.details?.response || groq.message || groq.status;
    let summary = String(text);
    try {
      const cleaned = summary.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
      const parsed = JSON.parse(cleaned);
      summary = parsed.device_summary || parsed.summary || parsed.issues?.join(', ') || summary;
    } catch (_) {}
    $('groq-summary').textContent = summary.replace(/[{}"\\]/g,' ').replace(/\s+/g,' ').slice(0,100);
    $('groq-time').textContent = `${groq.status} · ${relative(groq.checked_at)}`;
  }
}

async function init() {
  if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) {
    showLogin('Configure frontend/config.js com SUPABASE_URL e SUPABASE_ANON_KEY.');
    return;
  }
  supabase = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
  const {data:{session}} = await supabase.auth.getSession();
  if (session?.user) {
    try { await verifyAdmin(session.user); showDashboard(session.user.email); await refreshDashboard(); }
    catch (e) { showLogin(e.message); }
  }
  supabase.auth.onAuthStateChange(async (_event, sessionNow) => {
    if (!sessionNow?.user) { showLogin(); return; }
    try { await verifyAdmin(sessionNow.user); showDashboard(sessionNow.user.email); await refreshDashboard(); }
    catch (e) { await supabase.auth.signOut(); showLogin(e.message); }
  });
  el.loginForm.addEventListener('submit', async (e) => {
    e.preventDefault(); el.loginError.textContent = 'Entrando...';
    const {error} = await supabase.auth.signInWithPassword({email:$('email').value.trim(),password:$('password').value});
    if (error) el.loginError.textContent = error.message;
  });
  el.logout.addEventListener('click', async () => { await supabase.auth.signOut(); });
  $('enable-notifications').addEventListener('click', async () => {
    if (!('Notification' in window)) {
      alert('Este navegador não oferece notificações. O alerta visual do painel continua disponível.');
      return;
    }
    const permission = await Notification.requestPermission();
    $('enable-notifications').textContent = permission === 'granted' ? 'Alertas ativados' : 'Permissão não concedida';
    if (permission === 'granted') await refreshDashboard();
  });
  $('refresh').addEventListener('click', async () => { $('refresh').textContent='Atualizando…'; try { await refreshDashboard(); } catch(e) { console.error(e); } finally { $('refresh').textContent='↻ Atualizar'; } });
  refreshTimer = setInterval(() => refreshDashboard().catch(console.error), 30000);
}

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('./sw.js').catch(console.error));
init().catch(e => showLogin(e.message));
