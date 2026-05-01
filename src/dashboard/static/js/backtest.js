/**
 * backtest.js — Backtest UI module
 * Handles form submission, result rendering, equity chart, trade table
 */
import { showToast } from './ui.js';

// Store full trade list for client-side filtering
let _allTrades = [];
let _equityChart = null;

// ── API ───────────────────────────────────────────────────────────────────────

async function apiBots() {
  const r = await fetch('/api/bots');
  return r.json();
}

async function apiStartBacktest(payload) {
  const r = await fetch('/api/backtest/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || 'Backtest thất bại');
  }
  return r.json();  // { job_id, status }
}

async function apiPollProgress(jobId) {
  const r = await fetch(`/api/backtest/progress/${jobId}`);
  return r.json();
}

// ── Page init ─────────────────────────────────────────────────────────────────

function _onBotChange() {
  const sel = document.getElementById('btBotId');
  const opt = sel.options[sel.selectedIndex];
  const strategy = opt ? opt.getAttribute('data-strategy') : '';
  const slTpGroup = document.getElementById('btSlTpGroup');
  if (slTpGroup) {
    slTpGroup.style.display = strategy === 'sma_macd_cross_v4' ? 'block' : 'none';
  }
}

export async function loadBacktestPage() {
  // Populate bot dropdown
  try {
    const bots = await apiBots();
    const sel = document.getElementById('btBotId');
    sel.innerHTML = bots.map(b =>
      `<option value="${b.id}" data-strategy="${b.strategy_name}">#${b.id} ${b.name} (${b.strategy_name})</option>`
    ).join('');
    // Trigger show/hide SL/TP on initial load
    _onBotChange();
    sel.addEventListener('change', _onBotChange);
  } catch (e) {
    showToast('Không tải được danh sách bot', 'error');
  }

  // Default start date: 30 days ago
  const d = new Date();
  d.setDate(d.getDate() - 30);
  const defaultDate = d.toISOString().slice(0, 10);
  document.getElementById('btStartDate').value = defaultDate;
  document.getElementById('btEndDate').value = '';
  // Strategy form defaults
  if (document.getElementById('btSStartDate')) {
    document.getElementById('btSStartDate').value = defaultDate;
    document.getElementById('btSEndDate').value = '';
  }

  // Reset result panels
  _resetResults();
}

// ── Run backtest ──────────────────────────────────────────────────────────────

