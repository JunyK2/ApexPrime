import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const cfg = window.APEX_CONFIG || {};
const $ = (id) => document.getElementById(id);
let supabase = null;
let currentUser = null;
let refreshTimer = null;
let refreshInFlight = false;
let lowBatteryNotificationArmed = true;
let cached = { account: null, trades: [], pending: [], runs: [], logs: [], checks: [], commands: [], settings: null, prompts: null, devices: [], heartbeats: [], ledger: [], geminiToday: 0, geminiTotal: 0 };
let replayTimer = null;
let replayIndex = 0;
let replayEvents = [];
let toastTimer = null;

const money = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const signedMoney = (value) => {
  const n = Number(value || 0);
  return `${n > 0 ? '+' : ''}${money(n, 4)} USDT`;
};
const fmtDate = (value, seconds = false) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
};
const relative = (value) => {
  if (!value) return 'Sem heartbeat';
  const sec = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (sec < 60) return `há ${sec}s`;
  if (sec < 3600) return `há ${Math.floor(sec / 60)} min`;
  return `há ${Math.floor(sec / 3600)} h ${Math.floor((sec % 3600) / 60)} min`;
};
const duration = (sec) => {
  sec = Math.max(0, Math.floor(sec || 0));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min`;
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
};
const uptime = (sec) => {
  if (sec == null) return '—';
  const days = Math.floor(sec / 86400), hours = Math.floor((sec % 86400) / 3600), mins = Math.floor((sec % 3600) / 60);
  return days ? `${days}d ${hours}h` : `${hours}h ${mins}m`;
};
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pill = (status) => {
  const s = String(status || '').toLowerCase();
  const cls = ['online','ok','completed','success','open','long'].includes(s) ? 'good' : ['offline','error','failed','short'].includes(s) ? 'bad' : ['warn','processing','running','pending','skipped'].includes(s) ? 'warn' : 'muted';
  return `<span class="pill ${cls}">${escapeHtml(String(status || '—').toUpperCase())}</span>`;
};
const localDayStart = () => {
  const d = new Date(); d.setHours(0, 0, 0, 0); return d.toISOString();
};
function notifyToast(message, type = 'info') {
  const node = $('toast');
  if (!node) return;
  node.textContent = message;
  node.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 6000);
}
function showLogin(message = '') {
  $('login-panel').classList.remove('hidden'); $('dashboard').classList.add('hidden');
  $('logout').classList.add('hidden'); $('session-state').textContent = 'Desconectado'; $('session-state').className = 'pill muted';
  $('login-error').textContent = message;
  if (refreshTimer) clearInterval(refreshTimer);
}
function showDashboard(email) {
  $('login-panel').classList.add('hidden'); $('dashboard').classList.remove('hidden');
  $('logout').classList.remove('hidden'); $('session-state').textContent = email || 'Administrador'; $('session-state').className = 'pill good';
}
async function verifyAdmin(user) {
  const { data, error } = await supabase.from('apex_admins').select('user_id').eq('user_id', user.id).maybeSingle();
  if (error || !data) throw new Error('Este usuário não está cadastrado como administrador em apex_admins.');
}
function activateTab(tabName) {
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabName));
  document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.id !== `tab-${tabName}`));
  if (location.hash !== `#${tabName}`) history.replaceState(null, '', `#${tabName}`);
}
function renderTimeline(heartbeats, latestSeen) {
  const host = $('timeline');
  const now = Date.now();
  const points = [...(heartbeats || [])].sort((a, b) => new Date(a.seen_at) - new Date(b.seen_at));
  const threshold = 180000;
  if (!points.length) {
    if (latestSeen && now - new Date(latestSeen).getTime() > threshold) {
      const last = new Date(latestSeen).getTime();
      const from = Math.max(now - 24 * 3600 * 1000, last + threshold);
      host.innerHTML = `<div class="timeline-row off"><div class="timeline-state offline">OFFLINE</div><div><div class="timeline-time">${fmtDate(from)} — ${fmtDate(now)}</div><div class="timeline-bar"><i style="width:100%"></i></div></div><div class="timeline-duration">${duration((now - from) / 1000)}</div></div>`;
    } else host.innerHTML = '<div class="empty">Nenhum heartbeat recebido ainda.</div>';
    return;
  }
  const rows = [];
  let start = new Date(points[0].seen_at).getTime();
  let end = start;
  for (let i = 1; i < points.length; i++) {
    const t = new Date(points[i].seen_at).getTime();
    if (t - end > threshold) {
      rows.push({ state: 'online', start, end });
      rows.push({ state: 'offline', start: end + threshold, end: t });
      start = t;
    }
    end = t;
  }
  rows.push({ state: 'online', start, end });
  const last = latestSeen ? new Date(latestSeen).getTime() : end;
  if (now - last > threshold) rows.push({ state: 'offline', start: last + threshold, end: now });
  const windowStart = now - 24 * 3600 * 1000;
  const filtered = rows.map((r) => ({ ...r, start: Math.max(r.start, windowStart), end: Math.max(Math.max(r.start, windowStart), r.end) })).filter((r) => r.end >= windowStart);
  host.innerHTML = filtered.slice(-48).reverse().map((r) => {
    const sec = Math.max(0, (r.end - r.start) / 1000), offline = r.state === 'offline';
    return `<div class="timeline-row ${offline ? 'off' : ''}"><div class="timeline-state ${offline ? 'offline' : 'online'}">${offline ? 'OFFLINE' : 'ONLINE'}</div><div><div class="timeline-time">${fmtDate(r.start)} — ${fmtDate(r.end)}</div><div class="timeline-bar"><i style="width:100%"></i></div></div><div class="timeline-duration">${duration(sec)}</div></div>`;
  }).join('') || '<div class="empty">Sem intervalos para exibir.</div>';
}
function renderDevice(device, heartbeats, groqCheck) {
  if (!device) {
    $('device-model').textContent = 'Nenhuma telemetria recebida. Rode o worker no Redmi.';
    $('online-badge').textContent = 'Aguardando'; $('online-badge').className = 'pill muted';
    $('worker-pill').textContent = 'Worker —'; renderTimeline([], null); return;
  }
  const seen = device.last_seen_at;
  const online = !!seen && Date.now() - new Date(seen).getTime() <= 180000;
  $('device-name').textContent = device.device_name || 'Redmi 6A';
  $('device-model').textContent = `${device.device_model || 'Modelo não identificado'} · Android ${device.android_version || '—'}`;
  $('online-badge').textContent = online ? 'ONLINE' : 'OFFLINE'; $('online-badge').className = `pill ${online ? 'good' : 'bad'}`;
  $('worker-pill').textContent = online ? 'Worker ativo' : 'Worker sem heartbeat'; $('worker-pill').className = `pill ${online ? 'good' : 'bad'}`;
  const pct = device.battery_percentage;
  $('battery-value-device').textContent = pct == null ? '—%' : `${pct}%`;
  $('battery-bar').style.width = `${Math.max(0, Math.min(100, Number(pct) || 0))}%`;
  $('battery-bar').style.background = pct != null && pct < 40 ? 'var(--red)' : 'var(--green)';
  const state = String(device.battery_status || '').toUpperCase();
  $('charging-value').textContent = state === 'FULL' ? 'Carga completa' : (device.is_charging ? 'Carregando' : (device.battery_status || 'Não carregando'));
  $('temp-value').textContent = device.battery_temperature_c == null ? '— °C' : `${Number(device.battery_temperature_c).toFixed(1)} °C`;
  $('wifi-name').textContent = device.wifi_ssid || 'Desconectado';
  $('wifi-detail').textContent = `${device.wifi_frequency_mhz ? `${device.wifi_frequency_mhz} MHz` : 'Frequência —'} · ${device.wifi_ip || 'IP —'}`;
  const rssi = device.wifi_rssi_dbm == null ? null : Number(device.wifi_rssi_dbm);
  const quality = rssi == null ? 'sem leitura' : (rssi >= -55 ? 'excelente' : rssi >= -67 ? 'bom' : rssi >= -75 ? 'regular' : 'fraco');
  $('wifi-rssi').textContent = rssi == null ? '— dBm' : `${rssi} dBm · ${quality}`;
  $('wifi-speed').textContent = device.wifi_link_speed_mbps == null ? 'Velocidade —' : `${device.wifi_link_speed_mbps} Mbps de link`;
  $('uptime-value').textContent = uptime(device.uptime_seconds);
  $('last-seen').textContent = fmtDate(seen); $('last-seen-relative').textContent = relative(seen);
  $('device-ip').textContent = `IP local: ${device.wifi_ip || '—'}`;
  $('device-health').textContent = `Bateria: ${device.battery_health || '—'} · Wi-Fi: ${device.wifi_connected ? 'conectado' : 'sem conexão'}`;
  const batteryLow = pct != null && pct < 40;
  $('battery-alert').classList.toggle('hidden', !batteryLow);
  if (pct != null && pct >= 45) lowBatteryNotificationArmed = true;
  if (batteryLow && lowBatteryNotificationArmed && 'Notification' in window && Notification.permission === 'granted') {
    new Notification('ApexPrime — bateria baixa', { body: `Redmi 6A em ${pct}%. Conecte o carregador.`, icon: './icon-192.png' });
    lowBatteryNotificationArmed = false;
  }
  renderTimeline(heartbeats || [], seen);
  if (groqCheck) {
    let summary = String(groqCheck.details?.response || groqCheck.message || groqCheck.status || 'Sem resumo');
    try {
      const cleaned = summary.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
      const parsed = JSON.parse(cleaned);
      summary = parsed.device_summary || parsed.summary || (parsed.issues || []).join(', ') || summary;
    } catch (_) { /* resumo pode ser texto */ }
    $('groq-summary').textContent = summary.replace(/[{}"\\]/g, ' ').replace(/\s+/g, ' ').slice(0, 150);
    $('groq-time').textContent = `${groqCheck.status} · ${relative(groqCheck.checked_at)}`;
  }
}
function pnlForTrade(trade, mark) {
  if (!mark || !trade || trade.remaining_quantity == null) return null;
  const entry = Number(trade.entry_price), qty = Number(trade.remaining_quantity);
  return (Number(mark) - entry) * qty * (trade.direction === 'LONG' ? 1 : -1);
}
function distancePct(price, level, direction, side) {
  if (!price || !level) return '—';
  const p = Number(price), l = Number(level);
  let d = (l - p) / p * 100;
  if (side === 'stop' && direction === 'LONG') d = (p - l) / p * 100;
  if (side === 'stop' && direction === 'SHORT') d = (l - p) / p * 100;
  return `${Math.max(0, d).toFixed(2)}%`;
}
function tradeCard(trade, mark, isHistory = false) {
  const pnl = pnlForTrade(trade, mark);
  const sign = trade.direction === 'LONG' ? 'long' : 'short';
  const pnlClass = pnl == null ? '' : pnl >= 0 ? 'positive' : 'negative';
  const stopDistance = mark ? distancePct(mark, trade.current_stop_loss, trade.direction, 'stop') : '—';
  const tp1Distance = mark ? `${Math.abs((Number(trade.tp1_price) - Number(mark)) / Number(mark) * 100).toFixed(2)}%` : '—';
  const tp2Distance = mark ? `${Math.abs((Number(trade.tp2_price) - Number(mark)) / Number(mark) * 100).toFixed(2)}%` : '—';
  const action = isHistory
    ? `<div class="action-group"><button class="ghost small" data-trade-details="${escapeHtml(trade.id)}">Detalhes</button><button class="ghost small" data-replay-trade="${escapeHtml(trade.id)}">Replay · 3s/evento</button></div>`
    : `<div class="action-group"><button class="ghost small" data-trade-details="${escapeHtml(trade.id)}">Detalhes</button><button class="danger-button small" data-close-trade="${escapeHtml(trade.id)}">Sair desta operação</button></div>`;
  return `<article class="card trade-card">
    <div class="trade-top"><div><span class="direction ${sign}">${escapeHtml(trade.direction)}</span><strong>${escapeHtml(trade.symbol || 'BTCUSDT')}</strong><small>${escapeHtml(trade.entry_type)} · ${fmtDate(trade.opened_at)}</small></div><div class="trade-right">${isHistory ? pill(trade.close_reason || 'CLOSED') : pill('OPEN')}<strong class="${pnlClass}">${pnl == null ? signedMoney(trade.realized_pnl_net) : signedMoney(pnl + Number(trade.realized_pnl_net || 0))}</strong></div></div>
    <div class="trade-levels"><div><span>ENTRADA</span><b>${money(trade.entry_price)}</b></div><div><span>STOP ATUAL</span><b>${money(trade.current_stop_loss)}</b><small>${stopDistance} até o stop</small></div><div><span>TP1</span><b>${money(trade.tp1_price)}</b><small>${tp1Distance} de distância</small></div><div><span>TP2</span><b>${money(trade.tp2_price)}</b><small>${tp2Distance} de distância</small></div></div>
    <div class="trade-bottom"><span>${Number(trade.leverage || 1)}x · Risco ${Number(trade.risk_pct || 0).toFixed(2)}% · ${Number(trade.remaining_quantity || 0).toFixed(6)} BTC restantes</span>${action}</div>
  </article>`;
}
function pendingCard(item) {
  return `<article class="card trade-card pending-card"><div class="trade-top"><div><span class="direction ${String(item.direction).toLowerCase()}">${escapeHtml(item.direction)}</span><strong>${escapeHtml(item.symbol || 'BTCUSDT')}</strong><small>${escapeHtml(item.entry_type)} · Criada ${fmtDate(item.created_at)}</small></div>${pill(item.status)}</div><div class="trade-levels"><div><span>ENTRADA</span><b>${money(item.entry_price)}</b></div><div><span>STOP</span><b>${money(item.stop_loss)}</b></div><div><span>TP1</span><b>${money(item.tp1_price)}</b></div><div><span>TP2</span><b>${money(item.tp2_price)}</b></div></div><div class="trade-bottom"><span>Expira ${fmtDate(item.expires_at)}</span><button class="danger-button small" data-cancel-pending="${escapeHtml(item.id)}">Cancelar entrada</button></div></article>`;
}
function renderPositions(mark) {
  const open = cached.trades.filter((t) => t.status === 'OPEN');
  const pend = cached.pending.filter((p) => ['PENDING', 'PROCESSING'].includes(p.status));
  $('overview-positions').innerHTML = open.length ? open.slice(0, 2).map((t) => tradeCard(t, mark)).join('') : '<div class="empty">Nenhuma operação virtual aberta.</div>';
  $('all-positions').innerHTML = open.length ? open.map((t) => tradeCard(t, mark)).join('') : '<div class="empty">Nenhuma operação aberta. O robô continua monitorando oportunidades.</div>';
  $('overview-pending').innerHTML = pend.length ? pend.slice(0, 2).map(pendingCard).join('') : '<div class="empty">Nenhuma entrada pendente.</div>';
  $('all-pending').innerHTML = pend.length ? pend.map(pendingCard).join('') : '<div class="empty">Nenhuma entrada pendente.</div>';
  $('open-count').textContent = `${open.length} operação(ões) aberta(s)`;
  const unrealized = open.reduce((sum, t) => sum + (pnlForTrade(t, mark) || 0), 0);
  $('unrealized-pnl').textContent = mark ? signedMoney(unrealized) : '— USDT';
  $('unrealized-pnl').className = unrealized >= 0 ? 'positive' : 'negative';
}
function renderHistory() {
  const closed = cached.trades.filter((t) => t.status === 'CLOSED');
  $('trade-history').innerHTML = closed.length ? closed.map((t) => tradeCard(t, null, true)).join('') : '<div class="empty">Ainda não há operações encerradas.</div>';
}
function renderRuns() {
  $('analysis-history').innerHTML = cached.runs.length ? cached.runs.map((run) => {
    const result = run.apex_table || {};
    const signal = result.signal || run.signal || run.trigger_direction || '—';
    const badge = signal === 'LONG' ? 'good' : signal === 'SHORT' ? 'bad' : 'muted';
    return `<article class="card list-card"><div class="list-card-head"><div><strong>${escapeHtml(signal)} · ${escapeHtml(run.symbol || 'BTCUSDT')}</strong><small>${fmtDate(run.created_at)} · ${escapeHtml(run.source)} · ${escapeHtml(run.analysis_mode || '—')}</small></div><span class="pill ${badge}">${escapeHtml(run.status)}</span></div><p>${escapeHtml(result.analysis_summary || run.error_message || run.market_snapshot?.trigger?.reason || 'Sem resumo disponível.')}</p><div class="list-card-footer"><span>${run.duration_ms ? `${run.duration_ms} ms` : ''} ${run.ai_model ? `· ${escapeHtml(run.ai_model)}` : ''}</span><button class="ghost small" data-run-details="${escapeHtml(run.id)}">Ver análise</button></div></article>`;
  }).join('') : '<div class="empty">Nenhuma análise registrada.</div>';
  $('command-history').innerHTML = tableCommands(cached.commands);
  $('test-commands').innerHTML = tableCommands(cached.commands.filter((c) => c.request_type === 'run_tests'));
}
function tableCommands(rows) {
  if (!rows?.length) return '<div class="empty">Nenhum comando registrado.</div>';
  return `<table><thead><tr><th>Comando</th><th>Status</th><th>Solicitado</th><th>Resultado</th></tr></thead><tbody>${rows.slice(0, 20).map((r) => `<tr><td>${escapeHtml(r.request_type)}</td><td>${pill(r.status)}</td><td>${fmtDate(r.requested_at)}</td><td>${escapeHtml(r.error_message || JSON.stringify(r.result || {}).slice(0, 120) || '—')}</td></tr>`).join('')}</tbody></table>`;
}
function renderTests() {
  $('service-tests').innerHTML = cached.checks.length ? cached.checks.map((c) => `<article class="card check-row"><div><strong>${escapeHtml(c.service)}</strong><small>${escapeHtml(c.message || '')} · ${fmtDate(c.checked_at)}</small></div><div>${c.latency_ms != null ? `<small>${c.latency_ms} ms</small>` : ''}${pill(c.status)}</div></article>`).join('') : '<div class="empty">Nenhum teste registrado. Clique em “Executar testes”.</div>';
}
function renderLogs() {
  const filter = $('log-filter').value;
  const rows = cached.logs.filter((l) => filter === 'ALL' || l.level === filter);
  $('logs-list').innerHTML = rows.length ? `<table><thead><tr><th>Nível</th><th>Componente</th><th>Mensagem</th><th>Horário</th></tr></thead><tbody>${rows.map((l) => `<tr><td>${pill(l.level)}</td><td>${escapeHtml(l.component)}</td><td class="log-message">${escapeHtml(l.message)}</td><td>${fmtDate(l.created_at, true)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Nenhum log para este filtro.</div>';
}
function fillSettings(settings, prompts) {
  if (!settings) return;
  $('setting-analysis-mode').value = settings.analysis_mode || 'chart_img';
  $('setting-symbol').value = settings.binance_symbol || 'BTCUSDT';
  $('setting-risk').value = settings.risk_per_trade_pct ?? 2;
  $('setting-leverage').value = settings.max_leverage ?? 20;
  $('setting-max-open').value = settings.max_open_trades ?? 1;
  $('setting-maker').value = Number(settings.maker_fee_rate || 0) * 100;
  $('setting-taker').value = Number(settings.taker_fee_rate || 0) * 100;
  $('setting-daily-loss').value = settings.max_daily_loss_pct ?? 6;
  $('setting-auto-trading').checked = settings.auto_trading_enabled !== false;
  $('setting-gemini-model').value = settings.gemini_model || 'gemini-4-hydrogen';
  $('setting-groq-model').value = settings.groq_model || 'openai/gpt-oss-120b';
  $('setting-timezone').value = settings.timezone || 'America/Sao_Paulo';
  $('setting-weekends').checked = !!settings.avoid_weekends;
  $('setting-groq').checked = !!settings.groq_enabled;
  $('setting-groq-alerts').checked = !!settings.groq_alerts_enabled;
  $('setting-funding').checked = settings.funding_enabled !== false;
  $('prompt-chart').value = prompts?.custom_chart_img_prompt || '';
  $('prompt-text').value = prompts?.custom_text_prompt || '';
  $('analysis-mode-label').textContent = settings.analysis_mode === 'text' ? 'Gráfico em Texto' : 'Chart IMG';
  $('auto-trading-label').textContent = settings.auto_trading_enabled === false ? 'Pausada' : 'Ativa';
  $('auto-trading-label').className = settings.auto_trading_enabled === false ? 'negative' : 'positive';
  $('daily-guard-label').textContent = `Proteção diária: ${Number(settings.max_daily_loss_pct ?? 6).toFixed(1)}% do saldo inicial (resultado contabilizado)`;
}
function renderDashboardMetrics(mark) {
  const account = cached.account || {};
  $('balance-value').textContent = `${money(account.balance, 4)} USDT`;
  $('balance-sub').textContent = `Saldo inicial: ${money(account.initial_balance, 2)} USDT · Taxas: ${money(account.total_fees, 4)}`;
  const today = cached.ledger.reduce((sum, row) => {
    if (['INITIAL_BALANCE', 'RESET'].includes(row.event_type)) return sum;
    return sum + Number(row.amount || 0);
  }, 0);
  $('today-pnl').textContent = signedMoney(today);
  $('today-pnl').className = today >= 0 ? 'positive' : 'negative';
  const closed = cached.trades.filter((t) => t.status === 'CLOSED');
  const wins = closed.filter((t) => Number(t.realized_pnl_net || 0) > 0).length;
  $('win-rate').textContent = closed.length ? `${(wins / closed.length * 100).toFixed(1)}%` : '—%';
  $('win-rate-sub').textContent = `${wins} vencedoras de ${closed.length} encerradas (até 100 recentes)`;
  renderPositions(mark);
}
async function fetchAll() {
  const since24 = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const [accountQ, tradesQ, pendingQ, runsQ, settingsQ, promptsQ, devicesQ, logsQ, checksQ, commandsQ, heartbeatsQ, ledgerQ, gemTodayQ, gemTotalQ] = await Promise.all([
    supabase.from('paper_accounts').select('*').eq('is_active', true).maybeSingle(),
    supabase.from('trades').select('*').order('opened_at', { ascending: false }).limit(100),
    supabase.from('pending_entries').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('system_runs').select('*').order('created_at', { ascending: false }).limit(30),
    supabase.from('apex_settings').select('*').eq('id', 1).maybeSingle(),
    supabase.from('apex_prompts').select('*').eq('id', 1).maybeSingle(),
    supabase.from('apex_devices').select('*').order('last_seen_at', { ascending: false }).limit(1),
    supabase.from('apex_logs').select('*').order('created_at', { ascending: false }).limit(100),
    supabase.from('service_checks').select('*').order('checked_at', { ascending: false }).limit(20),
    supabase.from('run_requests').select('*').order('requested_at', { ascending: false }).limit(20),
    supabase.from('device_heartbeats').select('seen_at,metadata').gte('seen_at', since24).order('seen_at', { ascending: true }).limit(3000),
    supabase.from('balance_ledger').select('amount,event_type,created_at').gte('created_at', localDayStart()).order('created_at', { ascending: true }).limit(1000),
    supabase.from('gemini_requests').select('id', { count: 'exact', head: true }).gte('created_at', localDayStart()),
    supabase.from('gemini_requests').select('id', { count: 'exact', head: true }),
  ]);
  const checks = [accountQ, tradesQ, pendingQ, runsQ, settingsQ, promptsQ, devicesQ, logsQ, checksQ, commandsQ, heartbeatsQ, ledgerQ];
  const failed = checks.find((q) => q.error);
  if (failed) throw failed.error;
  cached = {
    account: accountQ.data, trades: tradesQ.data || [], pending: pendingQ.data || [], runs: runsQ.data || [],
    settings: settingsQ.data, prompts: promptsQ.data, devices: devicesQ.data || [], logs: logsQ.data || [],
    checks: checksQ.data || [], commands: commandsQ.data || [], heartbeats: heartbeatsQ.data || [], ledger: ledgerQ.data || [],
    geminiToday: gemTodayQ.count ?? 0, geminiTotal: gemTotalQ.count ?? 0,
  };
  const latestRun = cached.runs.find((run) => run.market_snapshot?.mark_price) || cached.runs[0];
  const mark = latestRun?.market_snapshot?.mark_price ? Number(latestRun.market_snapshot.mark_price) : null;
  $('market-price').textContent = mark ? `${money(mark, 2)} USDT` : '— USDT';
  $('market-updated').textContent = latestRun?.created_at ? `Atualizado ${relative(latestRun.created_at)} · ${fmtDate(latestRun.created_at)}` : 'Aguardando leitura do mercado';
  const trigger = latestRun?.market_snapshot?.trigger || {};
  const triggerDirection = trigger.direction || '—';
  $('market-trigger').textContent = triggerDirection;
  $('market-trigger').className = triggerDirection === 'LONG' ? 'positive' : triggerDirection === 'SHORT' ? 'negative' : '';
  $('market-trigger-time').textContent = latestRun?.trigger_candle_open_time ? `Candle 1H · ${fmtDate(latestRun.trigger_candle_open_time)}` : 'Sem sinal recente';
  renderDashboardMetrics(mark);
  renderDevice(cached.devices[0], cached.heartbeats, cached.checks.find((c) => c.service === 'GROQ'));
  renderHistory(); renderRuns(); renderTests(); renderLogs(); fillSettings(cached.settings, cached.prompts);
  $('gemini-today').textContent = String(cached.geminiToday);
  $('gemini-total').textContent = String(cached.geminiTotal);
  $('gemini-count-overview').textContent = String(cached.geminiToday);
  const latestGemini = await supabase.from('gemini_requests').select('model,created_at,success').order('created_at', { ascending: false }).limit(1).maybeSingle();
  if (!latestGemini.error && latestGemini.data) {
    $('gemini-model-latest').textContent = latestGemini.data.model;
    $('gemini-last-time').textContent = `${latestGemini.data.success ? 'Concluída' : 'Falhou'} · ${relative(latestGemini.data.created_at)}`;
  } else { $('gemini-model-latest').textContent = '—'; $('gemini-last-time').textContent = 'Sem requisições'; }
}
async function refreshAll() {
  if (!supabase || refreshInFlight || document.visibilityState === 'hidden') return;
  refreshInFlight = true;
  try { await fetchAll(); }
  finally { refreshInFlight = false; }
}
async function enqueueCommand(requestType, payload = {}) {
  if (!currentUser) throw new Error('Sessão expirada. Entre novamente.');
  const { data, error } = await supabase.from('run_requests').insert({
    requested_by: currentUser.id,
    request_type: requestType,
    status: 'pending',
    payload,
  }).select().single();
  if (error) throw error;
  return data;
}
async function commandWithConfirm(type, payload, question, message) {
  if (!confirm(question)) return;
  try {
    await enqueueCommand(type, payload);
    notifyToast(message, 'success');
    await refreshAll();
  } catch (error) { notifyToast(error.message || 'Não foi possível enviar o comando.', 'error'); }
}
function openModal(title, html) {
  $('modal-title').textContent = title;
  $('modal-content').innerHTML = html;
  $('detail-modal').classList.remove('hidden');
}
function closeModal() { $('detail-modal').classList.add('hidden'); }
async function showTradeDetails(tradeId) {
  const trade = cached.trades.find((t) => t.id === tradeId);
  if (!trade) return;
  const { data: events, error } = await supabase.from('trade_events').select('*').eq('trade_id', tradeId).order('created_at', { ascending: true });
  if (error) throw error;
  const evHtml = (events || []).map((e) => `<div class="event-row"><span>${fmtDate(e.created_at, true)}</span><strong>${escapeHtml(e.event_type)}</strong><span>${e.price != null ? money(e.price) : '—'}</span></div>`).join('') || '<div class="empty">Sem eventos registrados.</div>';
  openModal(`Operação ${trade.direction} · ${trade.symbol}`, `<div class="detail-grid"><div><small>Entrada</small><b>${money(trade.entry_price)}</b></div><div><small>Stop atual</small><b>${money(trade.current_stop_loss)}</b></div><div><small>TP1 / TP2</small><b>${money(trade.tp1_price)} / ${money(trade.tp2_price)}</b></div><div><small>PnL líquido</small><b>${signedMoney(trade.realized_pnl_net)}</b></div></div><h3>Eventos da operação</h3>${evHtml}`);
}
async function showRunDetails(runId) {
  const run = cached.runs.find((r) => r.id === runId);
  if (!run) return;
  const apex = run.apex_table || {};
  const images = (run.chart_images || []).filter((i) => i.url && /^https:\/\//i.test(i.url));
  const imagesHtml = images.length ? `<div class="chart-images">${images.map((i) => `<a href="${escapeHtml(i.url)}" target="_blank" rel="noopener"><img src="${escapeHtml(i.url)}" loading="lazy" alt="Gráfico ${escapeHtml(i.timeframe)}"><span>${escapeHtml(i.timeframe)}</span></a>`).join('')}</div>` : '';
  const pre = escapeHtml(JSON.stringify(apex, null, 2));
  openModal(`Análise · ${run.signal || run.trigger_direction || 'Sem sinal'}`, `<p>${escapeHtml(apex.analysis_summary || run.error_message || 'Sem resumo.')}</p>${imagesHtml}<h3>APEX_TABLE</h3><pre class="json-view">${pre}</pre><details><summary>Resposta bruta do Gemini</summary><pre class="json-view">${escapeHtml(run.ai_raw_response || 'Sem resposta')}</pre></details><details><summary>Snapshot de mercado</summary><pre class="json-view">${escapeHtml(JSON.stringify(run.market_snapshot || {}, null, 2))}</pre></details>`);
}
async function startReplay(tradeId) {
  if (replayTimer) clearInterval(replayTimer);
  const { data, error } = await supabase.from('trade_events').select('*').eq('trade_id', tradeId).order('created_at', { ascending: true });
  if (error) throw error;
  replayEvents = data || [];
  replayIndex = 0;
  const trade = cached.trades.find((t) => t.id === tradeId);
  $('replay-panel').innerHTML = `<div class="replay-head"><div><strong>${escapeHtml(trade?.direction || '')} ${escapeHtml(trade?.symbol || 'BTCUSDT')}</strong><small>${replayEvents.length} eventos · avanço automático a cada 3 segundos</small></div><button id="stop-replay" class="ghost small">Parar replay</button></div><div class="replay-progress"><i id="replay-progress-bar"></i></div><div id="replay-stage" class="replay-stage">Preparando reprodução…</div>`;
  activateTab('history');
  if (!replayEvents.length) { $('replay-stage').textContent = 'Esta operação não possui eventos para reproduzir.'; return; }
  const renderStep = () => {
    const event = replayEvents[replayIndex];
    $('replay-stage').innerHTML = `<div class="eyebrow">EVENTO ${replayIndex + 1} / ${replayEvents.length}</div><h3>${escapeHtml(event.event_type)}</h3><p>${fmtDate(event.created_at, true)}</p><div class="detail-grid"><div><small>Preço</small><b>${event.price == null ? '—' : money(event.price)}</b></div><div><small>Quantidade</small><b>${event.quantity == null ? '—' : Number(event.quantity).toFixed(8)}</b></div><div><small>PnL bruto</small><b>${signedMoney(event.realized_pnl_gross)}</b></div><div><small>Taxa / funding</small><b>${money(event.fee, 5)} / ${money(event.funding, 5)}</b></div></div>`;
    $('replay-progress-bar').style.width = `${((replayIndex + 1) / replayEvents.length) * 100}%`;
    replayIndex += 1;
    if (replayIndex >= replayEvents.length) { clearInterval(replayTimer); replayTimer = null; $('replay-stage').insertAdjacentHTML('beforeend', '<p class="replay-finished">Replay concluído.</p>'); }
  };
  renderStep();
  if (replayEvents.length > 1) replayTimer = setInterval(renderStep, 3000);
  $('stop-replay').addEventListener('click', () => { if (replayTimer) clearInterval(replayTimer); replayTimer = null; $('replay-stage').insertAdjacentHTML('beforeend', '<p>Replay interrompido.</p>'); });
}
async function saveSettings(event) {
  event.preventDefault();
  const message = $('settings-message'); message.textContent = 'Salvando…'; message.className = 'form-message';
  const payload = {
    analysis_mode: $('setting-analysis-mode').value,
    binance_symbol: $('setting-symbol').value.trim().toUpperCase(),
    risk_per_trade_pct: Number($('setting-risk').value),
    max_leverage: Number($('setting-leverage').value),
    max_open_trades: Number($('setting-max-open').value),
    maker_fee_rate: Number($('setting-maker').value) / 100,
    taker_fee_rate: Number($('setting-taker').value) / 100,
    max_daily_loss_pct: Number($('setting-daily-loss').value),
    auto_trading_enabled: $('setting-auto-trading').checked,
    gemini_model: $('setting-gemini-model').value.trim(),
    groq_model: $('setting-groq-model').value.trim(),
    timezone: $('setting-timezone').value.trim(),
    avoid_weekends: $('setting-weekends').checked,
    groq_enabled: $('setting-groq').checked,
    groq_alerts_enabled: $('setting-groq-alerts').checked,
    funding_enabled: $('setting-funding').checked,
  };
  if (!payload.binance_symbol || !payload.gemini_model || !payload.groq_model || !payload.timezone) {
    message.textContent = 'Preencha o par, os modelos e o fuso horário.'; message.classList.add('error-text'); return;
  }
  if (payload.risk_per_trade_pct <= 0 || payload.risk_per_trade_pct > 2 || payload.max_leverage < 1 || payload.max_leverage > 20 || payload.max_open_trades < 1 || payload.max_open_trades > 5 || payload.max_daily_loss_pct < 0.5 || payload.max_daily_loss_pct > 20) {
    message.textContent = 'Risco deve ser entre 0 e 2%; alavancagem 1–20x; posições 1–5; perda contabilizada 0,5–20%.'; message.classList.add('error-text'); return;
  }
  const { error } = await supabase.from('apex_settings').update(payload).eq('id', 1);
  if (error) { message.textContent = error.message; message.classList.add('error-text'); return; }
  message.textContent = 'Configurações salvas. O Redmi aplicará na próxima leitura.'; message.classList.add('success-text');
  notifyToast('Configurações do robô atualizadas.', 'success');
  await refreshAll();
}
async function savePrompts(event) {
  event.preventDefault();
  const payload = {
    custom_chart_img_prompt: $('prompt-chart').value.trim() || null,
    custom_text_prompt: $('prompt-text').value.trim() || null,
  };
  const { error } = await supabase.from('apex_prompts').update(payload).eq('id', 1);
  const message = $('prompts-message');
  if (error) { message.textContent = error.message; message.className = 'form-message error-text'; return; }
  message.textContent = 'Prompts salvos. Campos vazios usam os prompts padrão.'; message.className = 'form-message success-text';
  notifyToast('Prompts atualizados.', 'success'); await refreshAll();
}
async function resetPrompts() {
  if (!confirm('Remover os prompts personalizados e voltar aos prompts padrão do projeto?')) return;
  const { error } = await supabase.from('apex_prompts').update({ custom_chart_img_prompt: null, custom_text_prompt: null }).eq('id', 1);
  const message = $('prompts-message');
  if (error) { message.textContent = error.message; message.className = 'form-message error-text'; return; }
  message.textContent = 'Prompts padrão restaurados.'; message.className = 'form-message success-text';
  await refreshAll();
}
async function init() {
  if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY || cfg.SUPABASE_URL.includes('SEU_PROJETO')) {
    showLogin('Configure frontend/config.js com SUPABASE_URL e SUPABASE_ANON_KEY.'); return;
  }
  supabase = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user) {
    try { currentUser = session.user; await verifyAdmin(currentUser); showDashboard(currentUser.email); await refreshAll(); }
    catch (e) { showLogin(e.message); }
  }
  supabase.auth.onAuthStateChange(async (_event, sessionNow) => {
    if (!sessionNow?.user) { currentUser = null; showLogin(); return; }
    try { currentUser = sessionNow.user; await verifyAdmin(currentUser); showDashboard(currentUser.email); await refreshAll(); }
    catch (e) { await supabase.auth.signOut(); showLogin(e.message); }
  });
  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault(); $('login-error').textContent = 'Entrando…';
    const { error } = await supabase.auth.signInWithPassword({ email: $('email').value.trim(), password: $('password').value });
    if (error) $('login-error').textContent = error.message;
  });
  $('logout').addEventListener('click', async () => { await supabase.auth.signOut(); });
  $('enable-notifications').addEventListener('click', async () => {
    if (!('Notification' in window)) { notifyToast('Este navegador não oferece notificações. O Telegram permanece disponível.', 'warn'); return; }
    const permission = await Notification.requestPermission();
    $('enable-notifications').textContent = permission === 'granted' ? 'Alertas ativados' : 'Permissão não concedida';
    if (permission === 'granted') await refreshAll();
  });
  $('refresh').addEventListener('click', async () => { $('refresh').textContent = 'Atualizando…'; try { await refreshAll(); notifyToast('Painel atualizado.', 'success'); } catch (e) { notifyToast(e.message, 'error'); } finally { $('refresh').textContent = '↻ Atualizar'; } });
  document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => activateTab(b.dataset.tab)));
  document.querySelectorAll('[data-open-tab]').forEach((b) => b.addEventListener('click', () => activateTab(b.dataset.openTab)));
  $('force-analysis').addEventListener('click', async () => {
    if (!confirm('Enviar um comando ao Redmi para solicitar uma análise Gemini agora? Isso consumirá uma requisição do modelo.')) return;
    try { await enqueueCommand('force_analysis'); notifyToast('Análise solicitada. O Redmi processará a fila em até 30 segundos.', 'success'); await refreshAll(); }
    catch (e) { notifyToast(e.message, 'error'); }
  });
  $('run-tests').addEventListener('click', async () => {
    if (!confirm('Executar os testes dos serviços? O Telegram receberá uma mensagem de teste e os provedores podem consumir requisições.')) return;
    try { await enqueueCommand('run_tests'); notifyToast('Testes enviados ao Redmi.', 'success'); await refreshAll(); }
    catch (e) { notifyToast(e.message, 'error'); }
  });
  $('close-all').addEventListener('click', () => commandWithConfirm('close_open_trade', {}, 'Fechar todas as operações virtuais abertas e cancelar entradas pendentes?', 'Comando de fechamento enviado ao Redmi.'));
  $('settings-form').addEventListener('submit', saveSettings);
  $('prompts-form').addEventListener('submit', savePrompts);
  $('reset-prompts').addEventListener('click', resetPrompts);
  $('log-filter').addEventListener('change', renderLogs);
  document.body.addEventListener('click', async (e) => {
    const close = e.target.closest('[data-close-trade]');
    const cancel = e.target.closest('[data-cancel-pending]');
    const replay = e.target.closest('[data-replay-trade]');
    const run = e.target.closest('[data-run-details]');
    const detail = e.target.closest('[data-trade-details]');
    if (close) await commandWithConfirm('close_trade', { trade_id: close.dataset.closeTrade }, 'Sair desta operação virtual pelo mark price atual?', 'Comando de saída enviado ao Redmi.');
    if (cancel) await commandWithConfirm('cancel_pending_entry', { pending_id: cancel.dataset.cancelPending }, 'Cancelar esta entrada virtual pendente?', 'Cancelamento enviado ao Redmi.');
    if (replay) { try { await startReplay(replay.dataset.replayTrade); } catch (err) { notifyToast(err.message, 'error'); } }
    if (run) { try { await showRunDetails(run.dataset.runDetails); } catch (err) { notifyToast(err.message, 'error'); } }
    if (detail) { try { await showTradeDetails(detail.dataset.tradeDetails); } catch (err) { notifyToast(err.message, 'error'); } }
    if (e.target.matches('[data-close-modal]')) closeModal();
  });
  if (location.hash && $(`tab-${location.hash.slice(1)}`)) activateTab(location.hash.slice(1));
  refreshTimer = setInterval(() => refreshAll().catch((e) => console.error('ApexPrime refresh:', e)), 30000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshAll().catch(console.error); });
}

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('./sw.js').catch(console.error));
init().catch((e) => showLogin(e.message));
