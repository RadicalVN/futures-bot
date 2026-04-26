// Navigation
function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + pageId).classList.add('active');
  
  if(event && event.currentTarget && event.currentTarget.classList) {
    event.currentTarget.classList.add('active');
  } else {
    // Fallback if triggered via JS instead of click
    document.querySelectorAll('.nav-item').forEach(n => {
      if(n.innerText.toLowerCase().includes(pageId.replace('mybots', 'bot').replace('dashboard', 'tổng quan'))) {
        n.classList.add('active');
      }
    });
  }
  
  if(pageId === 'dashboard') loadDashboard();
  if(pageId === 'mybots') fetchBots();
  if(pageId === 'settings') loadSettings();
  if(pageId === 'market') renderSignalsManagement();
}

// Toast Notification
function showToast(message, type='info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ================= SIGNAL MANAGEMENT =================
const AVAILABLE_SIGNALS = [
  { id: 'custom_sma', name: 'Custom SMA (ittuantruong)', desc: 'Chỉ báo Custom SMA bắt xu hướng bằng hệ thống dải băng (up/dn) và hệ số an toàn (factor). Tín hiệu Mua/Bán cực kỳ sát với biến động.', pros: ['Chống nhiễu tốt trong sideway', 'Bám sát đỉnh/đáy', 'Code độc quyền từ Pine Script'], defaultParams: `{\n  "timeframe": "15m",\n  "max_open_positions": 5,\n  "leverage": 5,\n  "fast_length": 1,\n  "slow_length": 5,\n  "len_c": 20,\n  "factor": 0.05\n}` },
  { id: 'custom_macd', name: 'Custom MACD (TuanTV1008)', desc: 'Chỉ báo Custom MACD cực nhạy. Sử dụng Signal Length dài hạn để xác nhận độ lớn của Trend.', pros: ['Kết hợp tùy chọn SMA/EMA linh hoạt', 'Tín hiệu giao cắt cực kỳ chuẩn xác', 'Không bị lừa bởi tín hiệu giả'], defaultParams: `{\n  "timeframe": "15m",\n  "max_open_positions": 5,\n  "leverage": 5,\n  "fast_length": 12,\n  "slow_length": 26,\n  "signal_length": 500,\n  "sma_source": "EMA",\n  "sma_signal": "EMA"\n}` },
  { id: 'ma_macd', name: 'MA + MACD Trend Following', desc: 'Bắt xu hướng mạnh mẽ bằng cách kết hợp Đường trung bình động và MACD Momentum.', pros: ['Ít nhiễu, tỷ lệ chính xác cao khi có trend', 'Dễ dàng cấu hình và hiểu nguyên lý', 'Tích hợp sẵn quản lý rủi ro (Take Profit / Stop Loss)'], defaultParams: `{\n  "timeframe": "15m",\n  "max_open_positions": 5,\n  "leverage": 5,\n  "fast_ma": 10,\n  "slow_ma": 30\n}` },
  { id: 'rsi_reversal', name: 'RSI Reversal (Quá mua/Quá bán)', desc: 'Bắt đỉnh/đáy ngắn hạn dựa trên chỉ báo RSI. Phù hợp cho thị trường đi ngang (Sideway).', pros: ['Hiệu quả trong thị trường biên độ hẹp', 'Tín hiệu rõ ràng ở vùng 30/70'], defaultParams: `{\n  "timeframe": "5m",\n  "rsi_period": 14,\n  "overbought": 70,\n  "oversold": 30\n}` },
  { id: 'bollinger_breakout', name: 'Bollinger Bands Breakout', desc: 'Giao dịch khi nến phá vỡ dải băng Bollinger, đón lõng biến động mạnh.', pros: ['Bắt trọn sóng lớn khi phá vỡ', 'Độ tin cậy cao'], defaultParams: `{\n  "timeframe": "1h",\n  "bb_period": 20,\n  "bb_std": 2\n}` },
];

const CUSTOM_SIGNAL = { id: 'custom_signal', name: 'Custom Signal (Webhook)', desc: 'Nhận tín hiệu mua bán từ TradingView hoặc hệ thống bên ngoài qua Webhook URL.', pros: ['Tự do kết hợp với mọi chỉ báo phức tạp trên TradingView', 'Tốc độ thực thi cực nhanh, độ trễ thấp'], defaultParams: `{\n  "leverage": 10,\n  "max_open_positions": 3,\n  "margin_mode": "isolated"\n}` };

let activeSignalsIds = JSON.parse(localStorage.getItem('activeSignals')) || ['custom_signal'];

function saveActiveSignals() {
  localStorage.setItem('activeSignals', JSON.stringify(activeSignalsIds));
}

function renderSignalsManagement() {
  const activeGrid = document.getElementById('activeSignalsGrid');
  const availableGrid = document.getElementById('availableSignalsGrid');
  const searchStr = (document.getElementById('searchSignal')?.value || '').toLowerCase();

  // 1. Render Active Signals
  let activeHtml = '';
  // Mặc định luôn có Custom Signal
  activeHtml += buildSignalCard(CUSTOM_SIGNAL, true, false);
  
  // Các signal hệ thống đã add
  AVAILABLE_SIGNALS.forEach(sig => {
    if (activeSignalsIds.includes(sig.id)) {
      activeHtml += buildSignalCard(sig, true, true);
    }
  });
  activeGrid.innerHTML = activeHtml;

  // 2. Render Available Signals (Filtered)
  let availHtml = '';
  AVAILABLE_SIGNALS.forEach(sig => {
    if (!activeSignalsIds.includes(sig.id) && (sig.name.toLowerCase().includes(searchStr) || sig.id.toLowerCase().includes(searchStr))) {
      availHtml += buildSignalCard(sig, false, false);
    }
  });
  
  if(availHtml === '') availHtml = '<div class="empty-state">Không tìm thấy chỉ báo nào hoặc bạn đã thêm tất cả.</div>';
  availableGrid.innerHTML = availHtml;
}

function buildSignalCard(sig, isActive, canRemove) {
  const btn = isActive 
    ? `<div style="display: flex; gap: 10px; margin-top: 15px;">
         <button class="btn btn-primary" style="flex:1;" onclick="openStrategyDetail('${sig.id}')">⚙️ Cấu hình Bot</button>
         ${canRemove ? `<button class="btn btn-danger" onclick="removeSignal('${sig.id}')">Xóa</button>` : ''}
       </div>`
    : `<button class="btn btn-success" style="width: 100%; margin-top: 15px;" onclick="addSignal('${sig.id}')">➕ Thêm vào danh sách</button>`;

  return `
    <div class="card">
      <h3 style="color: ${isActive ? 'var(--accent)' : 'var(--text-primary)'};">${sig.name}</h3>
      <p style="color: var(--text-secondary); margin: 10px 0; font-size: 14px;">${sig.desc}</p>
      ${btn}
    </div>
  `;
}

function addSignal(id) {
  if (!activeSignalsIds.includes(id)) {
    activeSignalsIds.push(id);
    saveActiveSignals();
    renderSignalsManagement();
    showToast('Đã thêm chỉ báo vào danh sách kích hoạt', 'success');
  }
}

function removeSignal(id) {
  activeSignalsIds = activeSignalsIds.filter(x => x !== id);
  saveActiveSignals();
  renderSignalsManagement();
}

function filterAvailableSignals() {
  renderSignalsManagement();
}

// ================= STRATEGY DETAIL =================
function openStrategyDetail(stratId) {
  let strat = AVAILABLE_SIGNALS.find(s => s.id === stratId);
  if(!strat && stratId === 'custom_signal') strat = CUSTOM_SIGNAL;
  if(!strat) return;
  
  document.getElementById('detailTitle').innerText = strat.name;
  document.getElementById('detailDesc').innerText = strat.desc;
  document.getElementById('detailPros').innerHTML = strat.pros.map(p => `<li>${p}</li>`).join('');
  document.getElementById('setupStrategy').value = stratId;
  document.getElementById('setupParams').value = strat.defaultParams;
  
  fetchAccountsForSetup();
  showPage('strategy-detail');
}

// ================= API CALLS =================
async function loadSettings() {
  const res = await fetch('/api/accounts');
  const accounts = await res.json();
  const list = document.getElementById('accountsList');
  
  if(accounts.length === 0) {
    list.innerHTML = `<tr><td colspan="3" class="empty-state">Chưa có tài khoản API nào được thêm.</td></tr>`;
    return;
  }
  
  list.innerHTML = accounts.map(acc => `
    <tr>
      <td>${acc.name}</td>
      <td><span class="bot-status ${acc.mode === 'mainnet' ? 'status-stopped' : 'status-running'}">${acc.mode.toUpperCase()}</span></td>
      <td style="color: #0ecb81;">Hoạt động</td>
    </tr>
  `).join('');
}

async function fetchAccountsForSetup() {
  const res = await fetch('/api/accounts');
  const accounts = await res.json();
  const select = document.getElementById('setupAccount');
  
  if(accounts.length === 0) {
    select.innerHTML = `<option value="">-- Cần thêm Tài khoản ở tab Settings trước --</option>`;
    return;
  }
  
  select.innerHTML = accounts.map(acc => `<option value="${acc.id}">${acc.name} (${acc.mode})</option>`).join('');
}

async function createAccount(e) {
  e.preventDefault();
  const data = {
    name: document.getElementById('accName').value,
    api_key: document.getElementById('accKey').value,
    api_secret: document.getElementById('accSecret').value,
    mode: document.getElementById('accMode').value
  };
  const res = await fetch('/api/accounts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if(res.ok) {
    showToast('Thêm tài khoản thành công', 'success');
    e.target.reset();
    loadSettings();
  }
}

async function createBot(e) {
  e.preventDefault();
  
  const accountId = document.getElementById('setupAccount').value;
  if(!accountId) return showToast('Vui lòng chọn hoặc tạo Tài khoản API trước', 'error');

  let params = {};
  try {
    params = JSON.parse(document.getElementById('setupParams').value);
  } catch(err) {
    return showToast('Lỗi JSON trong ô Tham số', 'error');
  }

  const symbolsInput = document.getElementById('setupSymbols').value;
  const symbols = symbolsInput.split(',').map(s => s.trim()).filter(s => s);

  const data = {
    name: document.getElementById('setupName').value,
    account_id: accountId,
    strategy_name: document.getElementById('setupStrategy').value,
    symbols: symbols,
    parameters: params
  };

  const res = await fetch('/api/bots', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if(res.ok) {
    showToast('Tạo Bot thành công!', 'success');
    showPage('mybots');
  }
}

async function fetchBots() {
  const res = await fetch('/api/bots');
  const bots = await res.json();
  const grid = document.getElementById('botsGrid');
  
  if (bots.length === 0) {
    grid.innerHTML = '<div class="empty-state"><h3>Chưa có Bot nào đang chạy</h3><p style="margin-top:10px;">Vui lòng sang tab "Chợ Chiến Thuật" để khởi tạo Bot đầu tiên của bạn!</p></div>';
    return;
  }
  
  grid.innerHTML = bots.map(bot => {
    const isRunning = bot.status === 'running';
    const statusClass = isRunning ? 'status-running' : 'status-stopped';
    const toggleBtn = isRunning 
        ? `<button class="btn btn-danger btn-sm" onclick="toggleBot(${bot.id}, 'stopped')">⏹ Dừng Bot</button>`
        : `<button class="btn btn-success btn-sm" onclick="toggleBot(${bot.id}, 'running')">▶ Chạy Bot</button>`;

    const symbolsStr = (bot.symbols || []).join(', ');

    return `
      <div class="card">
        <div class="card-header">
          <span class="bot-name">${bot.name}</span>
          <span class="bot-status ${statusClass}">${bot.status.toUpperCase()}</span>
        </div>
        <div class="stat-row"><span class="stat-label">Chiến thuật:</span><span>${bot.strategy_name}</span></div>
        <div class="stat-row"><span class="stat-label">Symbols:</span><span>${symbolsStr}</span></div>
        <div class="stat-row"><span class="stat-label">Lợi nhuận (PnL):</span><span style="color: ${bot.total_pnl >= 0 ? '#0ecb81' : '#f6465d'}">$${bot.total_pnl}</span></div>
        <div class="stat-row"><span class="stat-label">Tỷ lệ thắng:</span><span>${bot.win_rate}%</span></div>
        <div style="margin-top: 15px; display: flex; gap: 10px;">
          ${toggleBtn}
          <button class="btn btn-sm" style="background: var(--border); color: #fff;" onclick="deleteBot(${bot.id})">🗑 Xóa</button>
        </div>
      </div>
    `;
  }).join('');
}

async function toggleBot(id, status) {
  const res = await fetch(`/api/bots/${id}/status`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status})
  });
  if(res.ok) fetchBots();
}

