import { api } from './api.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso) {
  if (!iso) return '—';
  // Convert UTC → GMT+7
  const d = new Date(iso);
  return d.toLocaleString('vi-VN', {
    hour12: false,
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
}

function fmtPnl(val) {
  const n = parseFloat(val) || 0;
  const color = n > 0 ? '#0ecb81' : n < 0 ? '#f6465d' : '#8892a4';
  const sign = n > 0 ? '+' : '';
  return `<span style="color:${color};font-weight:600;">${sign}$${n.toFixed(4)}</span>`;
}

function sideLabel(side, signalType) {
  // Ưu tiên signal_type để hiển thị đúng LONG/SHORT
  if (signalType === 'long' || signalType === 'close_long') {
    return signalType === 'long'
      ? '<span class="badge badge-long">LONG</span>'
      : '<span class="badge badge-close">ĐÓNG LONG</span>';
  }
  if (signalType === 'short' || signalType === 'close_short') {
    return signalType === 'short'
      ? '<span class="badge badge-short">SHORT</span>'
      : '<span class="badge badge-close">ĐÓNG SHORT</span>';
  }
  const color = side === 'buy' ? '#0ecb81' : '#f6465d';
  return `<span style="color:${color};font-weight:600;">${side.toUpperCase()}</span>`;
}

function statusBadge(status) {
  const map = {
    filled:   { bg: 'rgba(14,203,129,0.15)',  color: '#0ecb81',  label: 'Đang mở' },
    closed:   { bg: 'rgba(139,148,158,0.15)', color: '#8892a4',  label: 'Đã đóng' },
    failed:   { bg: 'rgba(246,70,93,0.15)',   color: '#f6465d',  label: 'Thất bại' },
    pending:  { bg: 'rgba(240,185,11,0.15)',  color: '#F0B90B',  label: 'Chờ' },
    canceled: { bg: 'rgba(139,148,158,0.15)', color: '#8892a4',  label: 'Hủy' },
  };
  const s = map[status] || { bg: 'rgba(139,148,158,0.15)', color: '#8892a4', label: status };
  return `<span style="background:${s.bg};color:${s.color};padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">${s.label}</span>`;
}

// ── State ─────────────────────────────────────────────────────────────────────

let _filterBotId = '';
let _filterStatus = '';
let _filterSymbol = '';
let _currentPage = 1;
const PAGE_SIZE = 20;

// ── Main loader ───────────────────────────────────────────────────────────────

export async function loadTradesPage() {
  await Promise.all([
    _loadStats(),
    _loadOpenTrades(),
    _loadTradeHistory(),
    _populateBotFilter(),
  ]);

  // Auto-refresh open trades mỗi 30s để cập nhật unrealized PnL
  if (!window._tradesRefreshTimer) {
    window._tradesRefreshTimer = setInterval(() => {
      const page = document.getElementById('page-trades');
      if (page && page.classList.contains('active')) {
        _loadOpenTrades();
        _loadStats();
      }
    }, 30000);
  }
}

// ── Stats cards ───────────────────────────────────────────────────────────────

async function _loadStats() {
  const stats = await api.getTradeStats();
  const container = document.getElementById('tradeStatsGrid');
  if (!container) return;

  if (!stats || stats.length === 0) {
    container.innerHTML = '<div class="empty-state">Chưa có dữ liệu thống kê</div>';
    return;
  }

  // Tổng hợp toàn hệ thống
  const totalPnl = stats.reduce((s, b) => s + b.total_pnl, 0);
  const totalClosed = stats.reduce((s, b) => s + b.closed_trades, 0);
  const totalWins = stats.reduce((s, b) => s + b.winning_trades, 0);
  const totalOpen = stats.reduce((s, b) => s + b.open_trades, 0);
  const globalWinRate = totalClosed > 0 ? (totalWins / totalClosed * 100).toFixed(1) : 0;

  const pnlColor = totalPnl >= 0 ? '#0ecb81' : '#f6465d';
  const pnlSign = totalPnl >= 0 ? '+' : '';

  container.innerHTML = `
    <div class="stat-card">
      <h3>💰 Tổng PnL</h3>
      <div class="val" style="color:${pnlColor};">${pnlSign}$${totalPnl.toFixed(4)}</div>
    </div>
    <div class="stat-card">
      <h3>📂 Lệnh Đang Mở</h3>
      <div class="val" style="color:#F0B90B;">${totalOpen}</div>
    </div>
    <div class="stat-card">
      <h3>✅ Lệnh Đã Đóng</h3>
      <div class="val">${totalClosed}</div>
    </div>
    <div class="stat-card">
      <h3>🏆 Tỷ Lệ Thắng</h3>
      <div class="val" style="color:#0ecb81;">${globalWinRate}%</div>
    </div>
  `;

  // Bảng thống kê từng bot
  const botStatsEl = document.getElementById('botStatsTable');
  if (botStatsEl) {
    botStatsEl.innerHTML = stats.map(b => {
      const pnlColor = b.total_pnl >= 0 ? '#0ecb81' : '#f6465d';
      const pnlSign = b.total_pnl >= 0 ? '+' : '';
      const statusDot = b.status === 'running'
        ? '<span style="color:#0ecb81;">●</span>'
        : '<span style="color:#8892a4;">●</span>';
      return `
        <tr>
          <td>${statusDot} <strong>${b.bot_name}</strong></td>
          <td style="color:#8892a4;">${b.strategy_name}</td>
          <td>${(b.symbols || []).join(', ')}</td>
          <td style="text-align:center;">${b.open_trades}</td>
          <td style="text-align:center;">${b.closed_trades}</td>
          <td style="text-align:center;">${b.win_rate}%</td>
          <td style="color:${pnlColor};font-weight:600;text-align:right;">${pnlSign}$${b.total_pnl.toFixed(4)}</td>
        </tr>
      `;
    }).join('');
  }
}

// ── Open positions ────────────────────────────────────────────────────────────

async function _loadOpenTrades() {
  const trades = await api.getOpenTrades();
  const tbody = document.getElementById('openTradesBody');
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-state" style="padding:20px;">Không có vị thế nào đang mở</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const upnl = t.unrealized_pnl != null
      ? fmtPnl(t.unrealized_pnl) + (t.unrealized_pct != null ? ` <span style="color:#8892a4;font-size:11px;">(${t.unrealized_pct > 0 ? '+' : ''}${t.unrealized_pct}%)</span>` : '')
      : '<span style="color:#8892a4;">—</span>';
    return `
    <tr>
      <td style="color:#8892a4;font-size:12px;">${fmtTime(t.created_at)}</td>
      <td><strong>${t.symbol}</strong></td>
      <td>${sideLabel(t.side, t.signal_type)}</td>
      <td>${t.price ? t.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 6}) : '—'}</td>
      <td>${t.amount}</td>
      <td>${t.leverage ? t.leverage + 'x' : '—'}</td>
      <td style="color:#8892a4;font-size:12px;">${t.bot_name || `Bot#${t.bot_id||'?'}`}</td>
      <td style="color:#8892a4;font-size:12px;">${t.strategy || '—'}</td>
      <td>${upnl}</td>
      <td>${statusBadge(t.status)}</td>
    </tr>
  `}).join('');
}

// ── Trade history ─────────────────────────────────────────────────────────────

async function _loadTradeHistory() {
  const params = new URLSearchParams({ limit: PAGE_SIZE });
  if (_filterBotId) params.set('bot_id', _filterBotId);
  if (_filterStatus) params.set('status', _filterStatus);
  if (_filterSymbol) params.set('symbol', _filterSymbol);

  const trades = await fetch(`/api/trades?${params}`).then(r => r.json());
  const tbody = document.getElementById('tradeHistoryBody');
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-state" style="padding:20px;">Không có lệnh nào</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => `
    <tr>
      <td style="color:#8892a4;font-size:12px;">${fmtTime(t.created_at)}</td>
      <td><strong>${t.symbol}</strong></td>
      <td>${sideLabel(t.side, t.signal_type)}</td>
      <td>${t.price ? t.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 6}) : '—'}</td>
      <td>${t.amount}</td>
      <td>${t.leverage ? t.leverage + 'x' : '—'}</td>
      <td style="color:#8892a4;font-size:12px;">${t.bot_name || `Bot#${t.bot_id||'?'}`}</td>
      <td style="color:#8892a4;font-size:12px;">${t.strategy || '—'}</td>
      <td>${fmtPnl(t.realized_pnl)}</td>
      <td>${statusBadge(t.status)}</td>
      <td style="color:#8892a4;font-size:12px;">${fmtTime(t.closed_at)}</td>
    </tr>
  `).join('');
}

// ── Bot filter dropdown ───────────────────────────────────────────────────────

async function _populateBotFilter() {
  const sel = document.getElementById('filterBot');
  if (!sel || sel.dataset.loaded) return;
  const bots = await api.getBots();
  bots.forEach(b => {
    const opt = document.createElement('option');
    opt.value = b.id;
    opt.textContent = b.name;
    sel.appendChild(opt);
  });
  sel.dataset.loaded = '1';
}

// ── Filter handlers (exposed to window) ──────────────────────────────────────

export function applyTradeFilters() {
  _filterBotId = document.getElementById('filterBot')?.value || '';
  _filterStatus = document.getElementById('filterStatus')?.value || '';
  _filterSymbol = document.getElementById('filterSymbol')?.value?.trim() || '';
  _currentPage = 1;
  _loadTradeHistory();
}

export function resetTradeFilters() {
  _filterBotId = '';
  _filterStatus = '';
  _filterSymbol = '';
  const fb = document.getElementById('filterBot');
  const fs = document.getElementById('filterStatus');
  const fsym = document.getElementById('filterSymbol');
  if (fb) fb.value = '';
  if (fs) fs.value = '';
  if (fsym) fsym.value = '';
  _loadTradeHistory();
}
