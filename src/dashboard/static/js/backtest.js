/**
 * backtest.js — Backtest UI module
 * Handles form submission, result rendering, equity chart, trade table
 */
import { showToast } from './ui.js';
import { renderBacktestChart, scrollChartToTrade, destroyBacktestChart } from './backtest_chart.js';

// Store full trade list for client-side filtering
let _allTrades = [];
let _equityChart = null;

// ── Error display ─────────────────────────────────────────────────────────────

function _showBacktestError(message) {
  /**
   * Hiển thị lỗi backtest đầy đủ trong panel riêng.
   * Dùng cho các lỗi quan trọng như thiếu data, gap data, v.v.
   */
  // Tìm hoặc tạo error panel
  let panel = document.getElementById('btErrorPanel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'btErrorPanel';
    panel.style.cssText = [
      'background:#2a0a0a', 'border:1px solid #f6465d', 'border-radius:8px',
      'padding:16px 20px', 'margin-bottom:20px', 'display:none',
    ].join(';');
    // Chèn vào đầu form backtest
    const form = document.getElementById('btStrategyForm') || document.getElementById('btBotForm');
    if (form) form.parentNode.insertBefore(panel, form);
  }

  // Format message: xuống dòng → <br>, ❌ → icon đỏ
  const formatted = message
    .replace(/\n/g, '<br>')
    .replace(/→/g, '<span style="color:#F0B90B">→</span>');

  panel.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
      <div>
        <div style="color:#f6465d; font-weight:bold; margin-bottom:8px; font-size:15px;">
          ⚠️ Backtest thất bại
        </div>
        <div style="color:#ffb3b3; font-size:13px; line-height:1.6;">${formatted}</div>
      </div>
      <button onclick="document.getElementById('btErrorPanel').style.display='none'"
        style="background:none; border:none; color:#888; cursor:pointer; font-size:18px; margin-left:12px; flex-shrink:0;">✕</button>
    </div>
  `;
  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

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

  // Ẩn error panel cũ nếu có
  const errPanel = document.getElementById('btErrorPanel');
  if (errPanel) errPanel.style.display = 'none';

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
  const loadingEl     = document.getElementById('btLoading');
  const progressEl    = document.getElementById('btProgressBar');
  const progressTextEl= document.getElementById('btProgressText');
  const progressPctEl = document.getElementById('btProgressPct');
  const elapsedEl     = document.getElementById('btElapsedTime');
  const spinnerEl     = document.getElementById('btLoadingSpinner');

  const startTime = Date.now();

  // Cập nhật elapsed time mỗi giây
  const elapsedTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - startTime) / 1000);
    if (elapsedEl) {
      elapsedEl.textContent = sec < 60
        ? `${sec}s`
        : `${Math.floor(sec / 60)}m ${sec % 60}s`;
    }
  }, 1000);

  /**
   * Map progress % → step index (1-5):
   *  0–8%   → step 1: Kiểm tra dữ liệu
   *  8–15%  → step 2: Đọc DB
   *  15–25% → step 3: Tính indicators
   *  25–90% → step 4: Simulate
   *  90–100%→ step 5: Thống kê & Excel
   */
  function _updateSteps(pct, message) {
    let activeStep = 1;
    if (pct >= 90) activeStep = 5;
    else if (pct >= 25) activeStep = 4;
    else if (pct >= 15) activeStep = 3;
    else if (pct >= 8)  activeStep = 2;

    for (let s = 1; s <= 5; s++) {
      const el = document.getElementById(`btStep${s}`);
      if (!el) continue;
      const icon  = el.querySelector('.bt-step-icon');
      const label = el.querySelector('.bt-step-label');
      const detail = el.querySelector('.bt-step-detail');

      el.classList.remove('active', 'done');
      if (s < activeStep) {
        el.classList.add('done');
        if (icon) icon.textContent = '✅';
        if (label) label.style.color = 'var(--text-secondary)';
      } else if (s === activeStep) {
        el.classList.add('active');
        if (icon) icon.textContent = '🔄';
        if (label) label.style.color = 'var(--text-primary)';
        // Hiển thị message chi tiết ở step đang active
        if (detail) detail.textContent = message || '';
        else {
          // Thêm detail span nếu chưa có
          const span = document.createElement('span');
          span.className = 'bt-step-detail';
          span.textContent = message || '';
          el.appendChild(span);
        }
      } else {
        if (icon) icon.textContent = '⬜';
        if (label) label.style.color = 'var(--text-secondary)';
        // Xóa detail của step chưa đến
        const detail2 = el.querySelector('.bt-step-detail');
        if (detail2) detail2.textContent = '';
      }
    }
  }

  function _markAllDone() {
    for (let s = 1; s <= 5; s++) {
      const el = document.getElementById(`btStep${s}`);
      if (!el) continue;
      el.classList.remove('active');
      el.classList.add('done');
      const icon = el.querySelector('.bt-step-icon');
      if (icon) icon.textContent = '✅';
    }
    if (spinnerEl) spinnerEl.style.animation = 'none';
    if (spinnerEl) spinnerEl.textContent = '✅';
  }

  while (true) {
    await new Promise(r => setTimeout(r, 1500));  // poll mỗi 1.5s

    let job;
    try {
      job = await apiPollProgress(jobId);
    } catch (e) {
      clearInterval(elapsedTimer);
      showToast('Mất kết nối khi poll progress', 'error');
      loadingEl.style.display = 'none';
      return;
    }

    const pct = job.progress || 0;
    const msg = job.message || '';

    // Cập nhật progress bar và text
    if (progressEl)     progressEl.style.width = `${pct}%`;
    if (progressPctEl)  progressPctEl.textContent = `${pct}%`;
    if (progressTextEl) progressTextEl.textContent = msg;

    // Cập nhật steps
    _updateSteps(pct, msg);

    if (job.status === 'done') {
      clearInterval(elapsedTimer);
      _markAllDone();
      if (progressEl) progressEl.style.width = '100%';
      if (progressPctEl) progressPctEl.textContent = '100%';

      // Ẩn loading sau 800ms để user thấy 100%
      setTimeout(() => { loadingEl.style.display = 'none'; }, 800);

      const result = job.result;
      _allTrades = result.trades || [];
      _renderSummary(result);
      _renderEquityChart(result.equity_curve || []);
      _renderTrades(_allTrades);

      // Vẽ backtest chart (candlestick + indicators + entry/exit)
      renderBacktestChart(jobId);

      const sec = Math.floor((Date.now() - startTime) / 1000);
      const timeStr = sec < 60 ? `${sec}s` : `${Math.floor(sec/60)}m ${sec%60}s`;
      showToast(`✅ Backtest hoàn tất — ${result.summary.total_trades} lệnh (${timeStr})`, 'success');
      return;
    }

    if (job.status === 'error') {
      clearInterval(elapsedTimer);
      loadingEl.style.display = 'none';
      // Hiển thị lỗi đầy đủ — đặc biệt quan trọng với lỗi thiếu data
      const errMsg = job.error || job.message || 'Lỗi không xác định';
      // Nếu lỗi dài (thiếu data, gap...) → hiển thị trong panel riêng thay vì toast
      if (errMsg.length > 80 || errMsg.includes('❌')) {
        _showBacktestError(errMsg);
      } else {
        showToast(`Lỗi backtest: ${errMsg}`, 'error');
      }
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
  const commLabel = s.commission_pct != null ? ` | Comm: ${(s.commission_pct * 100).toFixed(3)}%` : '';
  const slipLabel = s.slippage_pct != null && s.slippage_pct > 0 ? ` | Slip: ${(s.slippage_pct * 100).toFixed(3)}%` : '';
  const periodLabel = `${result.start_date || ''} → ${result.end_date || 'nay'} | TF: ${tfLabel} | ${result.symbol}${commLabel}${slipLabel}`;

  const mddEqPct = s.mdd_equity_pct ?? s.max_drawdown_pct;
  const mddColor = mddEqPct > 20 ? '#f6465d' : mddEqPct > 10 ? '#F0B90B' : '#b0b8c1';

  const metrics = [
    { label: 'Tổng lệnh',        val: s.total_trades,                    color: '' },
    { label: 'Thắng / Thua',     val: `${s.winning_trades} / ${s.losing_trades}`, color: '' },
    { label: 'Win Rate',         val: `${s.win_rate}%`,                  color: s.win_rate >= 50 ? '#0ecb81' : '#f6465d' },
    { label: 'Tổng PnL (USDT)',  val: `${s.total_pnl >= 0 ? '+' : ''}${s.total_pnl}`, color: pnlColor },
    { label: 'Lợi nhuận (%)',    val: `${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%`, color: retColor },
    { label: 'Vốn cuối (USDT)',  val: s.final_balance,                   color: retColor },
    { label: 'Profit Factor',    val: s.profit_factor === Infinity ? '∞' : s.profit_factor, color: pfColor },
    { label: 'Sharpe Ratio',     val: s.sharpe_ratio,                    color: srColor },
    { label: 'TB Thắng (USDT)',  val: `+${s.avg_win}`,                   color: '#0ecb81' },
    { label: 'TB Thua (USDT)',   val: s.avg_loss,                        color: '#f6465d' },
    { label: 'Lớn nhất Thắng',  val: `+${s.largest_win}`,               color: '#0ecb81' },
    { label: 'Lớn nhất Thua',   val: s.largest_loss,                    color: '#f6465d' },
    { label: 'TB giữ (nến)',     val: s.avg_holding_candles,             color: '' },
    { label: 'Tổng hoa hồng',   val: s.total_commission != null ? `-${s.total_commission}` : '-', color: '#f6465d' },
    { label: 'Tổng trượt giá',  val: s.total_slippage_cost != null ? `-${s.total_slippage_cost}` : '-', color: s.total_slippage_cost > 0 ? '#f6465d' : '' },
  ];

  // MDD block riêng — hiển thị nổi bật bên dưới metrics chính
  const mddRecovery = s.mdd_recovery_days != null
    ? `${s.mdd_recovery_days} ngày`
    : '<span style="color:#f6465d">⚠ Chưa hồi phục</span>';
  const mddHtml = `
    <div style="margin-top:16px; padding:14px 16px; background:rgba(197,90,17,0.12);
                border:1px solid rgba(197,90,17,0.4); border-radius:8px;">
      <div style="font-size:12px; font-weight:700; color:#C55A11; margin-bottom:10px; letter-spacing:0.5px;">
        🔥 PHÂN TÍCH MAX DRAWDOWN (EQUITY CURVE)
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:8px;">
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>MDD Equity (%)</h3>
          <div class="val" style="color:${mddColor}">-${mddEqPct}%</div>
        </div>
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>MDD Equity (USDT)</h3>
          <div class="val" style="color:#f6465d">-${s.mdd_equity_usdt ?? '-'}</div>
        </div>
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>MDD Duration</h3>
          <div class="val" style="color:#f6465d">${s.mdd_duration_days != null ? s.mdd_duration_days + ' ngày' : '-'}</div>
        </div>
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>MDD Recovery</h3>
          <div class="val">${mddRecovery}</div>
        </div>
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>MDD (đóng lệnh)</h3>
          <div class="val" style="color:${ddColor}">-${s.max_drawdown_pct}%</div>
        </div>
        <div class="stat-card" style="border:1px solid rgba(197,90,17,0.3);">
          <h3>Đỉnh → Đáy</h3>
          <div class="val" style="font-size:11px; color:#b0b8c1;">
            ${s.mdd_peak_ts || '-'}<br>→ ${s.mdd_trough_ts || '-'}
          </div>
        </div>
      </div>
    </div>
  `;

  const metricsHtml = metrics.map(m => `
    <div class="stat-card">
      <h3>${m.label}</h3>
      <div class="val" style="${m.color ? `color:${m.color}` : ''}">${m.val}</div>
    </div>
  `).join('');

  const fullHtml = metricsHtml + mddHtml;

  // Detect active tab: strategy tab or bot tab
  const isStrategyTab = document.getElementById('btPanelStrategy')?.style.display !== 'none';

  if (isStrategyTab) {
    // Strategy tab: render into btSSummaryCard
    const card = document.getElementById('btSSummaryCard');
    if (card) {
      document.getElementById('btSSummaryGrid').innerHTML = fullHtml;
      const periodEl = document.getElementById('btSPeriodInfo');
      if (periodEl) periodEl.textContent = periodLabel;
      const dl = document.getElementById('btSDownloadLink');
      if (dl) { dl.href = result.download_url; dl.download = result.excel_filename; }
      card.style.display = 'block';
    }
  } else {
    // Bot tab: render into btSummaryCard
    document.getElementById('btSummaryGrid').innerHTML = fullHtml;
    const periodEl = document.getElementById('btPeriodInfo');
    if (periodEl) periodEl.textContent = periodLabel;
    const dl = document.getElementById('btDownloadLink');
    if (dl) { dl.href = result.download_url; dl.download = result.excel_filename; }
    document.getElementById('btSummaryCard').style.display = 'block';
  }
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
    const pnlColor  = t.pnl >= 0 ? '#0ecb81' : '#f6465d';
    const sideColor = t.side === 'long' ? '#0ecb81' : '#f6465d';
    const rowBg     = i % 2 === 0 ? '' : 'background:rgba(255,255,255,0.02)';
    return `
      <tr style="${rowBg}; cursor:pointer;" data-trade-idx="${i}"
          title="Click để xem trên biểu đồ">
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

  // Click vào row → scroll chart đến lệnh đó
  tbody.querySelectorAll('tr[data-trade-idx]').forEach(row => {
    row.addEventListener('click', () => {
      const idx = parseInt(row.getAttribute('data-trade-idx'));
      scrollChartToTrade(idx);
      // Scroll lên chart
      const container = document.getElementById('btChartContainer');
      if (container) container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
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
  const sCard = document.getElementById('btSSummaryCard');
  if (sCard) sCard.style.display = 'none';
  document.getElementById('btEquityCard').style.display   = 'none';
  document.getElementById('btTradesCard').style.display   = 'none';
  document.getElementById('btLoading').style.display      = 'none';
  const chartContainer = document.getElementById('btChartContainer');
  if (chartContainer) chartContainer.style.display = 'none';
  _allTrades = [];
  if (_equityChart) { _equityChart.destroy(); _equityChart = null; }
  destroyBacktestChart();
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
  document.getElementById('btSV6Params').style.display = (v === 'sma_macd_cross_v6') ? 'block' : 'none';
  document.getElementById('btSV7Params').style.display = (v === 'sma_macd_cross_v7') ? 'block' : 'none';
  document.getElementById('btSAdtsParams').style.display = (v === 'adts') ? 'block' : 'none';
  // bb_length field: hide for ADTS (uses its own bbwidth_sma_period)
  const bbLenGroup = document.getElementById('btSBbLengthGroup');
  if (bbLenGroup) bbLenGroup.style.display = (v === 'adts') ? 'none' : 'block';
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

  // V6 params
  const adxEntryThr = document.getElementById('btSAdxEntryThreshold')?.value;
  const adxExitThr  = document.getElementById('btSAdxExitThreshold')?.value;
  const levV6       = document.getElementById('btSLeverageV6')?.value;
  if (adxEntryThr) payload.adx_entry_threshold = parseFloat(adxEntryThr);
  if (adxExitThr)  payload.adx_exit_threshold  = parseFloat(adxExitThr);
  if (levV6)       payload.leverage_v4         = parseInt(levV6);

  // V7 params
  const bbPeriod = document.getElementById('btSBbPeriod')?.value;
  const bbMult   = document.getElementById('btSBbMult')?.value;
  const levV7    = document.getElementById('btSLeverageV7')?.value;
  if (bbPeriod) payload.bb_period  = parseInt(bbPeriod);
  if (bbMult)   payload.bb_mult    = parseFloat(bbMult);
  if (levV7)    payload.leverage_v4 = parseInt(levV7);

  // ADTS params
  const adxThr   = document.getElementById('btSAdxThreshold')?.value;
  const emgAdx   = document.getElementById('btSEmgAdx')?.value;
  const slAtr    = document.getElementById('btSSlAtr')?.value;
  const tp1Rr    = document.getElementById('btSTp1Rr')?.value;
  const tp2Trail = document.getElementById('btSTp2Trail')?.value;
  const riskPct  = document.getElementById('btSRiskPct')?.value;
  const bbwSma   = document.getElementById('btSBbwSma')?.value;
  const adtsLev  = document.getElementById('btSAdtsLeverage')?.value;
  if (adxThr)   payload.adts_adx_threshold            = parseFloat(adxThr);
  if (emgAdx)   payload.adts_emergency_adx_threshold  = parseFloat(emgAdx);
  if (slAtr)    payload.adts_sl_atr_mult               = parseFloat(slAtr);
  if (document.getElementById('btSHardSlPct')?.value)
    payload.adts_hard_sl_pct = parseFloat(document.getElementById('btSHardSlPct').value) / 100;
  if (tp1Rr)    payload.adts_tp1_rr                    = parseFloat(tp1Rr);
  if (tp2Trail) payload.adts_tp2_trail_atr_mult        = parseFloat(tp2Trail);
  if (riskPct)  payload.adts_risk_pct                  = parseFloat(riskPct) / 100;
  if (bbwSma)   payload.adts_bbwidth_sma_period        = parseInt(bbwSma);
  if (adtsLev)  payload.adts_leverage                  = parseInt(adtsLev);

  // Phí giao dịch & trượt giá — dùng chung cho mọi chiến lược
  const commission = document.getElementById('btSCommission')?.value;
  const slippage   = document.getElementById('btSSlippage')?.value;
  if (commission) payload.commission_pct = parseFloat(commission) / 100;
  if (slippage)   payload.slippage_pct   = parseFloat(slippage) / 100;

  const btn = document.getElementById('btSRunBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Đang chạy...';

  // Ẩn error panel cũ nếu có
  const errPanel = document.getElementById('btErrorPanel');
  if (errPanel) errPanel.style.display = 'none';

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
