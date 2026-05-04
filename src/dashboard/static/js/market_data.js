/**
 * market_data.js — Market Data Cache UI
 *
 * Quản lý việc xem trạng thái, trigger refresh, và theo dõi tiến độ
 * fetch data OHLCV cho từng chiến lược.
 */

const MD_API = '/api/market-data';

// ── Polling state ─────────────────────────────────────────────────────────────
let _mdGlobalJobKey = null;
let _mdGlobalPollTimer = null;
let _mdRowJobKeys = {};   // rowKey → job_key đang chạy cho row đó

// ── Helpers ───────────────────────────────────────────────────────────────────

function _fmtNum(n) {
  if (n == null) return '—';
  return n.toLocaleString('vi-VN');
}

function _lagBadge(lagHours) {
  if (lagHours == null) return '<span style="color:#888">—</span>';
  if (lagHours <= 2)   return `<span style="color:#0ecb81">${lagHours}h ✓</span>`;
  if (lagHours <= 24)  return `<span style="color:#F0B90B">${lagHours}h ⚠</span>`;
  return `<span style="color:#f6465d">${lagHours}h ✗</span>`;
}

function _statusBadge(status) {
  const map = {
    done:         '<span style="color:#0ecb81">✓ Done</span>',
    partial_done: '<span style="color:#F0B90B">⚠ Partial</span>',
    running:      '<span style="color:#4183f4">⟳ Running</span>',
    pending:      '<span style="color:#888">⏳ Pending</span>',
    failed:       '<span style="color:#f6465d">✗ Failed</span>',
  };
  return map[status] || `<span>${status}</span>`;
}

function _rowKey(ds) {
  return `${ds.strategy_name}:${ds.symbol}:${ds.timeframe}`;
}

// ── Load status table ─────────────────────────────────────────────────────────

export async function mdRefreshStatus() {
  const tbody = document.getElementById('mdStatusBody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:20px; color:var(--text-secondary);">Đang tải...</td></tr>';

  try {
    const res = await fetch(`${MD_API}/status`);
    const datasets = await res.json();

    if (!datasets.length) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:30px; color:var(--text-secondary);">Không có dataset nào. Hãy tạo bot trước.</td></tr>';
      return;
    }

    tbody.innerHTML = datasets.map(ds => {
      const rk = _rowKey(ds);
      const hasData = ds.count > 0;
      const statusHtml = hasData
        ? `<span style="color:#0ecb81">✓ Có data</span>`
        : `<span style="color:#f6465d">✗ Chưa có</span>`;

      return `
        <tr id="mdRow_${rk.replace(/:/g, '_')}">
          <td><code>${ds.strategy_name}</code></td>
          <td><strong>${ds.symbol}</strong></td>
          <td>${ds.timeframe}</td>
          <td>${_fmtNum(ds.count)}</td>
          <td>${ds.min_date || '—'}</td>
          <td>${ds.max_date || '—'}</td>
          <td>${_lagBadge(ds.lag_hours)}</td>
          <td>${statusHtml}</td>
          <td>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              <button onclick="mdRefreshOne('${ds.strategy_name}','${ds.symbol}','${ds.timeframe}',false)"
                style="padding:4px 10px; font-size:12px; background:#1a6b3a; color:#fff; border:none; border-radius:4px; cursor:pointer;">
                ⬆ Update
              </button>
              <button onclick="mdRefreshOne('${ds.strategy_name}','${ds.symbol}','${ds.timeframe}',true)"
                style="padding:4px 10px; font-size:12px; background:#7a1a1a; color:#fff; border:none; border-radius:4px; cursor:pointer;">
                🔁 Full
              </button>
            </div>
            <div id="mdRowProgress_${rk.replace(/:/g, '_')}" style="margin-top:6px; display:none;">
              <div style="background:var(--border); border-radius:3px; height:5px; overflow:hidden;">
                <div id="mdRowBar_${rk.replace(/:/g, '_')}" style="height:100%; background:var(--accent); width:0%; transition:width 0.3s;"></div>
              </div>
              <div id="mdRowMsg_${rk.replace(/:/g, '_')}" style="font-size:11px; color:var(--text-secondary); margin-top:3px;"></div>
            </div>
          </td>
        </tr>`;
    }).join('');

  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" style="color:#f6465d; padding:20px;">Lỗi: ${e.message}</td></tr>`;
  }
}

// ── Refresh 1 dataset ─────────────────────────────────────────────────────────

