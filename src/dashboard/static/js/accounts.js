import { api } from './api.js';
import { showToast } from './ui.js';

export async function loadSettings() {
  const accounts = await api.getAccounts();
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

export async function fetchAccountsForSetup() {
  const accounts = await api.getAccounts();
  const select = document.getElementById('setupAccount');
  if(accounts.length === 0) {
    select.innerHTML = `<option value="">-- Cần thêm Tài khoản ở tab Settings trước --</option>`;
    return;
  }
  select.innerHTML = accounts.map(acc => `<option value="${acc.id}">${acc.name} (${acc.mode})</option>`).join('');
}

export async function createAccount(e) {
  e.preventDefault();
  const data = {
    name: document.getElementById('accName').value,
    api_key: document.getElementById('accKey').value,
    api_secret: document.getElementById('accSecret').value,
    mode: document.getElementById('accMode').value
  };
  try {
    await api.createAccount(data);
    showToast('Thêm tài khoản thành công', 'success');
    e.target.reset();
    loadSettings();
  } catch (err) {
    showToast('Lỗi khi thêm tài khoản', 'error');
  }
}
