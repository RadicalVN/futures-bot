/* =====================================================================
   app.js — Dashboard JavaScript
   Xử lý API calls, WebSocket, Charts và UI logic
   ===================================================================== */

// ─── State ────────────────────────────────────────────────────────────
const state = {
  currentPage: 'dashboard',
  ws: null,
  priceChart: null,
  macdChart: null,
  refreshInterval: null,
};

// ─── Init ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  loadDashboard();
  startAutoRefresh();
});

// ─── Navigation ───────────────────────────────────────────────────────
function showPage(page) {
  // Hide all pages
  document.querySelectorAll('.page').forEach(p => {
    p.classList.add('hidden');
    p.classList.remove('active');
  });

  // Show target page
  const target = document.getElementById(`page-${page}`);
  if (target) {
    target.classList.remove('hidden');
    target.classList.add('active');
  }

  // Update nav
  document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
  const navItem = document.getElementById(`nav-${page}`);
  if (navItem) navItem.classList.add('active');

  // Update title
  const titles = {
    dashboard: 'Dashboard',
    trades: 'Lịch sử Lệnh',
    signals: 'Tín hiệu',
    chart: 'Biểu đồ',
    config: 'Cài đặt',
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;
  state.currentPage = page;

  // Load page-specific data
  if (page === 'trades') loadTrades();
  if (page === 'signals') loadSignals();
  if (page === 'chart') loadChart();
  if (page === 'config') loadConfig();

  // Close sidebar on mobile
  if (window.innerWidth < 900) {
    document.getElementById('sidebar').classList.remove('open');
  }
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// ─── WebSocket ────────────────────────────────────────────────────────
function initWebSocket() {
  const wsUrl = `ws://${window.location.host}/ws`;
  
  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      setConnectionStatus(true);
    };

    state.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'update') {
        updateBalanceFromWS(data.balance);
        updatePositionsFromWS(data.positions);
        updateBotStatusFromWS(data.bot_status);
        document.getElementById('lastUpdate').textContent =
          '● Cập nhật: ' + new Date(data.timestamp).toLocaleTimeString('vi-VN');
      }
    };

    state.ws.onclose = () => {
      setConnectionStatus(false);
      // Reconnect sau 5 giây
      setTimeout(initWebSocket, 5000);
    };

    state.ws.onerror = () => {
      setConnectionStatus(false);
    };
  } catch (e) {
    setConnectionStatus(false);
  }
}

function setConnectionStatus(connected) {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  if (connected) {
    dot.className = 'status-dot connected';
    text.textContent = 'Đã kết nối';
  } else {
    dot.className = 'status-dot disconnected';
    text.textContent = 'Mất kết nối';
  }
}

