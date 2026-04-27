import { api } from './api.js';

let chartInstance = null;
let chartAutoRefreshInterval = null;
let chartTimeTrackerInterval = null;
let lastChartUpdateTime = null;
let isFetchingOlderData = false;

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

export function resetChartConfig() {
    localStorage.removeItem('chartHiddenStates');
    loadChart();
}

export async function loadChart() {
    const symbolInput = document.getElementById('chartSymbol');
    const timeframeSelect = document.getElementById('chartTimeframe');
    
    if (!symbolInput.dataset.initialized) {
        const savedSymbol = localStorage.getItem('lastChartSymbol');
        const savedTimeframe = localStorage.getItem('lastChartTimeframe');
        if (savedSymbol) symbolInput.value = savedSymbol;
        if (savedTimeframe && timeframeSelect) timeframeSelect.value = savedTimeframe;
        symbolInput.dataset.initialized = 'true';
    }
    
    const symbol = symbolInput.value;
    const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
    
    localStorage.setItem('lastChartSymbol', symbol);
    localStorage.setItem('lastChartTimeframe', timeframe);
    
    const statusLabel = document.getElementById('chartStatusLabel');
    
    document.getElementById('chartTitle').innerText = `Đang tải ${symbol} (${timeframe})...`;
    if(statusLabel) {
        statusLabel.innerText = "Đang làm mới...";
        statusLabel.style.color = '#8892a4';
    }
    
    try {
        const json = await api.getChartData(symbol, timeframe);
        document.getElementById('chartTitle').innerText = `Biểu đồ Nến - ${symbol} (${timeframe})`;
        renderChart(json.data);
        
        lastChartUpdateTime = new Date();
        if(statusLabel) {
            statusLabel.innerText = "Đã cập nhật";
            statusLabel.style.color = '#0ecb81';
        }
        
        startAutoRefresh();
    } catch(err) {
        document.getElementById('chartTitle').innerText = `Lỗi tải biểu đồ ${symbol}: ${err.message || err}`;
        if(statusLabel) {
            statusLabel.innerText = "Lỗi cập nhật";
            statusLabel.style.color = '#f6465d';
        }
        console.error("loadChart Error:", err);
    }
}

function startAutoRefresh() {
    if(chartAutoRefreshInterval) clearInterval(chartAutoRefreshInterval);
    if(chartTimeTrackerInterval) clearInterval(chartTimeTrackerInterval);
    
    // Auto fetch ngầm mỗi 15 giây
    chartAutoRefreshInterval = setInterval(() => {
        silentFetchChart();
    }, 15000);
    
    // Tracking thời gian hiển thị mỗi giây
    chartTimeTrackerInterval = setInterval(() => {
        const statusLabel = document.getElementById('chartStatusLabel');
        if(!statusLabel || !lastChartUpdateTime) return;
        if(statusLabel.innerText === "Lỗi cập nhật" || statusLabel.innerText === "Đang làm mới...") return;
        
        const diffSecs = Math.floor((new Date() - lastChartUpdateTime) / 1000);
        
        if (diffSecs < 5) {
            statusLabel.innerText = `Vừa cập nhật`;
            statusLabel.style.color = '#0ecb81';
        } else {
            statusLabel.innerText = `Cập nhật ${diffSecs} giây trước`;
            statusLabel.style.color = diffSecs > 30 ? '#FFEB3B' : '#8892a4';
        }
    }, 1000);
}

