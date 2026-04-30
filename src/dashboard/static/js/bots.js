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
    window.showPage('mybots');
  } catch (err) {
    showToast('Lỗi tạo bot', 'error');
  }
}

export async function fetchBots() {
  const bots = await api.getBots();
  const grid = document.getElementById('botsGrid');
  
  if (bots.length === 0) {
    grid.innerHTML = '<div class="empty-state"><h3>Chưa có Bot nào đang chạy</h3><p style="margin-top:10px;">Vui lòng sang tab "Chiến lược giao dịch" để khởi tạo Bot đầu tiên!</p></div>';
    return;
  }
  
  grid.innerHTML = bots.map(bot => {
    const isRunning = bot.status === 'running';
    const statusClass = isRunning ? 'status-running' : 'status-stopped';
    const toggleBtn = isRunning 
        ? `<button class="btn btn-danger btn-sm" onclick="toggleBot(${bot.id}, 'stopped')">⏹ Dừng Bot</button>`
        : `<button class="btn btn-success btn-sm" onclick="toggleBot(${bot.id}, 'running')">▶ Chạy Bot</button>`;

    const symbolsStr = (bot.symbols || []).join(', ');

    // Job behavior settings — defaults true nếu undefined
    const allowEntry  = bot.allow_new_entry  !== false;
    const notifyEntry = bot.notify_entry     !== false;
    const allowExit   = bot.allow_exit_scan  !== false;
    const notifyExit  = bot.notify_exit      !== false;

    // Khi bot stopped, allow_new_entry luôn false và không cho toggle
    const entryDisabled = !isRunning ? 'disabled title="Bot đang dừng — không vào lệnh mới"' : '';

    function toggleHtml(label, value, field, disabled = '') {
      const checked = value ? 'checked' : '';
      const cls = value ? 'toggle-on' : 'toggle-off';
      return `
        <label class="bot-toggle ${cls}" ${disabled}>
          <input type="checkbox" ${checked} ${disabled}
            onchange="updateBotSetting(${bot.id}, '${field}', this.checked)"
            style="display:none">
          <span class="toggle-track"></span>
          <span class="toggle-label">${label}</span>
        </label>`;
    }

    return `
      <div class="card" id="bot-card-${bot.id}">
        <div class="card-header">
          <span class="bot-name">#${bot.id} ${bot.name}</span>
          <span class="bot-status ${statusClass}">${bot.status.toUpperCase()}</span>
        </div>
        <div class="stat-row"><span class="stat-label">Chiến thuật:</span><span>${bot.strategy_name}</span></div>
        <div class="stat-row"><span class="stat-label">Symbols:</span><span>${symbolsStr}</span></div>
        <div class="stat-row"><span class="stat-label">PnL:</span><span style="color: ${bot.total_pnl >= 0 ? '#0ecb81' : '#f6465d'}">${bot.total_pnl}</span></div>
        <div class="stat-row"><span class="stat-label">Win Rate:</span><span>${bot.win_rate}%</span></div>

        <!-- Job behavior settings -->
        <div style="margin-top: 12px; padding: 10px; background: rgba(0,0,0,0.15); border-radius: 6px; border: 1px solid var(--border);">
          <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">⚙️ Cài đặt Job</div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
            ${toggleHtml('Vào lệnh mới', allowEntry, 'allow_new_entry', entryDisabled)}
            ${toggleHtml('Noti entry', notifyEntry, 'notify_entry')}
            ${toggleHtml('Quét đóng lệnh', allowExit, 'allow_exit_scan')}
            ${toggleHtml('Noti đóng lệnh', notifyExit, 'notify_exit')}
          </div>
        </div>

        <div style="margin-top: 15px; display: flex; gap: 10px;">
          ${toggleBtn}
          <button class="btn btn-sm" style="background: var(--border); color: #fff;" onclick="deleteBot(${bot.id})">🗑 Xóa</button>
        </div>
      </div>
    `;
  }).join('');
}

export async function toggleBot(id, status) {
  try {
    await api.updateBotStatus(id, status);
    showToast(`Bot ${status === 'running' ? 'đã khởi động' : 'đã dừng'}`, 'success');
    fetchBots();
  } catch (err) {
    showToast('Lỗi cập nhật trạng thái bot', 'error');
  }
}

export async function updateBotSetting(botId, field, value) {
  try {
    await api.updateBotSettings(botId, { [field]: value });
    showToast(`Đã cập nhật: ${_settingLabel(field)} = ${value ? 'Bật' : 'Tắt'}`, 'success');
    // Không reload toàn bộ grid — chỉ update visual state của toggle
    const card = document.getElementById(`bot-card-${botId}`);
    if (card) {
      const label = card.querySelector(`input[onchange*="'${field}'"]`)?.closest('.bot-toggle');
      if (label) {
        label.classList.toggle('toggle-on', value);
        label.classList.toggle('toggle-off', !value);
      }
    }
  } catch (err) {
    showToast('Lỗi cập nhật cài đặt', 'error');
    // Revert checkbox
    fetchBots();
  }
}

function _settingLabel(field) {
  const map = {
    allow_new_entry: 'Vào lệnh mới',
    notify_entry: 'Noti entry',
    allow_exit_scan: 'Quét đóng lệnh',
    notify_exit: 'Noti đóng lệnh',
  };
  return map[field] || field;
}

export async function deleteBot(id) {
  if(!confirm('Bạn có chắc muốn xóa bot này? Lịch sử PnL vẫn được giữ lại.')) return;
  await api.deleteBot(id);
  fetchBots();
}
