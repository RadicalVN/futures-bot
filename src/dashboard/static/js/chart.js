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

    // Ép màu toàn cục cho nến Nhật
    if (Chart.defaults && Chart.defaults.elements && Chart.defaults.elements.candlestick) {
        Chart.defaults.elements.candlestick.backgroundColors = { up: 'rgba(0,0,0,0)', down: '#000000', unchanged: '#000000' };
        Chart.defaults.elements.candlestick.borderColors = '#000000';
    }

    let datasets = [
        {
            label: 'Giá',
            data: data,
            backgroundColors: { up: 'rgba(0,0,0,0)', down: '#000000', unchanged: '#000000' },
            borderColors: '#000000',
            yAxisID: 'y'
        }
    ];

    if (activeIndicatorsIds.includes('custom_sma')) {
        const trendData = data.map(d => {
            let val = null;
            if (d.sma_trend === 1 && d.sma_up !== 0) val = d.sma_up;
            else if (d.sma_trend === -1 && d.sma_dn !== 0) val = d.sma_dn;
            return { x: d.x, y: val, trend: d.sma_trend };
        });
        
        const smaBasisData = data.map(d => ({x: d.x, y: d.sma_basis === null ? null : d.sma_basis, momentum: d.sma_momentum}));

        datasets.push({ 
            type: 'scatter', 
            label: 'TVT-Trend', 
            data: trendData, 
            backgroundColor: function(context) {
                const tr = context.raw?.trend;
                return tr === 1 ? '#2196F3' : (tr === -1 ? '#FFEB3B' : 'transparent');
            },
            borderColor: 'transparent',
            pointStyle: 'circle',
            pointRadius: 4,
            borderWidth: 0,
            yAxisID: 'y' 
        });

        datasets.push({ 
            type: 'line', 
            label: 'TVT-MA', 
            data: smaBasisData, 
            spanGaps: true,
            segment: {
                borderColor: ctx => {
                    if (!ctx.p0 || !ctx.p1 || !ctx.p0.parsed || !ctx.p1.parsed) return '#2196F3';
                    const curr = ctx.p1.parsed.y;
                    const prev = ctx.p0.parsed.y;
                    if (curr > prev) return '#2196F3'; // blue
                    if (curr < prev) return '#f6465d'; // red
                    return '#FFEB3B'; // yellow
                }
            },
            borderWidth: 2, 
            pointRadius: 0, 
            yAxisID: 'y' 
        });

        datasets.push({ 
            type: 'scatter', 
            label: 'TVT-MA-Cross', 
            data: smaBasisData, 
            borderColor: function(context) {
                const mom = context.raw?.momentum;
                if (!mom || mom === 'Chưa rõ') return 'transparent';
                if (mom === 'yellow') return '#FFEB3B';
                if (mom === 'orange') return '#FF9800';
                if (mom === 'purple') return '#9C27B0';
                if (mom === 'blue') return '#2196F3';
                if (mom === 'red') return '#f6465d';
                if (mom === 'green') return '#4CAF50';
                return mom;
            },
            pointStyle: 'cross',
            pointRadius: 4,
            borderWidth: 2,
            yAxisID: 'y' 
        });
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
        x: { type: 'time', time: { tooltipFormat: 'yyyy-MM-dd HH:mm' }, grid: { color: 'rgba(0,0,0,0.1)' }, ticks: { color: '#333' } },
        y: { 
            type: 'linear', display: true, position: 'right', grid: { color: 'rgba(0,0,0,0.1)' }, 
            ticks: { 
                color: '#333',
                callback: function(val, index) {
                    // Ẩn tick thấp nhất để tránh đè lên MACD
                    return index === 0 ? '' : val;
                }
            } 
        }
    };

    if (activeIndicatorsIds.includes('custom_macd')) {
        chartScales.y.stack = 'main';
        chartScales.y.stackWeight = 3;
        chartScales.y_macd = {
            type: 'linear', display: true, position: 'right', grid: { color: 'rgba(0,0,0,0.1)', drawOnChartArea: true }, 
            ticks: { 
                color: '#333',
                callback: function(val, index, ticks) {
                    // Ẩn tick cao nhất để tránh đè lên Price
                    return index === ticks.length - 1 ? '' : val;
                }
            }, 
            stack: 'main', stackWeight: 1
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

    const customCanvasBackgroundColor = {
        id: 'customCanvasBackgroundColor',
        beforeDraw: (chart) => {
            const ctx = chart.canvas.getContext('2d');
            ctx.save();
            ctx.globalCompositeOperation = 'destination-over';
            ctx.fillStyle = 'white';
            ctx.fillRect(0, 0, chart.width, chart.height);
            ctx.restore();
        }
    };

    chartInstance = new Chart(ctx, {
        type: 'candlestick',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, scales: chartScales,
            plugins: {
                legend: { display: true, labels: { color: '#333' } },
                zoom: { pan: { enabled: true, mode: 'x' }, zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' } }
            }
        },
        plugins: [splitPanePlugin, customCanvasBackgroundColor]
    });
}
