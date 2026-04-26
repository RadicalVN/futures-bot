import { api } from './api.js';
import { showToast } from './ui.js';

export async function createBot(e) {
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

  try {
    await api.createBot(data);
    showToast('Tạo Bot thành công!', 'success');
    window.showPage('mybots'); // Phụ thuộc vào main.js đã expose
  } catch (err) {
    showToast('Lỗi tạo bot', 'error');
  }
}

export async function fetchBots() {
  const bots = await api.getBots();
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

export async function toggleBot(id, status) {
  await api.updateBotStatus(id, status);
  fetchBots();
}

export async function deleteBot(id) {
  if(!confirm('Bạn có chắc muốn xóa bot này? Lịch sử PnL vẫn được giữ lại.')) return;
  await api.deleteBot(id);
  fetchBots();
}