async function deleteBot(id) {
  if(!confirm('Bạn có chắc muốn xóa bot này? Lịch sử PnL vẫn được giữ lại.')) return;
  const res = await fetch(`/api/bots/${id}`, { method: 'DELETE' });
  if(res.ok) fetchBots();
}

async function loadSignals() {
  const res = await fetch('/api/signals?limit=50');
  const signals = await res.json();
  const list = document.getElementById('signalsList');
  
  if(signals.length === 0) {
    list.innerHTML = `<tr><td colspan="5" class="empty-state">Chưa có tín hiệu giao dịch nào được ghi nhận.</td></tr>`;
    return;
  }
  
  list.innerHTML = signals.map(s => `
    <tr>
      <td>${new Date(s.timestamp).toLocaleString('vi-VN')}</td>
      <td>Bot #${s.bot_id}</td>
      <td style="font-weight:bold;">${s.symbol}</td>
      <td style="color:${s.signal_type === 'long' ? '#0ecb81' : (s.signal_type === 'short' ? '#f6465d' : '#8892a4')}">${s.signal_type.toUpperCase()}</td>
      <td>
        <span class="bot-status ${s.executed ? 'status-running' : 'status-stopped'}">${s.executed ? 'Đã chạy lệnh' : 'Bỏ qua'}</span>
      </td>
    </tr>
  `).join('');
}

