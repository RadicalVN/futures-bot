import { showToast } from './ui.js';
import { loadChart } from './chart.js';

const AVAILABLE_INDICATORS = [
  { id: 'custom_sma', name: 'Custom SMA (ittuantruong)', desc: 'Hệ thống dải băng (up/dn) và hệ số an toàn (factor)' },
  { id: 'custom_macd', name: 'Custom MACD (TuanTV1008)', desc: 'Cực nhạy, sử dụng Signal Length dài hạn' }
];

let activeIndicatorsIds = JSON.parse(localStorage.getItem('activeIndicators')) || ['custom_sma', 'custom_macd'];

function saveActiveIndicators() {
  localStorage.setItem('activeIndicators', JSON.stringify(activeIndicatorsIds));
}

export function toggleIndicator(id) {
  if (activeIndicatorsIds.includes(id)) {
    activeIndicatorsIds = activeIndicatorsIds.filter(x => x !== id);
  } else {
    activeIndicatorsIds.push(id);
  }
  saveActiveIndicators();
  renderIndicatorsManagement();
  
  if(document.getElementById('page-dashboard').classList.contains('active')) {
    loadChart();
  } else {
    showToast('Đã cập nhật biểu đồ', 'success');
  }
}

export function renderIndicatorsManagement() {
  const list = document.getElementById('indicatorsList');
  if(!list) return;
  
  let html = '';
  AVAILABLE_INDICATORS.forEach(ind => {
    const isActive = activeIndicatorsIds.includes(ind.id);
    html += `
      <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: start;">
          <div>
            <h3 style="color: ${isActive ? 'var(--accent)' : 'var(--text-primary)'}; margin-bottom: 8px;">${ind.name}</h3>
            <p style="color: var(--text-secondary); font-size: 13px;">${ind.desc}</p>
          </div>
          <label class="switch" style="position: relative; display: inline-block; width: 40px; height: 20px;">
            <input type="checkbox" ${isActive ? 'checked' : ''} onchange="toggleIndicator('${ind.id}')" style="opacity: 0; width: 0; height: 0;">
            <span style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: ${isActive ? '#0ecb81' : '#333'}; border-radius: 20px; transition: .4s;">
              <span style="position: absolute; height: 16px; width: 16px; left: ${isActive ? '22px' : '2px'}; bottom: 2px; background-color: white; border-radius: 50%; transition: .4s;"></span>
            </span>
          </label>
        </div>
      </div>
    `;
  });
  list.innerHTML = html;
}