export async function runBacktest(e) {
  e.preventDefault();

  const botId      = parseInt(document.getElementById('btBotId').value);
  const startDate  = document.getElementById('btStartDate').value;
  const endDate    = document.getElementById('btEndDate').value || null;
  const balance    = parseFloat(document.getElementById('btBalance').value);
  const timeframe  = document.getElementById('btTimeframe').value || null;
  const slPct      = document.getElementById('btSlPct')?.value ? parseFloat(document.getElementById('btSlPct').value) : null;
  const tpPct      = document.getElementById('btTpPct')?.value ? parseFloat(document.getElementById('btTpPct').value) : null;

  if (!startDate) return showToast('Vui lòng chọn ngày bắt đầu', 'error');

  // Show loading, hide results
  _resetResults();
  document.getElementById('btLoading').style.display = 'block';
  const btn = document.getElementById('btRunBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Đang chạy...';

  try {
    const { job_id } = await apiStartBacktest({
      bot_id: botId,
      start_date: startDate,
      end_date: endDate,
      initial_balance: balance,
      timeframe: timeframe,
      stop_loss_pct: slPct,
      take_profit_pct: tpPct,
    });

    // Poll progress mỗi 2s
    await _pollJob(job_id);

  } catch (err) {
    showToast(`Lỗi: ${err.message}`, 'error');
    document.getElementById('btLoading').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Chạy Backtest';
  }
}

async function _pollJob(jobId) {
  const loadingEl = document.getElementById('btLoading');
  const progressEl = document.getElementById('btProgressBar');
  const progressTextEl = document.getElementById('btProgressText');

  while (true) {
    await new Promise(r => setTimeout(r, 2000));  // chờ 2s

    let job;
    try {
      job = await apiPollProgress(jobId);
    } catch (e) {
      showToast('Mất kết nối khi poll progress', 'error');
      loadingEl.style.display = 'none';
      return;
    }

    // Cập nhật progress bar
    if (progressEl) progressEl.style.width = `${job.progress}%`;
    if (progressTextEl) progressTextEl.textContent = `${job.progress}% — ${job.message}`;

    if (job.status === 'done') {
      loadingEl.style.display = 'none';
      const result = job.result;
      _allTrades = result.trades || [];
      _renderSummary(result);
      _renderEquityChart(result.equity_curve || []);
      _renderTrades(_allTrades);
      showToast(`Backtest hoàn tất — ${result.summary.total_trades} lệnh`, 'success');
      return;
    }

    if (job.status === 'error') {
      loadingEl.style.display = 'none';
      showToast(`Lỗi backtest: ${job.error}`, 'error');
      return;
    }
    // status === 'running' → tiếp tục poll
  }
}

// ── Summary ───────────────────────────────────────────────────────────────────

function _renderSummary(result) {
  document.getElementById('btLoading').style.display = 'none';

  const s = result.summary;
  const pnlColor  = s.total_pnl  >= 0 ? '#0ecb81' : '#f6465d';
  const retColor  = s.total_return_pct >= 0 ? '#0ecb81' : '#f6465d';
  const ddColor   = '#f6465d';
  const pfColor   = s.profit_factor >= 1 ? '#0ecb81' : '#f6465d';
  const srColor   = s.sharpe_ratio >= 1 ? '#0ecb81' : (s.sharpe_ratio >= 0 ? '#F0B90B' : '#f6465d');

  // Hiển thị thông tin kỳ backtest
  const tfLabel = result.timeframe || '?';
  const periodLabel = `${result.start_date || ''} → ${result.end_date || 'nay'} | TF: ${tfLabel} | ${result.symbol}`;

  const metrics = [
    { label: 'Tổng lệnh',        val: s.total_trades,                    color: '' },
    { label: 'Thắng / Thua',     val: `${s.winning_trades} / ${s.losing_trades}`, color: '' },
    { label: 'Win Rate',         val: `${s.win_rate}%`,                  color: s.win_rate >= 50 ? '#0ecb81' : '#f6465d' },
    { label: 'Tổng PnL (USDT)',  val: `${s.total_pnl >= 0 ? '+' : ''}${s.total_pnl}`, color: pnlColor },
    { label: 'Lợi nhuận (%)',    val: `${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%`, color: retColor },
    { label: 'Vốn cuối (USDT)',  val: s.final_balance,                   color: retColor },
    { label: 'Max Drawdown',     val: `-${s.max_drawdown_pct}%`,         color: ddColor },
    { label: 'Profit Factor',    val: s.profit_factor === Infinity ? '∞' : s.profit_factor, color: pfColor },
    { label: 'Sharpe Ratio',     val: s.sharpe_ratio,                    color: srColor },
    { label: 'TB Thắng (USDT)',  val: `+${s.avg_win}`,                   color: '#0ecb81' },
    { label: 'TB Thua (USDT)',   val: s.avg_loss,                        color: '#f6465d' },
    { label: 'Lớn nhất Thắng',  val: `+${s.largest_win}`,               color: '#0ecb81' },
    { label: 'Lớn nhất Thua',   val: s.largest_loss,                    color: '#f6465d' },
    { label: 'TB giữ (nến)',     val: s.avg_holding_candles,             color: '' },
  ];

  document.getElementById('btSummaryGrid').innerHTML = metrics.map(m => `
    <div class="stat-card">
      <h3>${m.label}</h3>
      <div class="val" style="${m.color ? `color:${m.color}` : ''}">${m.val}</div>
    </div>
  `).join('');

  // Hiển thị period info dưới tiêu đề
  const periodEl = document.getElementById('btPeriodInfo');
  if (periodEl) periodEl.textContent = periodLabel;

  // Download link
  const dl = document.getElementById('btDownloadLink');
  dl.href = result.download_url;
  dl.download = result.excel_filename;

  document.getElementById('btSummaryCard').style.display = 'block';
}

// ── Equity Chart ──────────────────────────────────────────────────────────────

function _renderEquityChart(equityCurve) {
  if (!equityCurve || equityCurve.length < 2) return;

  document.getElementById('btEquityCard').style.display = 'block';

  const labels   = equityCurve.map(e => e.ts);
  const balances = equityCurve.map(e => e.balance);
  const drawdowns = equityCurve.map(e => -e.drawdown_pct);  // negative for visual

  const ctx = document.getElementById('btEquityChart').getContext('2d');

  if (_equityChart) {
    _equityChart.destroy();
    _equityChart = null;
  }

  _equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Số dư (USDT)',
          data: balances,
          borderColor: '#4183f4',
          backgroundColor: 'rgba(65,131,244,0.08)',
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.3,
          yAxisID: 'y',
        },
        {
          label: 'Drawdown (%)',
          data: drawdowns,
          borderColor: '#f6465d',
          backgroundColor: 'rgba(246,70,93,0.08)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.3,
          yAxisID: 'y2',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#b0b8c1' } },
        tooltip: {
          callbacks: {
            title: (items) => {
              const ts = items[0].label;
              const d = new Date(ts);
              return d.toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
            },
            label: (item) => {
              if (item.datasetIndex === 0) return ` Số dư: $${item.raw.toFixed(2)}`;
              return ` Drawdown: ${Math.abs(item.raw).toFixed(2)}%`;
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'day', displayFormats: { day: 'dd/MM' } },
          ticks: { color: '#b0b8c1', maxTicksLimit: 10 },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y: {
          position: 'left',
          ticks: { color: '#4183f4', callback: v => `$${v.toFixed(0)}` },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y2: {
          position: 'right',
          ticks: { color: '#f6465d', callback: v => `${Math.abs(v).toFixed(1)}%` },
          grid: { display: false },
        },
      },
    },
  });
}

