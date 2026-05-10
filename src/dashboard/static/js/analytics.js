/**
 * analytics.js — Performance Analytics UI
 *
 * Hien thi hieu suat giao dich cua tung bot va strategy:
 *   - Net PnL, Win Rate, Profit Factor, Max Drawdown
 *   - Bang so sanh tat ca bot
 *   - Loc theo khoang thoi gian (7/30/90 ngay)
 */

// ── State ─────────────────────────────────────────────────────────────────────

let _analyticsDays = 30;

// ── Entry point ───────────────────────────────────────────────────────────────

export async function loadAnalytics() {
  await refreshAnalytics();
}

export async function refreshAnalytics() {
  const days = _analyticsDays;
  showAnalyticsLoading();
  try {
    const res = await fetch(`/api/analytics/bots?days=${days}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAnalyticsSummary(data, days);
    renderAnalyticsTable(data);
  } catch (err) {
    showAnalyticsError(err.message);
  }
}

// ── Period selector ───────────────────────────────────────────────────────────

export function setAnalyticsDays(days) {
  _analyticsDays = parseInt(days, 10);
  document.querySelectorAll('.analytics-period-btn').forEach(btn => {
    btn.classList.toggle('btn-primary', parseInt(btn.dataset.days, 10) === _analyticsDays);
    btn.classList.toggle('btn-secondary', parseInt(btn.dataset.days, 10) !== _analyticsDays);
  });
  refreshAnalytics();
}

// ── Render helpers ────────────────────────────────────────────────────────────

function renderAnalyticsSummary(bots, days) {
  const totalPnl   = bots.reduce((s, b) => s + (b.net_pnl || 0), 0);
  const totalTrades = bots.reduce((s, b) => s + (b.total_trades || 0), 0);
  const totalWins  = bots.reduce((s, b) => s + (b.winning_trades || 0), 0);
  const winRate    = totalTrades > 0 ? (totalWins / totalTrades * 100).toFixed(1) : '0.0';
  const activeBots = bots.filter(b => b.total_trades > 0).length;

  const pnlColor = totalPnl >= 0 ? 'var(--green)' : 'var(--red)';
  const pnlSign  = totalPnl >= 0 ? '+' : '';

  document.getElementById('analyticsSummary').innerHTML = `
    <div class="stat-card">
      <h3>Tong PnL (${days} ngay)</h3>
      <div class="val" style="color:${pnlColor}">${pnlSign}$${totalPnl.toFixed(2)}</div>
    </div>
    <div class="stat-card">
      <h3>Tong lenh da dong</h3>
      <div class="val">${totalTrades}</div>
    </div>
    <div class="stat-card">
      <h3>Win Rate tong hop</h3>
      <div class="val">${winRate}%</div>
    </div>
    <div class="stat-card">
      <h3>Bot co giao dich</h3>
      <div class="val">${activeBots} / ${bots.length}</div>
    </div>
  `;
}

function renderAnalyticsTable(bots) {
  const tbody = document.getElementById('analyticsTableBody');
  if (!bots || bots.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-state">Chua co du lieu</td></tr>';
    return;
  }

  tbody.innerHTML = bots.map(b => {
    const pnl      = b.net_pnl || 0;
    const pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
    const pnlSign  = pnl >= 0 ? '+' : '';
    const pf       = b.profit_factor != null ? b.profit_factor.toFixed(2) : 'N/A';
    const dd       = b.max_drawdown != null ? `$${b.max_drawdown.toFixed(2)}` : 'N/A';
    const winRate  = (b.win_rate_pct || 0).toFixed(1);
    const dur      = b.avg_duration_hours != null ? `${b.avg_duration_hours.toFixed(1)}h` : 'N/A';

    return `
      <tr>
        <td><strong>#${b.bot_id}</strong> ${escHtml(b.bot_name)}</td>
        <td><code>${escHtml(b.strategy_name)}</code></td>
        <td style="text-align:center">${b.total_trades}</td>
        <td style="text-align:center">${b.winning_trades} / ${b.losing_trades}</td>
        <td style="text-align:center">${winRate}%</td>
        <td style="text-align:right; color:${pnlColor}; font-weight:600">${pnlSign}$${pnl.toFixed(2)}</td>
        <td style="text-align:center">${pf}</td>
        <td style="text-align:center; color:var(--red)">${dd}</td>
        <td style="text-align:center; color:var(--text-secondary)">${dur}</td>
      </tr>
    `;
  }).join('');
}

function showAnalyticsLoading() {
  document.getElementById('analyticsSummary').innerHTML =
    '<div class="empty-state" style="grid-column:1/-1">Dang tai du lieu...</div>';
  document.getElementById('analyticsTableBody').innerHTML =
    '<tr><td colspan="9" class="empty-state">Dang tai...</td></tr>';
}

function showAnalyticsError(msg) {
  document.getElementById('analyticsSummary').innerHTML =
    `<div class="empty-state" style="grid-column:1/-1; color:var(--red)">Loi: ${escHtml(msg)}</div>`;
  document.getElementById('analyticsTableBody').innerHTML =
    `<tr><td colspan="9" class="empty-state" style="color:var(--red)">Loi tai du lieu: ${escHtml(msg)}</td></tr>`;
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