async function silentFetchChart() {
    const symbol = document.getElementById('chartSymbol').value;
    const timeframeSelect = document.getElementById('chartTimeframe');
    const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
    const statusLabel = document.getElementById('chartStatusLabel');
    
    try {
        const json = await api.getChartData(symbol, timeframe);
        
        if (chartInstance) {
            const newData = json.data;
            const datasets = chartInstance.data.datasets;
            
            const smaBasisData = newData.map(d => ({x: d.x, y: d.sma_basis === null ? null : d.sma_basis, momentum: d.sma_momentum}));
            const trendData = newData.map(d => {
                let val = null;
                if (d.sma_trend === 1 && d.sma_up !== 0) val = d.sma_up;
                else if (d.sma_trend === -1 && d.sma_dn !== 0) val = d.sma_dn;
                return { x: d.x, y: val, trend: d.sma_trend };
            });
            const macdData = newData.map(d => ({x: d.x, y: d.macd}));
            const macdSignalData = newData.map(d => ({x: d.x, y: d.macd_signal}));
            const histData = macdData.map((d, i) => {
                let val = null;
                if (d.y !== null && macdSignalData[i] && macdSignalData[i].y !== null) {
                    val = d.y - macdSignalData[i].y;
                }
                return { x: d.x, y: val };
            });

            function mergeData(oldData, newChunk) {
                if (!oldData || !oldData.length) return newChunk;
                const matchIndex = oldData.findIndex(d => d.x === newChunk[0].x);
                if (matchIndex !== -1) {
                    oldData.splice(matchIndex, oldData.length - matchIndex, ...newChunk);
                    return oldData;
                }
                return newChunk;
            }

            datasets.forEach(ds => {
                if(ds.label === 'Giá') ds.data = mergeData(ds.data, newData);
                if(ds.label === 'TVT-Trend') ds.data = mergeData(ds.data, trendData);
                if(ds.label === 'TVT-MA') ds.data = mergeData(ds.data, smaBasisData);
                if(ds.label === 'TVT-MA-Cross') ds.data = mergeData(ds.data, smaBasisData);
                if(ds.label === 'MACD') ds.data = mergeData(ds.data, macdData);
                if(ds.label === 'MACD Signal') ds.data = mergeData(ds.data, macdSignalData);
                if(ds.label === 'MACD Hist') {
                    ds.data = mergeData(ds.data, histData);
                    ds.backgroundColor = ds.data.map(d => d.y !== null && d.y >= 0 ? 'rgba(14, 203, 129, 0.5)' : 'rgba(246, 70, 93, 0.5)');
                }
            });
            chartInstance.update('none'); // Update ngầm
        } else {
            renderChart(json.data);
        }
        
        lastChartUpdateTime = new Date();
        if(statusLabel) {
            statusLabel.innerText = "Đã cập nhật";
            statusLabel.style.color = '#0ecb81';
        }
    } catch (e) {
        if(statusLabel) {
            statusLabel.innerText = "Lỗi cập nhật";
            statusLabel.style.color = '#f6465d';
        }
        console.error("Auto fetch failed:", e);
    }
}

async function handlePanZoom({chart}) {
    if (isFetchingOlderData) return;
    
    const priceDataset = chart.data.datasets.find(d => d.label === 'Giá');
    if (!priceDataset || !priceDataset.data.length) return;
    
    const firstCandle = priceDataset.data[0];
    const xAxisMin = chart.scales.x.min;
    const xAxisMax = chart.scales.x.max;
    
    // 1. Nếu kéo sát lề phải (hiện tại), lấy luôn dữ liệu nến mới nhất chứ không chờ 15s
    const lastCandle = priceDataset.data[priceDataset.data.length - 1];
    // Sát khoảng 5 nến cuối
    const rightThreshold = priceDataset.data[Math.max(0, priceDataset.data.length - 5)];
    if (xAxisMax >= rightThreshold.x) {
        // Gọi ngầm cập nhật nến mới (không lock isFetchingOlderData vì nó xài chung)
        silentFetchChart();
    }
    
    // 2. Nếu kéo sát lề trái (cách khoảng 30 nến) thì load thêm quá khứ
    const thresholdCandle = priceDataset.data[Math.min(30, priceDataset.data.length - 1)];
    
    if (xAxisMin < thresholdCandle.x) {
        isFetchingOlderData = true;
        const statusLabel = document.getElementById('chartStatusLabel');
        if(statusLabel) {
            statusLabel.innerText = "Đang tải dữ liệu quá khứ...";
            statusLabel.style.color = '#8892a4';
        }
        
        try {
            const symbol = document.getElementById('chartSymbol').value;
            const timeframeSelect = document.getElementById('chartTimeframe');
            const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
            
            const endTime = firstCandle.x - 1;
            const json = await api.getChartData(symbol, timeframe, endTime);
            
            if (json.data && json.data.length > 0) {
                const newData = json.data;
                const datasets = chart.data.datasets;
                
                const smaBasisData = newData.map(d => ({x: d.x, y: d.sma_basis === null ? null : d.sma_basis, momentum: d.sma_momentum}));
                const trendData = newData.map(d => {
                    let val = null;
                    if (d.sma_trend === 1 && d.sma_up !== 0) val = d.sma_up;
                    else if (d.sma_trend === -1 && d.sma_dn !== 0) val = d.sma_dn;
                    return { x: d.x, y: val, trend: d.sma_trend };
                });
                const macdData = newData.map(d => ({x: d.x, y: d.macd}));
                const macdSignalData = newData.map(d => ({x: d.x, y: d.macd_signal}));
                const histData = macdData.map((d, i) => {
                    let val = null;
                    if (d.y !== null && macdSignalData[i] && macdSignalData[i].y !== null) {
                        val = d.y - macdSignalData[i].y;
                    }
                    return { x: d.x, y: val };
                });

                datasets.forEach(ds => {
                    if(ds.label === 'Giá') ds.data = newData.concat(ds.data);
                    if(ds.label === 'TVT-Trend') ds.data = trendData.concat(ds.data);
                    if(ds.label === 'TVT-MA') ds.data = smaBasisData.concat(ds.data);
                    if(ds.label === 'TVT-MA-Cross') ds.data = smaBasisData.concat(ds.data);
                    if(ds.label === 'MACD') ds.data = macdData.concat(ds.data);
                    if(ds.label === 'MACD Signal') ds.data = macdSignalData.concat(ds.data);
                    if(ds.label === 'MACD Hist') {
                        ds.data = histData.concat(ds.data);
                        ds.backgroundColor = ds.data.map(d => d.y !== null && d.y >= 0 ? 'rgba(14, 203, 129, 0.5)' : 'rgba(246, 70, 93, 0.5)');
                    }
                });
                
                chart.update('none'); // Update ngầm
                
                if(statusLabel) {
                    statusLabel.innerText = "Đã nối dữ liệu quá khứ";
                    statusLabel.style.color = '#0ecb81';
                }
            }
        } catch (e) {
            console.error("Lỗi lấy dữ liệu quá khứ:", e);
        } finally {
            setTimeout(() => { isFetchingOlderData = false; }, 1000);
        }
    }
}