// ── Trade table ───────────────────────────────────────────────────────────────

function _renderTrades(trades) {
  document.getElementById('btTradeCount').textContent = trades.length;
  document.getElementById('btTradesCard').style.display = 'block';

  const tbody = document.getElementById('btTradesBody');
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-state">Không có lệnh nào</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map((t, i) => {
    const pnlColor = t.pnl >= 0 ? '#0ecb81' : '#f6465d';
    const sideColor = t.side === 'long' ? '#0ecb81' : '#f6465d';
    const rowBg = i % 2 === 0 ? '' : 'background:rgba(255,255,255,0.02)';
    return `
      <tr style="${rowBg}">
        <td>${i + 1}</td>
        <td style="font-size:12px;">${t.entry_time}</td>
        <td style="font-size:12px;">${t.exit_time}</td>
        <td><span style="color:${sideColor}; font-weight:600;">${t.side.toUpperCase()}</span></td>
        <td>${_fmt(t.entry_price)}</td>
        <td>${_fmt(t.exit_price)}</td>
        <td style="color:${pnlColor}; font-weight:600;">${t.pnl >= 0 ? '+' : ''}${t.pnl}</td>
        <td style="color:${pnlColor};">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%</td>
        <td>$${t.balance_after}</td>
        <td>${t.holding_candles}</td>
      </tr>
    `;
  }).join('');
}