// ================= DASHBOARD =================
async function loadDashboard() {
  // Load Stats
  const resBots = await fetch('/api/bots');
  const bots = await resBots.json();
  let totalPnl = 0;
  let activeBots = 0;
  bots.forEach(b => {
    totalPnl += b.total_pnl;
    if(b.status === 'running') activeBots++;
  });
  
  document.getElementById('statTotalPnl').innerText = `$${totalPnl.toFixed(4)}`;
  document.getElementById('statTotalPnl').style.color = totalPnl >= 0 ? '#0ecb81' : '#f6465d';
  document.getElementById('statActiveBots').innerText = activeBots;

  // Load Trades
  const resTrades = await fetch('/api/trades?limit=10');
  const trades = await resTrades.json();
  const tradesList = document.getElementById('tradesList');
  if(trades.length === 0) {
    tradesList.innerHTML = `<tr><td colspan="5" class="empty-state">Chưa có giao dịch nào</td></tr>`;
  } else {
    tradesList.innerHTML = trades.map(t => `
      <tr>
        <td>${new Date(t.created_at).toLocaleString('vi-VN')}</td>
        <td style="font-weight:bold;">${t.symbol}</td>
        <td style="color:${t.side === 'buy' ? '#0ecb81' : '#f6465d'}">${t.side.toUpperCase()}</td>
        <td>${t.price}</td>
        <td style="color:${t.realized_pnl >= 0 ? '#0ecb81' : '#f6465d'}">$${t.realized_pnl}</td>
      </tr>
    `).join('');
  }

  // Load Logs
  const resEvents = await fetch('/api/events?limit=20');
  const events = await resEvents.json();
  const eventsList = document.getElementById('eventsList');
  if(events.length === 0) {
    eventsList.innerHTML = `<div class="empty-state">Chưa có nhật ký hoạt động</div>`;
  } else {
    eventsList.innerHTML = events.map(e => `
      <div class="log-item">
        <span class="log-time">[${new Date(e.timestamp).toLocaleTimeString('vi-VN')}]</span>
        <span class="log-${e.level}">${e.message}</span>
      </div>
    `).join('');
  }
}