function renderChart(data) {
    const ctx = document.getElementById('tradingChart').getContext('2d');
    
    // Đọc trạng thái ẩn/hiện từ localStorage hoặc chart cũ
    let hiddenStates = JSON.parse(localStorage.getItem('chartHiddenStates')) || {};
    if (chartInstance) {
        chartInstance.data.datasets.forEach((ds, index) => {
            const meta = chartInstance.getDatasetMeta(index);
            if (meta && hiddenStates[ds.label] === undefined) {
                hiddenStates[ds.label] = meta.hidden;
            }
        });
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

    const currentPricePlugin = {
        id: 'currentPricePlugin',
        afterDraw: (chart) => {
            const priceDataset = chart.data.datasets.find(d => d.label === 'Giá');
            if (!priceDataset || !priceDataset.data.length) return;
            
            const lastCandle = priceDataset.data[priceDataset.data.length - 1];
            if (!lastCandle) return;
            const currentPrice = lastCandle.c;
            
            const ctx = chart.ctx;
            const yAxis = chart.scales['y'];
            const yPos = yAxis.getPixelForValue(currentPrice);
            
            // Draw horizontal dashed line across chartArea
            ctx.save();
            ctx.beginPath();
            ctx.setLineDash([4, 4]);
            ctx.moveTo(chart.chartArea.left, yPos);
            ctx.lineTo(chart.chartArea.right, yPos);
            ctx.lineWidth = 1;
            
            const isUp = lastCandle.c >= lastCandle.o;
            const color = isUp ? '#2196F3' : '#f6465d'; // Màu xanh dương hoặc đỏ cho nổi bật
            ctx.strokeStyle = color;
            ctx.stroke();
            
            // Draw label box on the Y axis
            ctx.setLineDash([]);
            const text = currentPrice.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 2});
            ctx.font = 'bold 12px "Inter", sans-serif';
            
            const textWidth = ctx.measureText(text).width;
            const boxWidth = textWidth + 12;
            const boxHeight = 22;
            const rectX = chart.chartArea.right;
            const rectY = yPos - boxHeight / 2;
            
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(rectX, rectY);
            ctx.lineTo(rectX + boxWidth, rectY);
            ctx.lineTo(rectX + boxWidth, rectY + boxHeight);
            ctx.lineTo(rectX, rectY + boxHeight);
            ctx.lineTo(rectX - 6, yPos); // Mũi tên nhọn chỉ vào trong
            ctx.closePath();
            ctx.fill();
            
            // Label text
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, rectX + boxWidth / 2, yPos);
            
            ctx.restore();
        }
    };

    // Khôi phục trạng thái ẩn/hiện
    datasets.forEach(ds => {
        if (hiddenStates[ds.label] !== undefined) {
            ds.hidden = hiddenStates[ds.label];
        }
    });

    chartInstance = new Chart(ctx, {
        type: 'candlestick',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, scales: chartScales,
            plugins: {
                legend: { 
                    display: true, 
                    labels: { color: '#333' },
                    onClick: function(e, legendItem, legend) {
                        Chart.defaults.plugins.legend.onClick.call(this, e, legendItem, legend);
                        setTimeout(() => {
                            let states = {};
                            legend.chart.data.datasets.forEach((ds, idx) => {
                                const meta = legend.chart.getDatasetMeta(idx);
                                if (meta) states[ds.label] = meta.hidden;
                            });
                            localStorage.setItem('chartHiddenStates', JSON.stringify(states));
                        }, 50);
                    }
                },
                zoom: { 
                    pan: { enabled: true, mode: 'x', onPanComplete: handlePanZoom }, 
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x', onZoomComplete: handlePanZoom } 
                }
            }
        },
        plugins: [splitPanePlugin, customCanvasBackgroundColor, currentPricePlugin]
    });
}
