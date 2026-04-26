import { loadDashboard } from './dashboard.js';
import { fetchBots, createBot, toggleBot, deleteBot } from './bots.js';
import { loadSettings, createAccount } from './accounts.js';
import { loadChart, populateSymbolsDatalist } from './chart.js';
import { renderSignalsManagement, addSignal, removeSignal, filterAvailableSignals, openStrategyDetail } from './strategies.js';
import { renderIndicatorsManagement, toggleIndicator } from './indicators.js';

// Expose handlers to window for HTML onclick attributes
window.createBot = createBot;
window.toggleBot = toggleBot;
window.deleteBot = deleteBot;
window.createAccount = createAccount;
window.loadChart = loadChart;

window.addSignal = addSignal;
window.removeSignal = removeSignal;
window.filterAvailableSignals = filterAvailableSignals;
window.openStrategyDetail = openStrategyDetail;

window.toggleIndicator = toggleIndicator;

// Global Navigation
window.showPage = function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + pageId).classList.add('active');
  
  if(window.event && window.event.currentTarget && window.event.currentTarget.classList) {
    window.event.currentTarget.classList.add('active');
  } else {
    document.querySelectorAll('.nav-item').forEach(n => {
      if(n.innerText.toLowerCase().includes(pageId.replace('mybots', 'bot').replace('dashboard', 'tổng quan'))) {
        n.classList.add('active');
      }
    });
  }
  
  if(pageId === 'dashboard') loadDashboard();
  if(pageId === 'mybots') fetchBots();
  if(pageId === 'settings') loadSettings();
  if(pageId === 'strategies') renderSignalsManagement();
  if(pageId === 'indicators') renderIndicatorsManagement();
}

// Init Application
window.onload = () => {
  populateSymbolsDatalist();
  loadChart();
  loadDashboard();
};
