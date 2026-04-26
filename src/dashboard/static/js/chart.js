import { api } from './api.js';

let chartInstance = null;

export async function populateSymbolsDatalist() {
  try {
    const data = await api.getSymbols();
    const symbols = data.symbols || [];
    const datalist = document.getElementById('binanceSymbols');
    if(datalist) {
      datalist.innerHTML = symbols.map(s => `<option value="${s}">`).join('');
    }
  } catch (err) {
    console.error("Lỗi lấy danh sách symbol:", err);
  }
}

export async function loadChart() {
    const symbol = document.getElementById('chartSymbol').value;
    document.getElementById('chartTitle').innerText = `Đang tải ${symbol}...`;
    
    try {
        const json = await api.getChartData(symbol);
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
    
    const activeIndicatorsIds = JSON.parse(localStorage.getItem('activeIndicators')) || ['custom_sma', 'custom_macd'];
    const smaUpData = data.map(d => ({x: d.x, y: d.sma_up === 0 ? null : d.sma_up}));
    const smaDnData = data.map(d => ({x: d.x, y: d.sma_dn === 0 ? null : d.sma_dn}));
    const macdData = data.map(d => ({x: d.x, y: d.macd}));
    const macdSignalData = data.map(d => ({x: d.x, y: d.macd_signal}));

    let datasets = [
        {
            label: 'Giá',
            data: data,
            color: { up: '#0ecb81', down: '#f6465d', unchanged: '#8892a4' },
            yAxisID: 'y'
        }
    ];

    if (activeIndicatorsIds.includes('custom_sma')) {
        datasets.push({ type: 'line', label: 'SMA Up', data: smaUpData, borderColor: '#2196F3', borderWidth: 1.5, pointRadius: 0, yAxisID: 'y' });
        datasets.push({ type: 'line', label: 'SMA Down', data: smaDnData, borderColor: '#FFEB3B', borderWidth: 1.5, pointRadius: 0, yAxisID: 'y' });
    }

    if (activeIndicatorsIds.includes('custom_macd')) {
        const histData = macdData.map((d, i) => {
            let val = null;
            if (d.y !== null && macdSignalData[i] && macdSignalData[i].y !== null) {
                val = d.y - macdSignalData[i].y;
            }
            return { x: d.x, y: val };
        });

        datasets.push({ type: 'bar', label: 'MACD Hist', data: histData, backgroundColor: histData.map(d => d.y !== null && d.y >= 0 ? 'rgba(14, 203, 129, 0.5)' : 'rgba(246, 70, 93, 0.5)'), yAxisID: 'y_macd' });
        datasets.push({ type: 'line', label: 'MACD', data: macdData, borderColor: '#2962FF', borderWidth: 1.5, pointRadius: 0, yAxisID: 'y_macd' });
        datasets.push({ type: 'line', label: 'MACD Signal', data: macdSignalData, borderColor: '#FF6D00', borderWidth: 1.5, pointRadius: 0, yAxisID: 'y_macd' });
    }

    let chartScales = {
        x: { type: 'time', time: { tooltipFormat: 'yyyy-MM-dd HH:mm' }, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8892a4' } },
        y: { type: 'linear', display: true, position: 'right', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8892a4' } }
    };

    if (activeIndicatorsIds.includes('custom_macd')) {
        chartScales.y.stack = 'main';
        chartScales.y.stackWeight = 3;
        chartScales.y_macd = {
            type: 'linear', display: true, position: 'right', grid: { color: 'rgba(255,255,255,0.05)', drawOnChartArea: true }, ticks: { color: '#8892a4' }, stack: 'main', stackWeight: 1
        };
    }

    const splitPanePlugin = {
        id: 'splitPane',
        beforeDraw(chart) {
            if (!chart.scales.y_macd) return;
            const ctx = chart.ctx;
            const yMacdAxis = chart.scales.y_macd;
            ctx.save();
            ctx.fillStyle = 'rgba(0, 0, 0, 0.15)';
            ctx.fillRect(chart.chartArea.left, yMacdAxis.top, chart.chartArea.right - chart.chartArea.left, yMacdAxis.bottom - yMacdAxis.top);
            ctx.beginPath();
            ctx.moveTo(chart.chartArea.left, yMacdAxis.top);
            ctx.lineTo(chart.chartArea.right, yMacdAxis.top);
            ctx.lineWidth = 2;
            ctx.strokeStyle = '#444';
            ctx.stroke();
            ctx.restore();
        }
    };

    chartInstance = new Chart(ctx, {
        type: 'candlestick',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, scales: chartScales,
            plugins: {
                legend: { display: true, labels: { color: '#8892a4' } },
                zoom: { pan: { enabled: true, mode: 'x' }, zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' } }
            }
        },
        plugins: [splitPanePlugin]
    });
}