// ─── API Calls ────────────────────────────────────────────────────────
async function apiGet(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

async function apiPost(path) {
  const resp = await fetch(path, { method: 'POST' });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

// ─── Dashboard ────────────────────────────────────────────────────────
async function loadDashboard() {
  await Promise.allSettled([
    loadBalance(),
    loadBotStatus(),
    loadStats(),
    loadPositions(),
    loadRecentTrades(),
  ]);
}

async function loadBalance() {
  try {
    const data = await apiGet('/api/account/balance');
    document.getElementById('balanceTotal').textContent =
      data.error ? '⚠️' : `$${fmt(data.total)}`;
    document.getElementById('balanceFree').textContent =
      data.error ? data.error : `Khả dụng: $${fmt(data.free)}`;
  } catch (e) {
    document.getElementById('balanceTotal').textContent = '--';
  }
}

async function loadBotStatus() {
  try {
    const status = await apiGet('/api/bot/status');
    updateBotStatusFromWS(status);
  } catch (e) { }
}

async function loadStats() {
  try {
    const stats = await apiGet('/api/trades/stats');
    const pnlEl = document.getElementById('totalPnl');
    const pnl = stats.total_pnl || 0;
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${fmt(pnl)}`;
    pnlEl.className = 'card-value ' + (pnl >= 0 ? 'pnl-pos' : 'pnl-neg');
    document.getElementById('winRate').textContent = `Win Rate: ${stats.win_rate}%`;
    document.getElementById('totalTrades').textContent = stats.total_trades || 0;
    document.getElementById('winLoss').textContent =
      `Thắng: ${stats.win_count} / Thua: ${stats.loss_count}`;
  } catch (e) { }
}

async function loadPositions() {
  try {
    const positions = await apiGet('/api/account/positions');
    renderPositions(positions);
    document.getElementById('openPositions').textContent = positions.length;
  } catch (e) {
    document.getElementById('openPositions').textContent = '--';
  }
}

async function loadRecentTrades() {
  try {
    const trades = await apiGet('/api/trades?limit=10');
    renderTradesTable('recentTradesBody', trades);
  } catch (e) { }
}

function updateBalanceFromWS(balance) {
  if (!balance || balance.error) return;
  document.getElementById('balanceTotal').textContent = `$${fmt(balance.total)}`;
  document.getElementById('balanceFree').textContent = `Khả dụng: $${fmt(balance.free)}`;
}

function updatePositionsFromWS(positions) {
  if (!positions) return;
  renderPositions(positions);
  document.getElementById('openPositions').textContent = positions.length;
}

function updateBotStatusFromWS(status) {
  if (!status) return;
  
  const isRunning = status.is_running;
  document.getElementById('btnStart').classList.toggle('hidden', isRunning);
  document.getElementById('btnStop').classList.toggle('hidden', !isRunning);
  
  const mode = (status.mode || 'testnet').toUpperCase();
  const badge = document.getElementById('modeBadge');
  badge.textContent = mode;
  badge.className = 'mode-badge ' + (mode === 'MAINNET' ? 'mainnet' : '');
}

function renderPositions(positions) {
  const tbody = document.getElementById('positionsBody');
  if (!positions || positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row">Không có vị thế nào đang mở</td></tr>';
    return;
  }

  tbody.innerHTML = positions.map(p => {
    const pnl = p.unrealized_pnl || 0;
    const pnlClass = pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    return `<tr>
      <td>${p.symbol}</td>
      <td><span class="badge badge-${p.side}">${p.side?.toUpperCase()}</span></td>
      <td>${p.size}</td>
      <td>$${fmt(p.entry_price)}</td>
      <td>${p.leverage}x</td>
      <td class="${pnlClass}">${pnl >= 0 ? '+' : ''}$${fmt(pnl)}</td>
      <td>${p.liquidation_price ? '$' + fmt(p.liquidation_price) : '--'}</td>
    </tr>`;
  }).join('');
}

async function refreshPositions() {
  await loadPositions();
  showToast('Đã làm mới vị thế', 'info');
}

// ─── Trades Page ──────────────────────────────────────────────────────
async function loadTrades() {
  try {
    const trades = await apiGet('/api/trades?limit=100');
    renderTradesTable('allTradesBody', trades, true);
  } catch (e) {
    showToast('Lỗi tải lịch sử lệnh', 'error');
  }
}

function renderTradesTable(tbodyId, trades, showCost = false) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    const cols = tbodyId === 'allTradesBody' ? 10 : 8;
    tbody.innerHTML = `<tr><td colspan="${cols}" class="empty-row">Chưa có giao dịch nào</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const pnl = t.realized_pnl || 0;
    const pnlClass = pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : 'pnl-zero';
    const pnlText = pnl !== 0 ? `${pnl > 0 ? '+' : ''}$${fmt(pnl)}` : '--';
    const time = t.created_at ? new Date(t.created_at).toLocaleString('vi-VN') : '--';

    const baseRow = `
      <td>${time}</td>
      <td>${t.symbol}</td>
      <td><span class="badge badge-${t.side}">${t.side?.toUpperCase()}</span></td>
      <td>${t.amount}</td>
      <td>${t.avg_price ? '$' + fmt(t.avg_price) : '--'}</td>
    `;

    if (showCost) {
      return `<tr>
        ${baseRow}
        <td>${t.cost ? '$' + fmt(t.cost) : '--'}</td>
        <td class="${pnlClass}">${pnlText}</td>
        <td><span class="badge badge-${t.signal_type || 'none'}">${t.signal_type || '--'}</span></td>
        <td><span class="badge badge-${t.status}">${t.status}</span></td>
      </tr>`;
    } else {
      return `<tr>
        ${baseRow}
        <td><span class="badge badge-${t.signal_type || 'none'}">${t.signal_type || '--'}</span></td>
        <td class="${pnlClass}">${pnlText}</td>
        <td><span class="badge badge-${t.status}">${t.status}</span></td>
      </tr>`;
    }
  }).join('');
}

// ─── Signals Page ─────────────────────────────────────────────────────
async function loadSignals() {
  try {
    const signals = await apiGet('/api/signals?limit=200');
    const tbody = document.getElementById('signalsBody');

    if (!signals || signals.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-row">Chưa có tín hiệu nào</td></tr>';
      return;
    }

    tbody.innerHTML = signals.map(s => {
      const time = s.timestamp ? new Date(s.timestamp).toLocaleString('vi-VN') : '--';
      const histClass = (s.macd_histogram || 0) >= 0 ? 'pnl-pos' : 'pnl-neg';
      return `<tr>
        <td>${time}</td>
        <td>${s.symbol}</td>
        <td><span class="badge badge-${s.signal_type === 'none' ? 'none' : s.signal_type?.includes('long') || s.signal_type === 'long' ? 'long' : 'short'}">${s.signal_type || '--'}</span></td>
        <td>${s.price ? '$' + fmt(s.price) : '--'}</td>
        <td>${s.ma_fast ? fmt6(s.ma_fast) : '--'}</td>
        <td>${s.ma_slow ? fmt6(s.ma_slow) : '--'}</td>
        <td>${s.macd !== null && s.macd !== undefined ? fmt6(s.macd) : '--'}</td>
        <td>${s.macd_signal !== null && s.macd_signal !== undefined ? fmt6(s.macd_signal) : '--'}</td>
        <td class="${histClass}">${s.macd_histogram !== null && s.macd_histogram !== undefined ? fmt6(s.macd_histogram) : '--'}</td>
        <td><span class="badge ${s.executed ? 'badge-filled' : 'badge-none'}">${s.executed ? '✓' : '○'}</span></td>
      </tr>`;
    }).join('');
  } catch (e) {
    showToast('Lỗi tải tín hiệu', 'error');
  }
}

// ─── Chart ────────────────────────────────────────────────────────────
async function loadChart() {
  const symbol = document.getElementById('chartSymbol').value;
  const timeframe = document.getElementById('chartTimeframe').value;

  try {
    const data = await apiGet(`/api/chart/${symbol}?timeframe=${timeframe}&limit=100`);
    if (!data || data.length === 0) {
      showToast('Không có dữ liệu chart — Exchange chưa kết nối', 'error');
      return;
    }

    renderPriceChart(data);
    renderMacdChart(data);
  } catch (e) {
    showToast('Lỗi tải chart: ' + e.message, 'error');
  }
}

function renderPriceChart(data) {
  const ctx = document.getElementById('priceChart').getContext('2d');
  
  if (state.priceChart) {
    state.priceChart.destroy();
  }

  const labels = data.map(d => {
    const dt = new Date(d.timestamp);
    return dt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  });

  state.priceChart = new Chart(ctx, {
    type: 'candlestick',
    data: {
      datasets: [
        {
          label: 'Nến Nhật',
          data: data.map(d => ({
            x: new Date(d.timestamp).getTime(),
            o: d.open,
            h: d.high,
            l: d.low,
            c: d.close
          })),
          color: {
            up: 'rgba(14,203,129,1)',
            down: 'rgba(246,70,93,1)',
            unchanged: '#999',
          },
          borderColor: {
            up: 'rgba(14,203,129,1)',
            down: 'rgba(246,70,93,1)',
            unchanged: '#999',
          }
        },
        {
          label: 'MA Fast',
          type: 'line',
          data: data.map(d => ({x: new Date(d.timestamp).getTime(), y: d.ma_fast})),
          borderColor: '#4183f4',
          borderWidth: 1.5,
          borderDash: [],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'MA Slow',
          type: 'line',
          data: data.map(d => ({x: new Date(d.timestamp).getTime(), y: d.ma_slow})),
          borderColor: '#f7931a',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: {
          labels: { color: '#8892a4', font: { size: 11 }, boxWidth: 24 }
        },
        tooltip: {
          backgroundColor: '#161a22',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          titleColor: '#e8eaf0',
          bodyColor: '#8892a4',
          callbacks: {
            label: ctx => `${ctx.dataset.label}: $${ctx.raw?.toFixed(4) || '--'}`,
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#525f74', maxTicksLimit: 10, font: { size: 10 } },
        },
        y: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            color: '#525f74', font: { size: 10 },
            callback: v => '$' + v.toFixed(2),
          },
          position: 'right',
        },
      },
    },
  });
}

function renderMacdChart(data) {
  const ctx = document.getElementById('macdChart').getContext('2d');

  if (state.macdChart) {
    state.macdChart.destroy();
  }

  const labels = data.map(d => {
    const dt = new Date(d.timestamp);
    return dt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  });

  const histColors = data.map(d =>
    (d.macd_histogram || 0) >= 0
      ? 'rgba(14,203,129,0.6)'
      : 'rgba(246,70,93,0.6)'
  );

  state.macdChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'MACD Histogram',
          data: data.map(d => d.macd_histogram),
          backgroundColor: histColors,
          borderRadius: 2,
          order: 2,
        },
        {
          label: 'MACD',
          data: data.map(d => d.macd),
          borderColor: '#4183f4',
          borderWidth: 1.5,
          pointRadius: 0,
          type: 'line',
          tension: 0.3,
          fill: false,
          order: 1,
        },
        {
          label: 'Signal',
          data: data.map(d => d.macd_signal),
          borderColor: '#f6465d',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          type: 'line',
          tension: 0.3,
          fill: false,
          order: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: {
          labels: { color: '#8892a4', font: { size: 10 }, boxWidth: 20 }
        },
        tooltip: {
          backgroundColor: '#161a22',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          titleColor: '#e8eaf0',
          bodyColor: '#8892a4',
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#525f74', maxTicksLimit: 10, font: { size: 10 } },
        },
        y: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#525f74', font: { size: 10 } },
          position: 'right',
        },
      },
    },
  });
}

