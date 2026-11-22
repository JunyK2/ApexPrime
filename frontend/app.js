import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const cfg = window.APEX_CONFIG || {};
const $ = (id) => document.getElementById(id);
let supabase = null;
let currentUser = null;
let refreshTimer = null;
let refreshInFlight = false;
let lowBatteryNotificationArmed = true;
let cached = { account: null, trades: [], pending: [], runs: [], logs: [], checks: [], commands: [], settings: null, prompts: null, devices: [], heartbeats: [], ledger: [], aiRequests: [], exports: [], opportunities: [], marketSnapshot: null, groqReports: [], geminiToday: 0, geminiTotal: 0, mark: null };
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
function resultLabel(category) {
  return ({ FULL_WIN: '🟢 WIN COMPLETO', PARTIAL_WIN: '🟢 WIN PARCIAL', LOSS: '🔴 LOSS', BREAKEVEN: '🟡 BREAK EVEN' })[category] || category || 'CLOSED';
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
  const provider = String(trade.analysis_provider || 'GEMINI').toUpperCase();
  const source = trade.analysis_source === 'manual_external' ? 'análise manual externa' : (trade.analysis_source || 'automática');
  const attribution = `${provider} · ${trade.analysis_model || 'modelo não registrado'} · ${trade.analysis_mode || 'gráfico —'} · ${source}`;
  const statusBadge = isHistory ? resultLabel(trade.result_category) : (trade.break_even_moved ? 'STOP PROTEGIDO' : 'OPEN');
  return `<article class="card trade-card">
    <div class="trade-top"><div><span class="direction ${sign}">${escapeHtml(trade.direction)}</span><strong>${escapeHtml(trade.symbol || 'BTCUSDT')}</strong><small>${escapeHtml(trade.entry_type)} · ${fmtDate(trade.opened_at)}</small><small class="trade-attribution">${escapeHtml(attribution)}</small></div><div class="trade-right">${pill(statusBadge)}<strong class="${pnlClass}">${pnl == null ? signedMoney(trade.realized_pnl_net) : signedMoney(pnl + Number(trade.realized_pnl_net || 0))}</strong></div></div>
    <div class="trade-levels"><div><span>ENTRADA</span><b>${money(trade.entry_price)}</b></div><div><span>STOP ATUAL</span><b>${money(trade.current_stop_loss)}</b><small>${trade.break_even_moved ? 'Breakeven protegido' : `${stopDistance} até o stop`}</small></div><div><span>TP1 · 50%</span><b>${money(trade.tp1_price)}</b><small>${trade.tp1_hit ? 'Parcial executada' : `${tp1Distance} de distância`}</small></div><div><span>TP2</span><b>${money(trade.tp2_price)}</b><small>${tp2Distance} de distância</small></div></div>
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
  renderBalanceLedger();
}
function renderBalanceLedger() {
  const rows = cached.ledger.filter((r) => r.event_type === 'MANUAL_ADJUSTMENT' || r.event_type === 'INITIAL_BALANCE' || r.event_type === 'RESET');
  $('balance-ledger').innerHTML = rows.length ? `<table><thead><tr><th>Tipo</th><th>Descrição</th><th>Valor</th><th>Saldo após</th><th>Data</th></tr></thead><tbody>${rows.slice(0, 100).map((r) => `<tr><td>${escapeHtml(r.event_type)}</td><td>${escapeHtml(r.description || '—')}</td><td class="${Number(r.amount) >= 0 ? 'positive' : 'negative'}">${signedMoney(r.amount)}</td><td>${money(r.balance_after, 4)}</td><td>${fmtDate(r.created_at, true)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Nenhuma adição manual de saldo registrada.</div>';
}

function renderRuns() {
  $('analysis-history').innerHTML = cached.runs.length ? cached.runs.map((run) => {
    const result = run.apex_table || {};
    const signal = result.signal || run.signal || run.trigger_direction || '—';
    const badge = signal === 'LONG' ? 'good' : signal === 'SHORT' ? 'bad' : 'muted';
    const provider = run.analysis_provider || (run.source === 'manual_external' ? 'EXTERNAL' : '—');
    const graphType = run.chart_source_type || run.analysis_mode || '—';
    return `<article class="card list-card"><div class="list-card-head"><div><strong>${escapeHtml(signal)} · ${escapeHtml(run.symbol || 'BTCUSDT')}</strong><small>${fmtDate(run.created_at)} · ${escapeHtml(run.source)} · ${escapeHtml(graphType)} · ${escapeHtml(provider)}</small></div><span class="pill ${badge}">${escapeHtml(run.status)}</span></div><p>${escapeHtml(result.analysis_summary || run.error_message || run.market_snapshot?.trigger?.reason || 'Sem resumo disponível.')}</p><div class="list-card-footer"><span>${run.duration_ms ? `${run.duration_ms} ms` : ''} ${run.analysis_model || run.ai_model ? `· ${escapeHtml(run.analysis_model || run.ai_model)}` : ''}</span><button class="ghost small" data-run-details="${escapeHtml(run.id)}">Ver análise</button></div></article>`;
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
function renderExports() {
  $('exports-list').innerHTML = cached.exports.length ? cached.exports.map((item) => {
    const files = Array.isArray(item.files) ? item.files : [];
    const links = files.map((f) => `<div class="export-image-action"><a class="export-image-link" href="${escapeHtml(f.url)}" target="_blank" rel="noopener">Abrir ${escapeHtml(f.timeframe)}</a><button class="ghost tiny" data-download-image="${escapeHtml(f.url)}" data-image-name="${escapeHtml(item.symbol)}-${escapeHtml(f.timeframe)}">Baixar</button></div>`).join('');
    return `<article class="card export-row"><div><strong>${item.export_type === 'TEXT_CHART' ? 'Gráfico em texto' : 'Imagens Chart IMG · 800×600'}</strong><small>${escapeHtml(item.symbol)} · ${fmtDate(item.reference_at || item.created_at)} · ${escapeHtml(item.status)}</small></div>${item.export_type === 'TEXT_CHART' ? `<button class="ghost small" data-download-export="${escapeHtml(item.id)}">Baixar TXT</button>` : `<div class="export-links">${links || 'Sem imagens'}</div>`}</article>`;
  }).join('') : '<div class="empty">Nenhum gráfico exportado ainda.</div>';
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
  $('setting-ai-strategy').value = settings.ai_provider_strategy || 'auto';
  $('setting-fixed-provider').value = settings.fixed_ai_provider || 'gemini';
  $('setting-fixed-model').value = settings.fixed_ai_model || '';
  $('setting-openrouter-model').value = settings.openrouter_model || 'openrouter/free';
  $('setting-groq-interval').value = settings.groq_health_interval_hours ?? 4;
  $('setting-minimum-size').checked = settings.simulate_exchange_minimum !== false;
  $('setting-min-notional').value = settings.minimum_notional_usdt ?? 100;
  $('setting-volume-mult').value = settings.trigger_volume_multiplier ?? 1.5;
  $('setting-sweep-len').value = settings.trigger_sweep_length ?? 16;
  $('setting-disp-mult').value = settings.trigger_displacement_multiplier ?? 1.5;
  $('setting-cooldown').value = settings.trigger_cooldown ?? 3;
  $('setting-min-score').value = String(settings.trigger_min_score ?? 2);
  $('prompt-chart').value = prompts?.custom_chart_img_prompt || '';
  $('prompt-text').value = prompts?.custom_text_prompt || '';
  $('analysis-mode-label').textContent = settings.analysis_mode === 'text' ? 'Gráfico em Texto' : 'Chart IMG';
  $('auto-trading-label').textContent = settings.auto_trading_enabled === false ? 'Pausada' : 'Ativa';
  $('auto-trading-label').className = settings.auto_trading_enabled === false ? 'negative' : 'positive';
  $('daily-guard-label').textContent = `Proteção diária: ${Number(settings.max_daily_loss_pct ?? 6).toFixed(1)}% do saldo inicial (resultado contabilizado)`;
  $('strategy-scan-label').textContent = `Scan a cada 15 min · candle 1H · Groq a cada ${settings.groq_health_interval_hours ?? 4}h`;
}
function canvasContext(canvas) {
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(280, Math.floor(rect.width || canvas.clientWidth || 600));
  const height = Number(canvas.getAttribute('height')) || 180;
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  canvas.width = width * dpr; canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}
function drawBatteryChart() {
  const target = $('battery-chart');
  const c = canvasContext(target);
  if (!c) return;
  const { ctx, width, height } = c;
  const series = cached.heartbeats.map((h) => ({
    t: new Date(h.seen_at).getTime(),
    v: Number(h.metadata?.battery_percentage),
    charging: !!h.metadata?.is_charging,
  })).filter((p) => Number.isFinite(p.v));
  const left = 34, right = width - 10, top = 12, bottom = height - 24;
  ctx.strokeStyle = '#26313a'; ctx.lineWidth = 1;
  for (let level = 0; level <= 100; level += 25) {
    const y = bottom - (level / 100) * (bottom - top);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillStyle = '#82909c'; ctx.font = '9px sans-serif'; ctx.fillText(`${level}%`, 2, y + 3);
  }
  if (series.length < 2) {
    ctx.fillStyle = '#82909c'; ctx.font = '11px sans-serif'; ctx.fillText('Aguardando mais amostras de bateria…', left + 5, height / 2);
    $('battery-eta').textContent = 'Autonomia: calculando';
    $('battery-chart-note').textContent = `${series.length} amostra(s) disponível(is); são necessárias ao menos duas.`;
    return;
  }
  const minT = series[0].t, maxT = Math.max(series[series.length - 1].t, minT + 1);
  ctx.beginPath();
  series.forEach((p, i) => {
    const x = left + ((p.t - minT) / (maxT - minT)) * (right - left);
    const y = bottom - (p.v / 100) * (bottom - top);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#49d49a'; ctx.lineWidth = 2; ctx.stroke();
  const last = series[series.length - 1];
  const lastX = right, lastY = bottom - (last.v / 100) * (bottom - top);
  ctx.fillStyle = '#49d49a'; ctx.beginPath(); ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2); ctx.fill();

  // Linear regression over recent battery readings estimates a trend, not a guarantee.
  const cutoff = Date.now() - 6 * 3600 * 1000;
  const recent = series.filter((p) => p.t >= cutoff);
  let slopePerHour = 0;
  if (recent.length >= 3) {
    const x = recent.map((p) => (p.t - recent[0].t) / 3600000);
    const y = recent.map((p) => p.v);
    const meanX = x.reduce((a, b) => a + b, 0) / x.length;
    const meanY = y.reduce((a, b) => a + b, 0) / y.length;
    const numerator = x.reduce((sum, v, i) => sum + (v - meanX) * (y[i] - meanY), 0);
    const denominator = x.reduce((sum, v) => sum + (v - meanX) ** 2, 0);
    if (denominator > 0) slopePerHour = numerator / denominator;
  }
  const device = cached.devices[0] || {};
  let eta = 'Autonomia: sem tendência suficiente';
  if (device.is_charging && slopePerHour > 0.4 && last.v < 99) eta = `Carga completa em ~${((100 - last.v) / slopePerHour).toFixed(1)}h`;
  else if (!device.is_charging && slopePerHour < -0.4) eta = `Restante: ~${(last.v / -slopePerHour).toFixed(1)}h`;
  $('battery-eta').textContent = eta;
  $('battery-chart-note').textContent = `Última leitura ${last.v.toFixed(0)}% · tendência ${slopePerHour > 0 ? '+' : ''}${slopePerHour.toFixed(2)} pontos/h · estimativa linear sujeita a variação de uso.`;
}
function drawOpportunityChart() {
  const c = canvasContext($('opportunity-chart'));
  if (!c) return;
  const { ctx, width, height } = c;
  const rows = [...cached.opportunities].sort((a, b) => new Date(a.candle_open_time) - new Date(b.candle_open_time));
  const left = 28, right = width - 10, top = 12, bottom = height - 20;
  ctx.strokeStyle = '#26313a'; ctx.fillStyle = '#82909c'; ctx.font = '9px sans-serif';
  for (let score = 0; score <= 3; score++) {
    const y = bottom - (score / 3) * (bottom - top);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillText(String(score), 9, y + 3);
  }
  const hits = rows.filter((r) => r.direction === 'LONG' || r.direction === 'SHORT');
  $('opportunity-count').textContent = `${hits.length} sinais / ${rows.length} candles`;
  $('opportunity-note').textContent = `LONG ${rows.filter((r) => r.direction === 'LONG').length} · SHORT ${rows.filter((r) => r.direction === 'SHORT').length} · sem gatilho ${rows.filter((r) => r.direction === 'NONE').length}.`;
  if (!rows.length) { ctx.fillStyle = '#82909c'; ctx.fillText('Aguardando candles analisados…', left + 5, height / 2); return; }
  const maxCount = rows.length - 1 || 1;
  rows.forEach((row, i) => {
    const x = left + (i / maxCount) * (right - left);
    const score = Math.max(0, Math.min(3, Number(row.score) || 0));
    const y = bottom - (score / 3) * (bottom - top);
    ctx.fillStyle = row.direction === 'LONG' ? '#49d49a' : row.direction === 'SHORT' ? '#f07878' : '#778390';
    ctx.beginPath(); ctx.arc(x, y, row.direction === 'NONE' ? 2 : 4, 0, Math.PI * 2); ctx.fill();
  });
}
function drawOpenTradeChart(mark) {
  const card = $('overview-trade-chart-card');
  const trade = cached.trades.find((t) => t.status === 'OPEN');
  const snapshot = cached.marketSnapshot;
  if (!trade || !snapshot?.candles?.length) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  const candles = snapshot.candles.slice(-70);
  const levels = [
    { name: 'ENTRADA', value: Number(trade.entry_price), color: '#e8b75e', dash: [] },
    { name: trade.break_even_moved ? 'STOP BE' : 'STOP', value: Number(trade.current_stop_loss), color: '#f07878', dash: [5, 3] },
    { name: 'TP1 50%', value: Number(trade.tp1_price), color: '#5fb5ea', dash: [3, 3] },
    { name: 'TP2', value: Number(trade.tp2_price), color: '#49d49a', dash: [5, 3] },
  ].filter((l) => Number.isFinite(l.value) && l.value > 0);
  const currentMark = Number(snapshot.mark_price || mark || candles[candles.length - 1].close);
  levels.push({ name: 'MARK', value: currentMark, color: '#d7e1e8', dash: [2, 3] });
  const minValue = Math.min(...candles.map((x) => Number(x.low)), ...levels.map((l) => l.value));
  const maxValue = Math.max(...candles.map((x) => Number(x.high)), ...levels.map((l) => l.value));
  const padding = Math.max((maxValue - minValue) * 0.08, maxValue * 0.0005);
  const min = minValue - padding, max = maxValue + padding;
  const c = canvasContext($('open-trade-chart'));
  if (!c) return;
  const { ctx, width, height } = c;
  const left = 8, right = width - 72, top = 14, bottom = height - 20;
  const yOf = (v) => bottom - ((v - min) / (max - min)) * (bottom - top);
  ctx.strokeStyle = '#202a32'; ctx.fillStyle = '#8c9aa6'; ctx.font = '9px sans-serif';
  for (let i = 0; i <= 4; i++) {
    const y = top + (i / 4) * (bottom - top);
    const value = max - (i / 4) * (max - min);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillText(money(value, 0), right + 4, y + 3);
  }
  const step = (right - left) / candles.length;
  const bodyWidth = Math.max(2, Math.min(8, step * 0.65));
  candles.forEach((k, i) => {
    const x = left + step * i + step / 2;
    const open = Number(k.open), close = Number(k.close), high = Number(k.high), low = Number(k.low);
    const up = close >= open;
    const color = up ? '#49d49a' : '#f07878';
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, yOf(high)); ctx.lineTo(x, yOf(low)); ctx.stroke();
    const y1 = yOf(Math.max(open, close)), y2 = yOf(Math.min(open, close));
    ctx.fillRect(x - bodyWidth / 2, y1, bodyWidth, Math.max(1.3, y2 - y1));
  });
  levels.forEach((level) => {
    const y = yOf(level.value);
    ctx.save(); ctx.strokeStyle = level.color; ctx.setLineDash(level.dash); ctx.lineWidth = level.name === 'MARK' ? 1 : 1.4;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke(); ctx.restore();
    ctx.fillStyle = level.color; ctx.font = 'bold 9px sans-serif'; ctx.fillText(`${level.name} ${money(level.value, 1)}`, left + 4, Math.max(10, y - 4));
  });
  const floating = (pnlForTrade(trade, currentMark) || 0) + Number(trade.realized_pnl_net || 0);
  $('trade-chart-pnl').textContent = `PnL estimado: ${signedMoney(floating)}`;
  $('trade-chart-pnl').className = floating >= 0 ? 'positive' : 'negative';
  $('trade-chart-note').textContent = `${trade.direction} · entrada ${money(trade.entry_price)} · ${trade.tp1_hit ? 'TP1 executado; 50% já realizado' : 'TP1 ainda pendente'} · ${trade.break_even_moved ? 'stop movido para breakeven' : 'stop inicial ativo'} · PnL indicativo pelo mark price, antes de eventuais custos de saída · dados ${relative(snapshot.updated_at)}.`;
}
function renderDashboardMetrics(mark) {
  const account = cached.account || {};
  $('balance-value').textContent = `${money(account.balance, 4)} USDT`;
  $('balance-sub').textContent = `Saldo inicial: ${money(account.initial_balance, 2)} USDT · Taxas: ${money(account.total_fees, 4)}`;
  const todayStart = new Date(localDayStart()).getTime();
  const today = cached.ledger.filter((row) => new Date(row.created_at).getTime() >= todayStart).reduce((sum, row) => {
    if (['INITIAL_BALANCE', 'RESET'].includes(row.event_type)) return sum;
    return sum + Number(row.amount || 0);
  }, 0);
  $('today-pnl').textContent = signedMoney(today);
  $('today-pnl').className = today >= 0 ? 'positive' : 'negative';
  const closed = cached.trades.filter((t) => t.status === 'CLOSED');
  const provider = $('winrate-filter')?.value || 'ALL';
  const allWins = closed.filter((t) => Number(t.realized_pnl_net || 0) > 0).length;
  const filtered = provider === 'ALL' ? closed : closed.filter((t) => String(t.analysis_provider || 'GEMINI').toUpperCase() === provider);
  const wins = filtered.filter((t) => Number(t.realized_pnl_net || 0) > 0).length;
  const pct = (rows, count) => rows.length ? `${(count / rows.length * 100).toFixed(1)}%` : '—%';
  $('win-rate').textContent = pct(filtered, wins);
  $('win-rate-sub').textContent = provider === 'ALL' ? `${wins} vencedoras de ${filtered.length} encerradas` : `${wins} vencedoras de ${filtered.length} · filtro ${provider}`;
  $('win-rate-general').textContent = `Geral: ${pct(closed, allWins)} (${allWins}/${closed.length})`;
  renderPositions(mark);
  drawBatteryChart(); drawOpportunityChart(); drawOpenTradeChart(mark);
}
async function fetchAll() {
  const since24 = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const [accountQ, tradesQ, pendingQ, runsQ, settingsQ, promptsQ, devicesQ, logsQ, checksQ,
    commandsQ, heartbeatsQ, ledgerQ, aiTodayQ, aiTotalQ, aiQ, exportsQ, opportunitiesQ,
    marketQ, groqReportsQ] = await Promise.all([
    supabase.from('paper_accounts').select('*').eq('is_active', true).maybeSingle(),
    supabase.from('trades').select('*').order('opened_at', { ascending: false }).limit(150),
    supabase.from('pending_entries').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('system_runs').select('*').order('created_at', { ascending: false }).limit(40),
    supabase.from('apex_settings').select('*').eq('id', 1).maybeSingle(),
    supabase.from('apex_prompts').select('*').eq('id', 1).maybeSingle(),
    supabase.from('apex_devices').select('*').order('last_seen_at', { ascending: false }).limit(1),
    supabase.from('apex_logs').select('*').order('created_at', { ascending: false }).limit(120),
    supabase.from('service_checks').select('*').order('checked_at', { ascending: false }).limit(30),
    supabase.from('run_requests').select('*').order('requested_at', { ascending: false }).limit(30),
    supabase.from('device_heartbeats').select('seen_at,metadata').gte('seen_at', since24).order('seen_at', { ascending: true }).limit(3000),
    supabase.from('balance_ledger').select('amount,event_type,created_at,description,balance_after').order('created_at', { ascending: false }).limit(500),
    supabase.from('ai_requests').select('id', { count: 'exact', head: true }).gte('created_at', localDayStart()),
    supabase.from('ai_requests').select('id', { count: 'exact', head: true }),
    supabase.from('ai_requests').select('*').order('created_at', { ascending: false }).limit(80),
    supabase.from('apex_exports').select('id,export_type,status,symbol,reference_at,files,error_message,created_at').order('created_at', { ascending: false }).limit(20),
    supabase.from('opportunity_events').select('*').order('candle_open_time', { ascending: false }).limit(180),
    supabase.from('market_snapshots').select('*').order('updated_at', { ascending: false }).limit(1),
    supabase.from('groq_reports').select('*').order('requested_at', { ascending: false }).limit(5),
  ]);
  const queries = [accountQ, tradesQ, pendingQ, runsQ, settingsQ, promptsQ, devicesQ, logsQ, checksQ,
    commandsQ, heartbeatsQ, ledgerQ, aiTodayQ, aiTotalQ, aiQ, exportsQ, opportunitiesQ, marketQ, groqReportsQ];
  const failed = queries.find((q) => q.error);
  if (failed) throw failed.error;
  cached = {
    ...cached,
    account: accountQ.data, trades: tradesQ.data || [], pending: pendingQ.data || [], runs: runsQ.data || [],
    settings: settingsQ.data, prompts: promptsQ.data, devices: devicesQ.data || [], logs: logsQ.data || [],
    checks: checksQ.data || [], commands: commandsQ.data || [], heartbeats: heartbeatsQ.data || [], ledger: ledgerQ.data || [],
    aiRequests: aiQ.data || [], exports: exportsQ.data || [], opportunities: opportunitiesQ.data || [],
    marketSnapshot: marketQ.data?.[0] || null, groqReports: groqReportsQ.data || [],
    geminiToday: aiTodayQ.count ?? 0, geminiTotal: aiTotalQ.count ?? 0,
  };
  const latestRun = cached.runs.find((run) => run.market_snapshot?.mark_price) || cached.runs[0];
  const mark = cached.marketSnapshot?.mark_price ? Number(cached.marketSnapshot.mark_price)
    : latestRun?.market_snapshot?.mark_price ? Number(latestRun.market_snapshot.mark_price) : null;
  cached.mark = mark;
  $('market-price').textContent = mark ? `${money(mark, 2)} USDT` : '— USDT';
  const updatedAt = cached.marketSnapshot?.updated_at || latestRun?.created_at;
  $('market-updated').textContent = updatedAt ? `Atualizado ${relative(updatedAt)} · ${fmtDate(updatedAt)}` : 'Aguardando leitura do mercado';
  const trigger = latestRun?.market_snapshot?.trigger || {};
  const triggerDirection = trigger.direction || '—';
  $('market-trigger').textContent = triggerDirection;
  $('market-trigger').className = triggerDirection === 'LONG' ? 'positive' : triggerDirection === 'SHORT' ? 'negative' : '';
  $('market-trigger-time').textContent = latestRun?.trigger_candle_open_time ? `Candle 1H · ${fmtDate(latestRun.trigger_candle_open_time)}` : 'Sem sinal recente';
  renderDashboardMetrics(mark);
  renderDevice(cached.devices[0], cached.heartbeats, cached.checks.find((c) => c.service === 'GROQ'));
  renderHistory(); renderRuns(); renderTests(); renderLogs(); renderExports(); fillSettings(cached.settings, cached.prompts);
  $('gemini-today').textContent = String(cached.geminiToday);
  $('gemini-total').textContent = String(cached.geminiTotal);
  $('gemini-count-overview').textContent = String(cached.geminiToday);
  const latestAi = cached.aiRequests[0];
  if (latestAi) {
    $('gemini-model-latest').textContent = `${latestAi.provider} · ${latestAi.model}`;
    $('gemini-last-time').textContent = `${latestAi.success ? 'Concluída' : 'Falhou'} · ${relative(latestAi.created_at)}`;
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
  const [{ data: events, error }, { data: review, error: reviewError }] = await Promise.all([
    supabase.from('trade_events').select('*').eq('trade_id', tradeId).order('created_at', { ascending: true }),
    supabase.from('trade_reviews').select('*').eq('trade_id', tradeId).maybeSingle(),
  ]);
  if (error) throw error;
  if (reviewError) console.warn('Trade review indisponível:', reviewError.message);
  const evHtml = (events || []).map((e) => `<div class="event-row"><span>${fmtDate(e.created_at, true)}</span><strong>${escapeHtml(e.event_type)}</strong><span>${e.price != null ? money(e.price) : '—'}</span></div>`).join('') || '<div class="empty">Sem eventos registrados.</div>';
  const attribution = `${trade.analysis_provider || '—'} · ${trade.analysis_model || '—'} · ${trade.analysis_mode || '—'} · ${trade.analysis_source || 'automatic'}`;
  const reviewHtml = review ? `<h3>Revisão pós-trade Groq · ${escapeHtml(review.review_status)}</h3><p>${escapeHtml(review.groq_review || review.error_message || 'Revisão ainda não disponível.')}</p><details><summary>Gráfico em texto da entrada até a saída</summary><pre class="json-view">${escapeHtml(review.exit_text_snapshot || 'Não disponível')}</pre></details>` : '<p class="subtle">Revisão Groq ainda pendente ou não registrada.</p>';
  openModal(`Operação ${trade.direction} · ${trade.symbol}`, `<p class="subtle">${escapeHtml(attribution)}</p><p><strong>${escapeHtml(resultLabel(trade.result_category))}</strong></p><div class="detail-grid"><div><small>Entrada</small><b>${money(trade.entry_price)}</b></div><div><small>Stop atual/final</small><b>${money(trade.current_stop_loss)}</b></div><div><small>TP1 / TP2</small><b>${money(trade.tp1_price)} / ${money(trade.tp2_price)}</b></div><div><small>PnL líquido</small><b>${signedMoney(trade.realized_pnl_net)}</b></div></div>${reviewHtml}<h3>Eventos da operação</h3>${evHtml}`);
}
async function showRunDetails(runId) {
  const run = cached.runs.find((r) => r.id === runId);
  if (!run) return;
  const apex = run.apex_table || {};
  const images = (run.chart_images || []).filter((i) => i.url && /^https:\/\//i.test(i.url));
  const imagesHtml = images.length ? `<div class="chart-images">${images.map((i) => `<a href="${escapeHtml(i.url)}" target="_blank" rel="noopener"><img src="${escapeHtml(i.url)}" loading="lazy" alt="Gráfico ${escapeHtml(i.timeframe)}"><span>${escapeHtml(i.timeframe)}</span></a>`).join('')}</div>` : '';
  const pre = escapeHtml(JSON.stringify(apex, null, 2));
  const providerInfo = `${run.analysis_provider || '—'} · ${run.analysis_model || run.ai_model || 'modelo —'} · gráfico ${run.chart_source_type || run.analysis_mode || '—'} · origem ${run.analysis_source || run.source || '—'}`;
  openModal(`Análise · ${run.signal || run.trigger_direction || 'Sem sinal'}`, `<p>${escapeHtml(apex.analysis_summary || run.error_message || 'Sem resumo.')}</p><p class="subtle">${escapeHtml(providerInfo)}</p>${imagesHtml}<h3>APEX_TABLE</h3><pre class="json-view">${pre}</pre><details><summary>Resposta bruta da análise</summary><pre class="json-view">${escapeHtml(run.ai_raw_response || 'Sem resposta')}</pre></details><details><summary>Snapshot de mercado</summary><pre class="json-view">${escapeHtml(JSON.stringify(run.market_snapshot || {}, null, 2))}</pre></details>`);
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
    ai_provider_strategy: $('setting-ai-strategy').value,
    fixed_ai_provider: $('setting-fixed-provider').value,
    fixed_ai_model: $('setting-fixed-model').value.trim(),
    openrouter_model: $('setting-openrouter-model').value.trim() || 'openrouter/free',
    groq_health_interval_hours: Number($('setting-groq-interval').value),
    simulate_exchange_minimum: $('setting-minimum-size').checked,
    minimum_notional_usdt: Number($('setting-min-notional').value),
    trigger_volume_multiplier: Number($('setting-volume-mult').value),
    trigger_sweep_length: Number($('setting-sweep-len').value),
    trigger_displacement_multiplier: Number($('setting-disp-mult').value),
    trigger_cooldown: Number($('setting-cooldown').value),
    trigger_min_score: Number($('setting-min-score').value),
  };
  if (!payload.binance_symbol || !payload.gemini_model || !payload.groq_model || !payload.timezone) {
    message.textContent = 'Preencha o par, os modelos e o fuso horário.'; message.classList.add('error-text'); return;
  }
  if (payload.risk_per_trade_pct <= 0 || payload.risk_per_trade_pct > 2 || payload.max_leverage < 1 || payload.max_leverage > 20 || payload.max_open_trades < 1 || payload.max_open_trades > 5 || payload.max_daily_loss_pct < 0.5 || payload.max_daily_loss_pct > 20 || payload.groq_health_interval_hours < 1 || payload.groq_health_interval_hours > 48 || payload.minimum_notional_usdt <= 0 || payload.trigger_volume_multiplier < 1 || payload.trigger_volume_multiplier > 5 || payload.trigger_sweep_length < 2 || payload.trigger_sweep_length > 100 || payload.trigger_displacement_multiplier < 1 || payload.trigger_displacement_multiplier > 5 || payload.trigger_cooldown < 1 || payload.trigger_cooldown > 30) {
    message.textContent = 'Revise os limites: risco 0–2%, alavancagem 1–20x, posições 1–5, Groq 1–48h e sensibilidade dentro das faixas indicadas.'; message.classList.add('error-text'); return;
  }
  if (payload.ai_provider_strategy === 'fixed' && payload.fixed_ai_provider === 'openrouter' && !payload.fixed_ai_model) payload.fixed_ai_model = payload.openrouter_model;
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
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
async function waitForCommand(commandId, timeoutMs = 100000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { data, error } = await supabase.from('run_requests').select('*').eq('id', commandId).maybeSingle();
    if (error) throw error;
    if (data?.status === 'completed') return data;
    if (data?.status === 'failed') throw new Error(data.error_message || 'O Redmi informou falha ao processar o comando.');
    await sleep(2500);
  }
  throw new Error('O comando ainda está na fila. Confira o histórico de comandos e atualize o painel em alguns instantes.');
}
function downloadBlob(content, filename, mime = 'text/plain;charset=utf-8') {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
function extractApexTable(rawText) {
  const raw = String(rawText || '').replace(/&#91;/g, '[').replace(/&#93;/g, ']').replace(/&quot;/g, '"');
  const match = raw.match(/\[APEX_TABLE\]([\s\S]*?)\[\/APEX_TABLE\]/i);
  const source = (match ? match[1] : raw).replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  const start = source.indexOf('{');
  if (start < 0) throw new Error('Não encontrei um objeto JSON nem um bloco [APEX_TABLE].');
  let depth = 0, inString = false, escaped = false, end = -1;
  for (let i = start; i < source.length; i++) {
    const ch = source[i];
    if (inString) { if (escaped) escaped = false; else if (ch === '\\') escaped = true; else if (ch === '"') inString = false; continue; }
    if (ch === '"') inString = true;
    else if (ch === '{') depth++;
    else if (ch === '}' && --depth === 0) { end = i + 1; break; }
  }
  if (end < 0) throw new Error('O JSON dentro da APEX_TABLE está incompleto.');
  const data = JSON.parse(source.slice(start, end));
  if (!['LONG', 'SHORT', 'NO_TRADE'].includes(String(data.signal || '').toUpperCase())) throw new Error('Campo signal inválido. Use LONG, SHORT ou NO_TRADE.');
  if (data.signal !== 'NO_TRADE') {
    for (const key of ['entry', 'stop_loss', 'tp1', 'tp2']) if (!Number.isFinite(Number(data[key])) || Number(data[key]) <= 0) throw new Error(`Campo ${key} ausente ou inválido.`);
  }
  return data;
}
async function pasteManualAnalysis() {
  const target = $('manual-analysis-raw');
  try {
    if (!navigator.clipboard?.readText) throw new Error('Clipboard API indisponível neste navegador.');
    target.value = await navigator.clipboard.readText();
    $('manual-analysis-status').textContent = 'Texto colado da área de transferência. Confira e valide antes de confirmar.';
  } catch (error) {
    target.focus();
    $('manual-analysis-status').textContent = 'O navegador não liberou leitura automática da área de transferência. Toque no campo e use Colar do teclado.';
  }
}
async function submitManualAnalysis() {
  const status = $('manual-analysis-status');
  const raw = $('manual-analysis-raw').value.trim();
  let apex;
  try { apex = extractApexTable(raw); }
  catch (error) { status.textContent = error.message; status.className = 'form-message error-text'; return; }
  const provider = $('manual-provider').value.trim() || 'Externa';
  const model = $('manual-model').value.trim() || 'Análise externa manual';
  const chartType = $('manual-chart-type').value;
  const direction = String(apex.signal).toUpperCase();
  const details = direction === 'NO_TRADE'
    ? `A análise externa informa NO_TRADE. Ela será registrada sem abrir posição.\n\nOrigem: ${provider} / ${model}`
    : `${direction} · ${apex.entry_type || 'tipo não informado'}\nEntrada: ${money(apex.entry)}\nStop: ${money(apex.stop_loss)}\nTP1: ${money(apex.tp1)}\nTP2: ${money(apex.tp2)}\n\nProvedor: ${provider}\nModelo: ${model}\nGráfico: ${chartType === 'chart_img' ? 'Chart IMG' : 'Texto'}\n\nConfirmar a criação da operação VIRTUAL?`;
  if (!confirm(details)) return;
  status.textContent = 'Enviando análise para o Redmi…'; status.className = 'form-message';
  try {
    const command = await enqueueCommand('manual_external_analysis', {
      raw_response: raw, confirmed: true, external_provider: provider,
      external_model: model, chart_type: chartType,
    });
    const completed = await waitForCommand(command.id);
    status.textContent = direction === 'NO_TRADE' ? 'Análise externa registrada sem operação.' : 'Análise externa registrada e entrada virtual processada.';
    status.className = 'form-message success-text';
    notifyToast('Análise externa registrada no histórico.', 'success');
    await refreshAll();
    activateTab('analysis');
  } catch (error) { status.textContent = error.message; status.className = 'form-message error-text'; }
}
async function copyEffectivePrompt(kind) {
  const custom = kind === 'chart_img' ? cached.prompts?.custom_chart_img_prompt : cached.prompts?.custom_text_prompt;
  let content = custom;
  if (!content) {
    const path = kind === 'chart_img' ? './prompts/default-chart-img.md' : './prompts/default-text.md';
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error('Não foi possível carregar o prompt padrão.');
    content = await response.text();
  }
  await navigator.clipboard.writeText(content);
  notifyToast(`Prompt ${kind === 'chart_img' ? 'Chart IMG' : 'Texto'} copiado.`, 'success');
}
async function requestGroqReport() {
  const command = await enqueueCommand('groq_report');
  notifyToast('Solicitação enviada ao Redmi. O relatório Groq está sendo preparado.', 'success');
  const completed = await waitForCommand(command.id, 150000);
  const report = completed.result?.report_text || cached.groqReports?.[0]?.report_text || 'Relatório concluído, mas o texto não foi retornado pelo comando.';
  openModal('Relatório operacional Groq', `<p class="subtle">Gerado em ${fmtDate(new Date().toISOString(), true)} · fotografia dos últimos acontecimentos</p><pre class="json-view report-view">${escapeHtml(report)}</pre>`);
  await refreshAll();
}
async function generateExport(type) {
  const status = $('export-status'); status.textContent = 'Solicitando ao Redmi…'; status.className = 'form-message';
  try {
    let payload = {};
    if (type === 'export_text' && $('export-reference-at').value) payload.reference_at = new Date($('export-reference-at').value).toISOString();
    const command = await enqueueCommand(type, payload);
    const completed = await waitForCommand(command.id, type === 'export_chart_images' ? 420000 : 150000);
    const exportId = completed.result?.export_id;
    if (!exportId) throw new Error('O worker concluiu, mas não retornou o identificador do arquivo.');
    const { data, error } = await supabase.from('apex_exports').select('*').eq('id', exportId).single();
    if (error) throw error;
    if (type === 'export_text') {
      if (!data.content_text) throw new Error('O export não contém gráfico em texto.');
      const stamp = new Date(data.reference_at || Date.now()).toISOString().replace(/[:.]/g, '-');
      downloadBlob(data.content_text, `ApexPrime-BTCUSDT-${stamp}.txt`);
      status.textContent = 'Gráfico em texto baixado. Você também pode encontrá-lo no histórico de exportações.';
    } else {
      status.textContent = 'Imagens Chart IMG geradas em 800×600. Abra os links no histórico abaixo.';
    }
    status.className = 'form-message success-text'; await refreshAll();
  } catch (error) { status.textContent = error.message; status.className = 'form-message error-text'; }
}
async function downloadTextExport(exportId) {
  const { data, error } = await supabase.from('apex_exports').select('content_text,reference_at,symbol').eq('id', exportId).single();
  if (error) throw error;
  if (!data.content_text) throw new Error('Este arquivo não contém texto para baixar.');
  const stamp = new Date(data.reference_at || Date.now()).toISOString().replace(/[:.]/g, '-');
  downloadBlob(data.content_text, `ApexPrime-${data.symbol}-${stamp}.txt`);
}
async function downloadChartImage(url, name = 'ApexPrime-chart') {
  if (!/^https:\/\//i.test(String(url))) throw new Error('URL da imagem inválida.');
  try {
    const response = await fetch(url, { mode: 'cors', cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const ext = blob.type.includes('jpeg') ? 'jpg' : blob.type.includes('webp') ? 'webp' : 'png';
    downloadBlob(blob, `${String(name).replace(/[^a-z0-9_-]/gi, '-')}.${ext}`);
  } catch (_) {
    window.open(url, '_blank', 'noopener');
    notifyToast('A imagem foi aberta em outra aba. Use o menu do navegador para salvar.', 'warn');
  }
}
async function addVirtualDeposit(event) {
  event.preventDefault();
  const amount = Number($('deposit-amount').value);
  const description = $('deposit-description').value.trim() || 'Adição manual de saldo virtual';
  const message = $('deposit-message');
  if (!Number.isFinite(amount) || amount <= 0) { message.textContent = 'Informe uma quantia maior que zero.'; return; }
  if (!confirm(`Adicionar ${money(amount, 4)} USDT ao saldo virtual? Essa movimentação ficará registrada no histórico.`)) return;
  message.textContent = 'Enviando ao Redmi…';
  try {
    const command = await enqueueCommand('add_virtual_balance', { amount, description });
    const completed = await waitForCommand(command.id);
    message.textContent = `Adicionado: ${money(completed.result?.added, 4)} USDT · Novo saldo: ${money(completed.result?.balance, 4)} USDT`;
    message.className = 'form-message success-text'; $('deposit-form').reset();
    $('deposit-description').value = 'Adição manual de saldo virtual';
    await refreshAll();
  } catch (error) { message.textContent = error.message; message.className = 'form-message error-text'; }
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
  $('force-analysis').textContent = 'Forçar análise IA';
  $('force-analysis').addEventListener('click', async () => {
    if (!confirm('Solicitar uma análise agora? O roteador tentará Gemini, OpenRouter e Groq conforme as configurações. Pode consumir créditos dos provedores.')) return;
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
  $('deposit-form').addEventListener('submit', addVirtualDeposit);
  $('paste-manual-analysis').addEventListener('click', pasteManualAnalysis);
  $('confirm-manual-analysis').addEventListener('click', submitManualAnalysis);
  $('copy-chart-prompt').addEventListener('click', () => copyEffectivePrompt('chart_img').catch((e) => notifyToast(e.message, 'error')));
  $('copy-text-prompt').addEventListener('click', () => copyEffectivePrompt('text').catch((e) => notifyToast(e.message, 'error')));
  $('groq-report-now').addEventListener('click', () => requestGroqReport().catch((e) => notifyToast(e.message, 'error')));
  $('download-text-chart').addEventListener('click', () => generateExport('export_text'));
  $('download-chart-images').addEventListener('click', () => generateExport('export_chart_images'));
  $('winrate-filter').addEventListener('change', () => renderDashboardMetrics(cached.mark));
  $('prompts-form').addEventListener('submit', savePrompts);
  $('reset-prompts').addEventListener('click', resetPrompts);
  $('log-filter').addEventListener('change', renderLogs);
  document.body.addEventListener('click', async (e) => {
    const close = e.target.closest('[data-close-trade]');
    const cancel = e.target.closest('[data-cancel-pending]');
    const replay = e.target.closest('[data-replay-trade]');
    const run = e.target.closest('[data-run-details]');
    const detail = e.target.closest('[data-trade-details]');
    const exportButton = e.target.closest('[data-download-export]');
    const imageButton = e.target.closest('[data-download-image]');
    if (close) await commandWithConfirm('close_trade', { trade_id: close.dataset.closeTrade }, 'Sair desta operação virtual pelo mark price atual?', 'Comando de saída enviado ao Redmi.');
    if (cancel) await commandWithConfirm('cancel_pending_entry', { pending_id: cancel.dataset.cancelPending }, 'Cancelar esta entrada virtual pendente?', 'Cancelamento enviado ao Redmi.');
    if (replay) { try { await startReplay(replay.dataset.replayTrade); } catch (err) { notifyToast(err.message, 'error'); } }
    if (run) { try { await showRunDetails(run.dataset.runDetails); } catch (err) { notifyToast(err.message, 'error'); } }
    if (detail) { try { await showTradeDetails(detail.dataset.tradeDetails); } catch (err) { notifyToast(err.message, 'error'); } }
    if (exportButton) { try { await downloadTextExport(exportButton.dataset.downloadExport); } catch (err) { notifyToast(err.message, 'error'); } }
    if (imageButton) { try { await downloadChartImage(imageButton.dataset.downloadImage, imageButton.dataset.imageName); } catch (err) { notifyToast(err.message, 'error'); } }
    if (e.target.matches('[data-close-modal]')) closeModal();
  });
  if (location.hash && $(`tab-${location.hash.slice(1)}`)) activateTab(location.hash.slice(1));
  refreshTimer = setInterval(() => refreshAll().catch((e) => console.error('ApexPrime refresh:', e)), 30000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshAll().catch(console.error); });
}

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('./sw.js').catch(console.error));
init().catch((e) => showLogin(e.message));
