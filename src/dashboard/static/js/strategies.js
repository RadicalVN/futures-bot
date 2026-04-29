import { showToast } from './ui.js';
import { fetchAccountsForSetup } from './accounts.js';

const AVAILABLE_SIGNALS = [
  { id: 'ma_macd', name: 'MA + MACD Trend Following', desc: 'Bắt xu hướng mạnh mẽ bằng cách kết hợp Đường trung bình động và MACD Momentum.', pros: ['Ít nhiễu, tỷ lệ chính xác cao khi có trend', 'Dễ dàng cấu hình và hiểu nguyên lý', 'Tích hợp sẵn quản lý rủi ro (Take Profit / Stop Loss)'], defaultParams: `{\n  "timeframe": "15m",\n  "max_open_positions": 10,\n  "leverage": 5,\n  "fast_ma": 10,\n  "slow_ma": 30\n}` },
  { id: 'sma_trend_early_exit', name: 'TVT-EarlyExit (Thuận xu hướng + Thoát sớm)', desc: 'Vào lệnh khi Trend đảo chiều + Momentum mạnh. Thoát sớm khi Momentum suy yếu.', pros: ['Bắt đúng điểm đảo chiều', 'Thoát lệnh nhanh, bảo vệ lợi nhuận'], defaultParams: `{\n  "timeframe": "5m",\n  "lookback_candles": 500,\n  "max_open_positions": 10,\n  "leverage": 5,\n  "position_size_pct": 0.10,\n  "stop_loss_pct": 0.02,\n  "take_profit_pct": 0.04,\n  "margin_mode": "isolated",\n  "fast_len": 1,\n  "slow_len": 5,\n  "len_c": 200,\n  "factor": 0.05,\n  "bb_length": 50,\n  "min_slope_pct": 0.002\n}` },
  { id: 'sma_pullback', name: 'TVT-Pullback (Bắt đáy sóng hồi)', desc: 'Chờ giá hồi lại rồi bắt khi Momentum bật mạnh trở lại. Mua giá rẻ hơn đầu sóng.', pros: ['Giá vào tốt hơn', 'Rủi ro thấp hơn so với đánh thuận'], defaultParams: `{\n  "timeframe": "5m",\n  "lookback_candles": 500,\n  "max_open_positions": 10,\n  "leverage": 5,\n  "position_size_pct": 0.10,\n  "stop_loss_pct": 0.02,\n  "take_profit_pct": 0.04,\n  "margin_mode": "isolated",\n  "fast_len": 1,\n  "slow_len": 5,\n  "len_c": 200,\n  "factor": 0.05,\n  "bb_length": 50,\n  "pullback_confirm_bars": 2,\n  "min_slope_pct": 0.002\n}` },
  { id: 'sma_anti_sideway', name: 'TVT-AntiSideway (Chống nhiễu Sideway)', desc: 'Lọc bỏ thị trường đi ngang bằng Slope. Chỉ vào lệnh khi thị trường đang chạy thật sự.', pros: ['Tránh bẫy sideway', 'Tín hiệu chất lượng cao hơn'], defaultParams: `{\n  "timeframe": "5m",\n  "lookback_candles": 500,\n  "max_open_positions": 10,\n  "leverage": 5,\n  "position_size_pct": 0.10,\n  "stop_loss_pct": 0.02,\n  "take_profit_pct": 0.04,\n  "margin_mode": "isolated",\n  "fast_len": 1,\n  "slow_len": 5,\n  "len_c": 200,\n  "factor": 0.05,\n  "bb_length": 50,\n  "sideway_slope_threshold": 0.005,\n  "min_momentum_pct": 0.001\n}` },
  { id: 'sma_macd_cross', name: 'TVT-SMA+MACD Cross (Giao cắt kép)', desc: 'Kết hợp Custom SMA và Custom MACD. Vào lệnh khi cả 3 điều kiện thỏa: Signal đảo chiều + MACD cross + Giá cắt MA.', pros: ['Tín hiệu xác nhận 3 lớp, ít false signal', 'Giá vào tiệm cận MA — rủi ro thấp', 'Exit thông minh theo nhiều điều kiện'], defaultParams: `{\n  "timeframe": "5m",\n  "lookback_candles": 600,\n  "max_open_positions": 10,\n  "leverage": 5,\n  "position_size_pct": 0.10,\n  "stop_loss_pct": 0.02,\n  "take_profit_pct": 0.04,\n  "margin_mode": "isolated",\n  "fast_len": 1,\n  "slow_len": 5,\n  "len_c": 200,\n  "factor": 0.05,\n  "bb_length": 50,\n  "macd_fast": 12,\n  "macd_slow": 26,\n  "macd_signal_length": 500\n}` },
];

