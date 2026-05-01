import { loadDashboard } from './dashboard.js';
import { fetchBots, createBot, toggleBot, deleteBot, updateBotSetting } from './bots.js';
import { loadSettings, createAccount } from './accounts.js';
import { loadChart, populateSymbolsDatalist, globalReset, globalRefresh, onLeftTimeframeChange, onRightTimeframeChange, onSymbolChange, toggleLegendMenu, toggleDataset, scrollToLatest } from './chart.js';
import { renderSignalsManagement, addSignal, removeSignal, filterAvailableSignals, openStrategyDetail } from './strategies.js';
import { renderIndicatorsManagement, toggleIndicator } from './indicators.js';
import { loadTradesPage, applyTradeFilters, resetTradeFilters } from './trades.js';
import { loadBacktestPage, runBacktest, filterBtTrades, switchBtTab, onStrategyChange, runStrategyBacktest } from './backtest.js';

// Expose handlers to window for HTML onclick attributes
window.createBot = createBot;
window.toggleBot = toggleBot;
window.deleteBot = deleteBot;
window.updateBotSetting = updateBotSetting;
window.createAccount = createAccount;
window.loadChart = loadChart;
window.globalReset = globalReset;
window.globalRefresh = globalRefresh;
window.onLeftTimeframeChange = onLeftTimeframeChange;
window.onRightTimeframeChange = onRightTimeframeChange;
window.onSymbolChange = onSymbolChange;
window.toggleLegendMenu = toggleLegendMenu;
window.toggleDataset = toggleDataset;
window.scrollToLatest = scrollToLatest;

window.addSignal = addSignal;
window.removeSignal = removeSignal;
window.filterAvailableSignals = filterAvailableSignals;
window.openStrategyDetail = openStrategyDetail;

window.toggleIndicator = toggleIndicator;

window.applyTradeFilters = applyTradeFilters;
window.resetTradeFilters = resetTradeFilters;

window.runBacktest = runBacktest;
window.filterBtTrades = filterBtTrades;
window.switchBtTab = switchBtTab;
window.onStrategyChange = onStrategyChange;
window.runStrategyBacktest = runStrategyBacktest;

// Global Navigation
window.showPage = function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + pageId).classList.add('active');

  // Highlight nav item tương ứng
  if(window.event && window.event.currentTarget && window.event.currentTarget.classList) {
    window.event.currentTarget.classList.add('active');
  } else {
    document.querySelectorAll('.nav-item').forEach(n => {
      if(n.innerText.toLowerCase().includes(pageId.replace('mybots', 'bot').replace('dashboard', 'tổng quan').replace('trades', 'lệnh'))) {
        n.classList.add('active');
      }
    });
  }

  // Lưu tab hiện tại để restore khi reload
  localStorage.setItem('activePage', pageId);

  if(pageId === 'dashboard') loadDashboard();
  if(pageId === 'mybots') fetchBots();
  if(pageId === 'trades') loadTradesPage();
  if(pageId === 'settings') loadSettings();
  if(pageId === 'strategies') renderSignalsManagement();
  if(pageId === 'indicators') renderIndicatorsManagement();
  if(pageId === 'backtest') loadBacktestPage();
}

// Init Application
window.onload = () => {
  populateSymbolsDatalist();
  loadChart(1);
  loadChart(2);

  // Restore tab đang active trước khi reload, mặc định là dashboard
  const savedPage = localStorage.getItem('activePage') || 'dashboard';
  // strategy-detail không nên restore vì cần context, fallback về strategies
  const restorePage = savedPage === 'strategy-detail' ? 'strategies' : savedPage;
  showPage(restorePage);
};