export async function mdRefreshOne(strategy, symbol, tf, fullRefresh) {
  const rk = `${strategy}:${symbol}:${tf}`;
  const rkSafe = rk.replace(/:/g, '_');

  const progressDiv = document.getElementById(`mdRowProgress_${rkSafe}`);
  const bar         = document.getElementById(`mdRowBar_${rkSafe}`);
  const msg         = document.getElementById(`mdRowMsg_${rkSafe}`);

  if (progressDiv) progressDiv.style.display = 'block';
  if (bar) bar.style.width = '0%';
  if (msg) msg.textContent = 'Đang khởi động...';

  try {
    const res = await fetch(`${MD_API}/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy_name: strategy, symbol, timeframe: tf, full_refresh: fullRefresh }),
    });
    const data = await res.json();
    const jobKey = data.job_key;
    _mdRowJobKeys[rk] = jobKey;

    // Poll tiến độ
    _pollRowJob(rk, jobKey, bar, msg, progressDiv);

  } catch (e) {
    if (msg) msg.textContent = `Lỗi: ${e.message}`;
  }
}

function _pollRowJob(rk, jobKey, bar, msg, progressDiv) {
  const timer = setInterval(async () => {
    try {
      const res = await fetch(`${MD_API}/refresh/${encodeURIComponent(jobKey)}`);
      if (!res.ok) { clearInterval(timer); return; }
      const job = await res.json();

      const pct = job.progress || 0;
      if (bar) bar.style.width = `${pct}%`;
      if (msg) msg.textContent = job.message || '';

      if (job.status === 'done' || job.status === 'error') {
        clearInterval(timer);
        if (job.status === 'done') {
          if (bar) bar.style.background = '#0ecb81';
          setTimeout(() => {
            if (progressDiv) progressDiv.style.display = 'none';
            mdRefreshStatus();  // reload bảng
          }, 2000);
        } else {
          if (bar) bar.style.background = '#f6465d';
          if (msg) msg.textContent = `Lỗi: ${job.error}`;
        }
      }
    } catch (e) {
      clearInterval(timer);
    }
  }, 1500);
}

// ── Refresh All ───────────────────────────────────────────────────────────────

export async function mdRefreshAll(fullRefresh) {
  const label = fullRefresh ? 'Full Refresh tất cả' : 'Incremental Update tất cả';
  if (!confirm(`Xác nhận: ${label}?`)) return;

  _showGlobalProgress(true, 'Đang khởi động...', 0);

  try {
    const res = await fetch(`${MD_API}/refresh-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_refresh: fullRefresh }),
    });
    const data = await res.json();
    _mdGlobalJobKey = data.job_key;
    _pollGlobalJob(_mdGlobalJobKey);
  } catch (e) {
    _showGlobalProgress(true, `Lỗi: ${e.message}`, 0);
  }
}