// ─── Config ───────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const config = await apiGet('/api/config');
    const view = document.getElementById('configView');
    if (!config || Object.keys(config).length === 0) {
      view.textContent = '⚠️ Bot chưa kết nối. Khởi động bot để xem cấu hình.';
      return;
    }
    view.textContent = JSON.stringify(config, null, 2)
      .replace(/"([^"]+)":/g, '\x1b[36m$1\x1b[0m:');
    
    // Simple syntax highlight
    view.innerHTML = syntaxHighlight(JSON.stringify(config, null, 2));
  } catch (e) {
    document.getElementById('configView').textContent = '⚠️ Không tải được cấu hình';
  }
}

function syntaxHighlight(json) {
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, match => {
      let cls = 'color: #8892a4';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) cls = 'color: #4183f4';
        else cls = 'color: #0ecb81';
      } else if (/true|false/.test(match)) {
        cls = 'color: #f7931a';
      } else if (/null/.test(match)) {
        cls = 'color: #f6465d';
      } else {
        cls = 'color: #F0B90B';
      }
      return `<span style="${cls}">${match}</span>`;
    });
}

// ─── Bot Controls ─────────────────────────────────────────────────────
async function startBot() {
  try {
    const result = await apiPost('/api/bot/start');
    showToast(`✅ ${result.message}`, 'success');
    setTimeout(loadBotStatus, 1000);
  } catch (e) {
    showToast('❌ Lỗi khởi động bot: ' + e.message, 'error');
  }
}

async function stopBot() {
  try {
    const result = await apiPost('/api/bot/stop');
    showToast(`⏹ ${result.message}`, 'info');
    setTimeout(loadBotStatus, 1000);
  } catch (e) {
    showToast('❌ Lỗi dừng bot: ' + e.message, 'error');
  }
}

// ─── Auto Refresh ─────────────────────────────────────────────────────
function startAutoRefresh() {
  state.refreshInterval = setInterval(() => {
    if (state.currentPage === 'dashboard') {
      loadStats();
      loadRecentTrades();
    }
  }, 30000); // Refresh mỗi 30 giây
}

// ─── Toast Notifications ──────────────────────────────────────────────
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;

  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ─── Formatters ───────────────────────────────────────────────────────
function fmt(val) {
  if (val === null || val === undefined) return '--';
  return Number(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmt6(val) {
  if (val === null || val === undefined) return '--';
  return Number(val).toFixed(6);
}