// Chart Logic
let chartInstance = null;

async function loadChart() {
    const symbol = document.getElementById('chartSymbol').value;
    document.getElementById('chartTitle').innerText = `Đang tải ${symbol}...`;
    
    try {
        const res = await fetch(`/api/chart-data/${symbol.replace("/", "-")}`);
        if(!res.ok) throw new Error("API lỗi");
        const json = await res.json();
        
        document.getElementById('chartTitle').innerText = `Biểu đồ Nến - ${symbol}`;
        renderChart(json.data);
    } catch(err) {
        document.getElementById('chartTitle').innerText = `Lỗi tải biểu đồ ${symbol}`;
        console.error(err);
    }
}

function renderChart(data) {
    const ctx = document.getElementById('tradingChart').getContext('2d');
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    // Prepare indicator data
    const smaUpData = data.map(d => ({x: d.x, y: d.sma_up === 0 ? null : d.sma_up}));
    const smaDnData = data.map(d => ({x: d.x, y: d.sma_dn === 0 ? null : d.sma_dn}));
    const macdData = data.map(d => ({x: d.x, y: d.macd}));
    const macdSignalData = data.map(d => ({x: d.x, y: d.macd_signal}));

    chartInstance = new Chart(ctx, {
        type: 'candlestick',
        data: {
            datasets: [
                {
                    label: 'Giá',
                    data: data,
                    color: { up: '#0ecb81', down: '#f6465d', unchanged: '#8892a4' },
                    yAxisID: 'y'
                },
                {
                    type: 'line',
                    label: 'SMA Up',
                    data: smaUpData,
                    borderColor: '#2196F3', // blue
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: 'y'
                },
                {
                    type: 'line',
                    label: 'SMA Down',
                    data: smaDnData,
                    borderColor: '#FFEB3B', // yellow
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: 'y'
                },
                {
                    type: 'line',
                    label: 'MACD',
                    data: macdData,
                    borderColor: '#2962FF',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: 'y_macd'
                },
                {
                    type: 'line',
                    label: 'MACD Signal',
                    data: macdSignalData,
                    borderColor: '#FF6D00',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: 'y_macd'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: { tooltipFormat: 'yyyy-MM-dd HH:mm' },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#8892a4' }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#8892a4' }
                },
                y_macd: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { display: false },
                    ticks: { color: '#8892a4' },
                    // Giới hạn MACD ở khu vực dưới biểu đồ (tùy chọn)
                    // Nếu muốn MACD và nến không bị đè lên nhau quá nhiều
                }
            },
            plugins: {
                legend: { display: true, labels: { color: '#8892a4' } },
                zoom: {
                    pan: {
                        enabled: true,
                        mode: 'x'
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: 'x'
                    }
                }
            }
        }
    });
}

// Populate Symbols Datalist
async function populateSymbolsDatalist() {
  try {
    const res = await fetch('/api/symbols');
    if (!res.ok) throw new Error('API lỗi');
    const data = await res.json();
    const symbols = data.symbols || [];
    const datalist = document.getElementById('binanceSymbols');
    if(datalist) {
      datalist.innerHTML = symbols.map(s => `<option value="${s}">`).join('');
    }
  } catch (err) {
    console.error("Lỗi lấy danh sách symbol:", err);
  }
}

// Init
window.onload = () => {
  populateSymbolsDatalist();
  loadChart();
  loadDashboard();
};