function _pollGlobalJob(jobKey) {
  if (_mdGlobalPollTimer) clearInterval(_mdGlobalPollTimer);
  _mdGlobalPollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${MD_API}/refresh/${encodeURIComponent(jobKey)}`);
      if (!res.ok) { clearInterval(_mdGlobalPollTimer); return; }
      const job = await res.json();

      _showGlobalProgress(true, job.message || '', job.progress || 0);

      if (job.status === 'done' || job.status === 'error') {
        clearInterval(_mdGlobalPollTimer);
        if (job.status === 'done') {
          setTimeout(() => {
            _showGlobalProgress(false);
            mdRefreshStatus();
            mdLoadJobs();
          }, 3000);
        }
      }
    } catch (e) {
      clearInterval(_mdGlobalPollTimer);
    }
  }, 1500);
}

function _showGlobalProgress(show, message = '', pct = 0) {
  const div = document.getElementById('mdGlobalProgress');
  const bar = document.getElementById('mdGlobalBar');
  const msg = document.getElementById('mdGlobalMsg');
  const pctEl = document.getElementById('mdGlobalPct');
  if (!div) return;
  div.style.display = show ? 'block' : 'none';
  if (bar) bar.style.width = `${pct}%`;
  if (msg) msg.textContent = message;
  if (pctEl) pctEl.textContent = `${pct}%`;
}

// ── Jobs history ──────────────────────────────────────────────────────────────

export async function mdLoadJobs() {
  const tbody = document.getElementById('mdJobsBody');
  if (!tbody) return;

  try {
    const res = await fetch(`${MD_API}/jobs?limit=30`);
    const jobs = await res.json();

    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-secondary); padding:20px;">Chưa có job nào</td></tr>';
      return;
    }

    tbody.innerHTML = jobs.map(j => {
      const canRetry = j.failed_chunks > 0 && j.status !== 'running';
      return `
        <tr>
          <td>${j.id}</td>
          <td><code>${j.strategy_name}</code></td>
          <td>${j.symbol}</td>
          <td>${j.timeframe}</td>
          <td>${j.job_type === 'full_refresh' ? '🔁 Full' : '⬆ Incr'}</td>
          <td>${_statusBadge(j.status)}</td>
          <td>
            <div style="display:flex; align-items:center; gap:8px;">
              <div style="background:var(--border); border-radius:3px; height:6px; width:80px; overflow:hidden;">
                <div style="height:100%; background:var(--accent); width:${j.progress_pct}%;"></div>
              </div>
              <span style="font-size:12px; color:var(--text-secondary);">${j.progress_pct}%</span>
            </div>
          </td>
          <td>${_fmtNum(j.total_candles_inserted)}</td>
          <td style="font-size:12px; color:var(--text-secondary);">${j.created_at ? j.created_at.slice(0,16).replace('T',' ') : '—'}</td>
          <td>
            <div style="display:flex; gap:6px;">
              <button onclick="mdShowJobDetail(${j.id})"
                style="padding:3px 8px; font-size:12px; background:var(--bg-panel); color:var(--text-primary); border:1px solid var(--border); border-radius:4px; cursor:pointer;">
                🔍 Chi tiết
              </button>
              ${canRetry ? `
              <button onclick="mdRetryJob(${j.id})"
                style="padding:3px 8px; font-size:12px; background:#7a4a00; color:#fff; border:none; border-radius:4px; cursor:pointer;">
                🔄 Retry
              </button>` : ''}
            </div>
          </td>
        </tr>`;
    }).join('');

  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="color:#f6465d; padding:20px;">Lỗi: ${e.message}</td></tr>`;
  }
}

// ── Job detail ────────────────────────────────────────────────────────────────

export async function mdShowJobDetail(jobId) {
  const detailDiv = document.getElementById('mdJobDetail');
  const title     = document.getElementById('mdJobDetailTitle');
  const tbody     = document.getElementById('mdChunksBody');
  if (!detailDiv || !tbody) return;

  detailDiv.style.display = 'block';
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:20px;">Đang tải...</td></tr>';
  detailDiv.scrollIntoView({ behavior: 'smooth' });

  try {
    const res = await fetch(`${MD_API}/jobs/${jobId}`);
    const job = await res.json();

    if (title) title.textContent = `Chi tiết Job #${jobId} — ${job.strategy_name}/${job.symbol}/${job.timeframe} (${job.job_type})`;

    const chunks = job.chunks || [];
    if (!chunks.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:20px; color:var(--text-secondary);">Không có chunk nào</td></tr>';
      return;
    }

    tbody.innerHTML = chunks.map(c => {
      const startDate = c.start_ms ? new Date(c.start_ms).toISOString().slice(0,10) : '—';
      const endDate   = c.end_ms   ? new Date(c.end_ms).toISOString().slice(0,10)   : '—';
      return `
        <tr>
          <td>${c.chunk_index + 1}</td>
          <td>${startDate}</td>
          <td>${endDate}</td>
          <td>${_statusBadge(c.status)}</td>
          <td>${_fmtNum(c.candles_inserted)}</td>
          <td>${c.retry_count}</td>
          <td style="font-size:11px; color:#f6465d; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${c.error_message || ''}">${c.error_message ? c.error_message.slice(0,60) + '...' : '—'}</td>
        </tr>`;
    }).join('');

  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:#f6465d; padding:20px;">Lỗi: ${e.message}</td></tr>`;
  }
}

// ── Retry job ─────────────────────────────────────────────────────────────────

export async function mdRetryJob(jobId) {
  try {
    const res = await fetch(`${MD_API}/jobs/${jobId}/retry`, { method: 'POST' });
    const data = await res.json();
    const jobKey = data.job_key;

    // Hiển thị progress global
    _showGlobalProgress(true, `Đang retry job #${jobId}...`, 0);
    _pollGlobalJob(jobKey);

    // Reload jobs list sau 2s
    setTimeout(mdLoadJobs, 2000);
  } catch (e) {
    alert(`Lỗi retry: ${e.message}`);
  }
}

// ── Page init ─────────────────────────────────────────────────────────────────

export function loadMarketDataPage() {
  mdRefreshStatus();
  mdLoadJobs();
}