export function filterBtTrades() {
  const filter = document.getElementById('btTradeFilter').value;
  let filtered = _allTrades;
  if (filter === 'win')  filtered = _allTrades.filter(t => t.pnl > 0);
  if (filter === 'loss') filtered = _allTrades.filter(t => t.pnl <= 0);
  _renderTrades(filtered);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _fmt(n) {
  if (n === null || n === undefined) return '-';
  if (n >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return n.toFixed(4);
}

function _resetResults() {
  document.getElementById('btSummaryCard').style.display  = 'none';
  document.getElementById('btEquityCard').style.display   = 'none';
  document.getElementById('btTradesCard').style.display   = 'none';
  document.getElementById('btLoading').style.display      = 'none';
  _allTrades = [];
  if (_equityChart) { _equityChart.destroy(); _equityChart = null; }
}

// ── Tab switching ─────────────────────────────────────────────────────────────

export function switchBtTab(tab) {
  const stratPanel = document.getElementById('btPanelStrategy');
  const botPanel   = document.getElementById('btPanelBot');
  const tabS = document.getElementById('btTabStrategy');
  const tabB = document.getElementById('btTabBot');
  if (tab === 'strategy') {
    stratPanel.style.display = '';
    botPanel.style.display   = 'none';
    tabS.className = 'btn btn-primary';
    tabB.className = 'btn';
    tabB.style.cssText = 'padding:8px 20px; background:var(--bg-panel); color:var(--text-primary); border:1px solid var(--border);';
  } else {
    stratPanel.style.display = 'none';
    botPanel.style.display   = '';
    tabB.className = 'btn btn-primary';
    tabS.className = 'btn';
    tabS.style.cssText = 'padding:8px 20px; background:var(--bg-panel); color:var(--text-primary); border:1px solid var(--border);';
  }
  _resetResults();
}

export function onStrategyChange() {
  const v = document.getElementById('btStrategyName').value;
  document.getElementById('btSV2Params').style.display = (v === 'sma_macd_cross_v2' || v === 'sma_macd_cross_v3') ? 'block' : 'none';
  document.getElementById('btSV3Params').style.display = (v === 'sma_macd_cross_v3') ? 'block' : 'none';
  document.getElementById('btSV4Params').style.display = (v === 'sma_macd_cross_v4' || v === 'sma_macd_cross_v5') ? 'block' : 'none';
}

// ── Run strategy backtest ─────────────────────────────────────────────────────

export async function runStrategyBacktest(e) {
  e.preventDefault();

  const strategy  = document.getElementById('btStrategyName').value;
  const symbol    = document.getElementById('btSymbol').value.trim().toUpperCase();
  const startDate = document.getElementById('btSStartDate').value;
  const endDate   = document.getElementById('btSEndDate').value || null;
  const balance   = parseFloat(document.getElementById('btSBalance').value);
  const timeframe = document.getElementById('btSTimeframe').value || null;
  const bbLength  = document.getElementById('btSBbLength').value ? parseInt(document.getElementById('btSBbLength').value) : null;

  if (!symbol) return showToast('Vui lòng nhập cặp tiền', 'error');
  if (!startDate) return showToast('Vui lòng chọn ngày bắt đầu', 'error');

  const payload = {
    strategy_name: strategy,
    symbol,
    start_date: startDate,
    end_date: endDate,
    initial_balance: balance,
    timeframe,
    bb_length: bbLength,
  };

  // V2/V3 params
  const useTrend = document.getElementById('btSUseTrend')?.value;
  if (useTrend === 'true')  payload.use_trend_filter = true;
  if (useTrend === 'false') payload.use_trend_filter = false;

  // V3 params
  const minDist = document.getElementById('btSMinDist')?.value;
  const minHold = document.getElementById('btSMinHold')?.value;
  if (minDist) payload.min_ma_distance_pct = parseFloat(minDist);
  if (minHold) payload.min_hold_candles = parseInt(minHold);

  // V4 params
  const lev     = document.getElementById('btSLeverage')?.value;
  const notional= document.getElementById('btSNotional')?.value;
  const sl      = document.getElementById('btSSl')?.value;
  const tp      = document.getElementById('btSTp')?.value;
  if (lev)      payload.leverage_v4    = parseInt(lev);
  if (notional) payload.notional_usdt  = parseFloat(notional);
  if (sl)       payload.stop_loss_pct  = parseFloat(sl);
  if (tp)       payload.take_profit_pct = parseFloat(tp);

  _resetResults();
  document.getElementById('btLoading').style.display = 'block';
  const btn = document.getElementById('btSRunBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Đang chạy...';

  try {
    const r = await fetch('/api/backtest/run-strategy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Lỗi');
    }
    const { job_id } = await r.json();
    await _pollJob(job_id);
  } catch (err) {
    showToast(`Lỗi: ${err.message}`, 'error');
    document.getElementById('btLoading').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Chạy Backtest';
  }
}
