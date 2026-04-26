import { showToast } from './ui.js';
import { fetchAccountsForSetup } from './accounts.js';

const AVAILABLE_SIGNALS = [
  { id: 'ma_macd', name: 'MA + MACD Trend Following', desc: 'Bắt xu hướng mạnh mẽ bằng cách kết hợp Đường trung bình động và MACD Momentum.', pros: ['Ít nhiễu, tỷ lệ chính xác cao khi có trend', 'Dễ dàng cấu hình và hiểu nguyên lý', 'Tích hợp sẵn quản lý rủi ro (Take Profit / Stop Loss)'], defaultParams: `{\n  "timeframe": "15m",\n  "max_open_positions": 5,\n  "leverage": 5,\n  "fast_ma": 10,\n  "slow_ma": 30\n}` },
  { id: 'rsi_reversal', name: 'RSI Reversal (Quá mua/Quá bán)', desc: 'Bắt đỉnh/đáy ngắn hạn dựa trên chỉ báo RSI. Phù hợp cho thị trường đi ngang (Sideway).', pros: ['Hiệu quả trong thị trường biên độ hẹp', 'Tín hiệu rõ ràng ở vùng 30/70'], defaultParams: `{\n  "timeframe": "5m",\n  "rsi_period": 14,\n  "overbought": 70,\n  "oversold": 30\n}` },
  { id: 'bollinger_breakout', name: 'Bollinger Bands Breakout', desc: 'Giao dịch khi nến phá vỡ dải băng Bollinger, đón lõng biến động mạnh.', pros: ['Bắt trọn sóng lớn khi phá vỡ', 'Độ tin cậy cao'], defaultParams: `{\n  "timeframe": "1h",\n  "bb_period": 20,\n  "bb_std": 2\n}` },
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
