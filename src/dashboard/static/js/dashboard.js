import { api } from './api.js';

export async function loadDashboard() {
  const bots = await api.getBots();
  let totalPnl = 0;
  let activeBots = 0;
  bots.forEach(b => {
    totalPnl += b.total_pnl;
    if(b.status === 'running') activeBots++;
  });
  
  document.getElementById('statTotalPnl').innerText = `$${totalPnl.toFixed(4)}`;
  document.getElementById('statTotalPnl').style.color = totalPnl >= 0 ? '#0ecb81' : '#f6465d';
  document.getElementById('statActiveBots').innerText = activeBots;

  const trades = await api.getTrades(10);
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

  const events = await api.getEvents(20);
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