const CUSTOM_SIGNAL = { id: 'custom_signal', name: 'Custom Signal (Webhook)', desc: 'Nhận tín hiệu mua bán từ TradingView hoặc hệ thống bên ngoài qua Webhook URL.', pros: ['Tự do kết hợp với mọi chỉ báo phức tạp trên TradingView', 'Tốc độ thực thi cực nhanh, độ trễ thấp'], defaultParams: `{\n  "leverage": 10,\n  "max_open_positions": 3,\n  "margin_mode": "isolated"\n}` };

let activeSignalsIds = JSON.parse(localStorage.getItem('activeSignals')) || ['custom_signal'];

function saveActiveSignals() {
  localStorage.setItem('activeSignals', JSON.stringify(activeSignalsIds));
}

export function renderSignalsManagement() {
  const activeGrid = document.getElementById('activeSignalsGrid');
  const availableGrid = document.getElementById('availableSignalsGrid');
  const searchStr = (document.getElementById('searchSignal')?.value || '').toLowerCase();

  let activeHtml = '';
  activeHtml += buildSignalCard(CUSTOM_SIGNAL, true, false);
  
  AVAILABLE_SIGNALS.forEach(sig => {
    if (activeSignalsIds.includes(sig.id)) {
      activeHtml += buildSignalCard(sig, true, true);
    }
  });
  activeGrid.innerHTML = activeHtml;

  let availHtml = '';
  AVAILABLE_SIGNALS.forEach(sig => {
    if (!activeSignalsIds.includes(sig.id) && (sig.name.toLowerCase().includes(searchStr) || sig.id.toLowerCase().includes(searchStr))) {
      availHtml += buildSignalCard(sig, false, false);
    }
  });
  
  if(availHtml === '') availHtml = '<div class="empty-state">Không tìm thấy chiến lược nào hoặc bạn đã thêm tất cả.</div>';
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

export function addSignal(id) {
  if (!activeSignalsIds.includes(id)) {
    activeSignalsIds.push(id);
    saveActiveSignals();
    renderSignalsManagement();
    showToast('Đã thêm chiến lược vào danh sách yêu thích', 'success');
  }
}

export function removeSignal(id) {
  activeSignalsIds = activeSignalsIds.filter(x => x !== id);
  saveActiveSignals();
  renderSignalsManagement();
}

export function filterAvailableSignals() {
  renderSignalsManagement();
}

export function openStrategyDetail(stratId) {
  let strat = AVAILABLE_SIGNALS.find(s => s.id === stratId);
  if(!strat && stratId === 'custom_signal') strat = CUSTOM_SIGNAL;
  if(!strat) return;
  
  document.getElementById('detailTitle').innerText = strat.name;
  document.getElementById('detailDesc').innerText = strat.desc;
  document.getElementById('detailPros').innerHTML = strat.pros.map(p => `<li>${p}</li>`).join('');
  document.getElementById('setupStrategy').value = stratId;
  document.getElementById('setupParams').value = strat.defaultParams;
  
  fetchAccountsForSetup();
  window.showPage('strategy-detail');
}
