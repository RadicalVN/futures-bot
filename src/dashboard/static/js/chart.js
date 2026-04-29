import { api } from './api.js';

let chartInstances = {1: null, 2: null};
let chartAutoRefreshIntervals = {1: null, 2: null};
let chartTimeTrackerIntervals = {1: null, 2: null};
let lastChartUpdateTimes = {1: null, 2: null};
let isFetchingOlderDataMap = {1: false, 2: false};

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];

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

export function globalReset() {
    localStorage.removeItem('chartHiddenStates');
    loadChart(1);
    loadChart(2);
}

export function globalRefresh() {
    loadChart(1);
    loadChart(2);
}

export function toggleLegendMenu(chartId) {
    const menu = document.getElementById(`chartLegend${chartId}`);
    if (menu) {
        if (menu.style.display === 'none') {
            menu.style.display = 'flex';
            renderHtmlLegend(chartId);
        } else {
            menu.style.display = 'none';
        }
    }
}

function renderHtmlLegend(chartId) {
    const menu = document.getElementById(`chartLegend${chartId}`);
    const chart = chartInstances[chartId];
    if (!chart || !menu) return;
    
    let html = '';
    chart.data.datasets.forEach((ds, idx) => {
        const meta = chart.getDatasetMeta(idx);
        const isHidden = meta.hidden === null ? ds.hidden : meta.hidden;
        
        let color = '#888';
        if (ds.borderColor && typeof ds.borderColor === 'string' && ds.borderColor !== 'transparent') color = ds.borderColor;
        else if (ds.backgroundColor && typeof ds.backgroundColor === 'string' && ds.backgroundColor !== 'transparent') color = ds.backgroundColor;
        else if (ds.label === 'Giá') color = '#0ecb81';
        else if (ds.label === 'TVT-Trend') color = '#2196F3';
        
        html += `
        <div class="legend-item" onclick="toggleDataset(${chartId}, ${idx})" style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: ${isHidden ? '#666' : 'var(--text-primary)'}; text-decoration: ${isHidden ? 'line-through' : 'none'}; padding: 4px;">
            <div style="width: 12px; height: 12px; border-radius: 2px; background: ${color}; border: 1px solid rgba(255,255,255,0.2); opacity: ${isHidden ? 0.3 : 1};"></div>
            <span>${ds.label}</span>
        </div>`;
    });
    menu.innerHTML = html;
}

export function toggleDataset(chartId, datasetIndex) {
    const chart = chartInstances[chartId];
    const meta = chart.getDatasetMeta(datasetIndex);
    const ds = chart.data.datasets[datasetIndex];
    
    const isCurrentlyHidden = meta.hidden === null ? ds.hidden : meta.hidden;
    const willBeHidden = !isCurrentlyHidden;
    
    meta.hidden = willBeHidden;
    ds.hidden = willBeHidden;
    
    let states = JSON.parse(localStorage.getItem('chartHiddenStates')) || {};
    states[ds.label] = willBeHidden;
    localStorage.setItem('chartHiddenStates', JSON.stringify(states));
    
    chart.update('none');
    renderHtmlLegend(chartId); // Cập nhật lại màu chữ/gạch ngang
    
    // Đồng bộ sang biểu đồ còn lại
    const otherChartId = chartId === 1 ? 2 : 1;
    const otherChart = chartInstances[otherChartId];
    if (otherChart) {
        otherChart.data.datasets.forEach((otherDs, idx) => {
            if (otherDs.label === ds.label) {
                otherDs.hidden = willBeHidden;
                otherChart.getDatasetMeta(idx).hidden = willBeHidden;
            }
        });
        otherChart.update('none');
        renderHtmlLegend(otherChartId);
    }
}

// Đóng dropdown khi click ra ngoài
document.addEventListener('click', (e) => {
    if (!e.target.closest('.chart-legend-dropdown')) {
        const m1 = document.getElementById('chartLegend1');
        const m2 = document.getElementById('chartLegend2');
        if (m1) m1.style.display = 'none';
        if (m2) m2.style.display = 'none';
    }
});

export function onLeftTimeframeChange() {
    const leftSelect = document.getElementById('chartTimeframe1');
    const rightSelect = document.getElementById('chartTimeframe2');
    
    if (leftSelect && rightSelect) {
        const leftIdx = TIMEFRAMES.indexOf(leftSelect.value);
        const rightIdx = TIMEFRAMES.indexOf(rightSelect.value);
        
        // Bên phải luôn phải > bên trái
        if (rightIdx <= leftIdx) {
            const nextIndex = Math.min(leftIdx + 1, TIMEFRAMES.length - 1);
            rightSelect.value = TIMEFRAMES[nextIndex];
            loadChart(2);
        }
    }
    loadChart(1);
}

export function onRightTimeframeChange() {
    const leftSelect = document.getElementById('chartTimeframe1');
    const rightSelect = document.getElementById('chartTimeframe2');
    
    if (leftSelect && rightSelect) {
        const leftIdx = TIMEFRAMES.indexOf(leftSelect.value);
        const rightIdx = TIMEFRAMES.indexOf(rightSelect.value);
        
        // Bên phải không được <= bên trái
        if (rightIdx <= leftIdx) {
            alert("Khung thời gian biểu đồ 2 phải LỚN HƠN biểu đồ 1!");
            // Trả về đúng giá trị hợp lệ lớn hơn 1 bậc
            rightSelect.value = TIMEFRAMES[Math.min(leftIdx + 1, TIMEFRAMES.length - 1)];
        }
    }
    loadChart(2);
}

export function onSymbolChange(sourceId) {
    const sourceSymbol = document.getElementById(`chartSymbol${sourceId}`).value;
    document.getElementById('chartSymbol1').value = sourceSymbol;
    document.getElementById('chartSymbol2').value = sourceSymbol;
    loadChart(1);
    loadChart(2);
}

export async function loadChart(chartId = 1) {
    const symbolInput = document.getElementById(`chartSymbol${chartId}`);
    const timeframeSelect = document.getElementById(`chartTimeframe${chartId}`);
    
    if (!symbolInput.dataset.initialized) {
        const savedSymbol = localStorage.getItem(`lastChartSymbol${chartId}`);
        const savedTimeframe = localStorage.getItem(`lastChartTimeframe${chartId}`);
        if (savedSymbol) symbolInput.value = savedSymbol;
        if (savedTimeframe && timeframeSelect) timeframeSelect.value = savedTimeframe;
        symbolInput.dataset.initialized = 'true';
    }
    
    const symbol = symbolInput.value;
    const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
    
    localStorage.setItem(`lastChartSymbol${chartId}`, symbol);
    localStorage.setItem(`lastChartTimeframe${chartId}`, timeframe);
    
    const statusLabel = document.getElementById(`chartStatusLabel${chartId}`);
    
    document.getElementById(`chartTitle${chartId}`).innerText = `Đang tải ${symbol} (${timeframe})...`;
    if(statusLabel) {
        statusLabel.innerText = "Đang làm mới...";
        statusLabel.style.color = '#8892a4';
    }
    
    try {
        const json = await api.getChartData(symbol, timeframe);
        document.getElementById(`chartTitle${chartId}`).innerText = `Biểu đồ ${chartId} - ${symbol} (${timeframe})`;
        renderChart(json.data, chartId);
        
        lastChartUpdateTimes[chartId] = new Date();
        if(statusLabel) {
            statusLabel.innerText = "Đã cập nhật";
            statusLabel.style.color = '#0ecb81';
        }
        
        startAutoRefresh(chartId);
    } catch(err) {
        document.getElementById(`chartTitle${chartId}`).innerText = `Lỗi tải biểu đồ ${symbol}: ${err.message || err}`;
        if(statusLabel) {
            statusLabel.innerText = "Lỗi cập nhật";
            statusLabel.style.color = '#f6465d';
        }
        console.error(`loadChart(${chartId}) Error:`, err);
    }
}

function startAutoRefresh(chartId) {
    if(chartAutoRefreshIntervals[chartId]) clearInterval(chartAutoRefreshIntervals[chartId]);
    if(chartTimeTrackerIntervals[chartId]) clearInterval(chartTimeTrackerIntervals[chartId]);
    
    // Auto fetch ngầm mỗi 15 giây
    chartAutoRefreshIntervals[chartId] = setInterval(() => {
        silentFetchChart(chartId);
    }, 15000);
    
    // Tracking thời gian hiển thị mỗi giây
    chartTimeTrackerIntervals[chartId] = setInterval(() => {
        const statusLabel = document.getElementById(`chartStatusLabel${chartId}`);
        if(!statusLabel || !lastChartUpdateTimes[chartId]) return;
        if(statusLabel.innerText === "Lỗi cập nhật" || statusLabel.innerText === "Đang làm mới...") return;
        
        const diffSecs = Math.floor((new Date() - lastChartUpdateTimes[chartId]) / 1000);
        
        if (diffSecs < 5) {
            statusLabel.innerText = `Vừa cập nhật`;
            statusLabel.style.color = '#0ecb81';
        } else {
            statusLabel.innerText = `Cập nhật ${diffSecs} giây trước`;
            statusLabel.style.color = diffSecs > 30 ? '#FFEB3B' : '#8892a4';
        }
    }, 1000);
}

async function silentFetchChart(chartId) {
    const symbol = document.getElementById(`chartSymbol${chartId}`).value;
    const timeframeSelect = document.getElementById(`chartTimeframe${chartId}`);
    const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
    const statusLabel = document.getElementById(`chartStatusLabel${chartId}`);
    
    try {
        const json = await api.getChartData(symbol, timeframe);
        
        if (chartInstances[chartId]) {
            const newData = json.data;
            const datasets = chartInstances[chartId].data.datasets;
            
            const smaBasisData = newData.map(d => ({
                x: d.x, 
                y: d.sma_basis === null ? null : d.sma_basis, 
                momentum: d.sma_momentum,
                slope_pct: d.sma_slope_pct,
                momentum_pct: d.sma_momentum_pct
            }));
            const trendData = newData.map(d => {
                let val = null;
                if (d.sma_trend === 1 && d.sma_up !== 0) val = d.sma_up;
                else if (d.sma_trend === -1 && d.sma_dn !== 0) val = d.sma_dn;
                return { x: d.x, y: val, trend: d.sma_trend };
            });
            const macdData = newData.map(d => ({x: d.x, y: d.macd, momentum: d.macd_momentum || 'yellow'}));
            const macdSignalData = newData.map(d => ({x: d.x, y: d.macd_signal, momentum: d.macd_sig_momentum || 'yellow'}));
            const histData = newData.map(d => ({x: d.x, y: d.macd_hist, color: d.macd_hist_color || 'above_grow'}));
            const HIST_COLORS = {'above_grow':'#26A69A','above_fall':'#B2DFDB','below_grow':'#FFCDD2','below_fall':'#FF5252'};

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
                if(ds.label === 'MACD-Cross') ds.data = mergeData(ds.data, macdData);
                if(ds.label === 'MACD Signal') ds.data = mergeData(ds.data, macdSignalData);
                if(ds.label === 'MACD-Signal-Cross') ds.data = mergeData(ds.data, macdSignalData);
                if(ds.label === 'MACD Hist') {
                    ds.data = mergeData(ds.data, histData);
                    ds.backgroundColor = ds.data.map(d => HIST_COLORS[d.color] || '#888');
                }
            });
            chartInstances[chartId].update('none'); // Update ngầm
        } else {
            renderChart(json.data, chartId);
        }
        
        lastChartUpdateTimes[chartId] = new Date();
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

async function handlePanZoom({chart}, chartId) {
    if (isFetchingOlderDataMap[chartId]) return;
    
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
        // Gọi ngầm cập nhật nến mới
        silentFetchChart(chartId);
    }
    
    // 2. Nếu kéo sát lề trái (cách khoảng 30 nến) thì load thêm quá khứ
    const thresholdCandle = priceDataset.data[Math.min(30, priceDataset.data.length - 1)];
    
    if (xAxisMin < thresholdCandle.x) {
        isFetchingOlderDataMap[chartId] = true;
        const statusLabel = document.getElementById(`chartStatusLabel${chartId}`);
        if(statusLabel) {
            statusLabel.innerText = "Đang tải dữ liệu quá khứ...";
            statusLabel.style.color = '#8892a4';
        }
        
        try {
            const symbol = document.getElementById(`chartSymbol${chartId}`).value;
            const timeframeSelect = document.getElementById(`chartTimeframe${chartId}`);
            const timeframe = timeframeSelect ? timeframeSelect.value : '5m';
            
            const endTime = firstCandle.x - 1;
            const json = await api.getChartData(symbol, timeframe, endTime);
            
            if (json.data && json.data.length > 0) {
                const newData = json.data;
                const datasets = chart.data.datasets;
                
                const smaBasisData = newData.map(d => ({
                    x: d.x, 
                    y: d.sma_basis === null ? null : d.sma_basis, 
                    momentum: d.sma_momentum,
                    slope_pct: d.sma_slope_pct,
                    momentum_pct: d.sma_momentum_pct
                }));
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
            setTimeout(() => { isFetchingOlderDataMap[chartId] = false; }, 1000);
        }
    }
}

const TF_MS = {
    '1m': 60000, '3m': 180000, '5m': 300000, '15m': 900000,
    '30m': 1800000, '1h': 3600000, '4h': 14400000, '1d': 86400000, '1w': 604800000
};

let isSyncingZoom = false;
function syncPanZoom({chart}, sourceChartId) {
    if (isSyncingZoom) return;
    const targetChartId = sourceChartId === 1 ? 2 : 1;
    const targetChart = chartInstances[targetChartId];
    if (!targetChart) return;
    
    const sourceTF = document.getElementById(`chartTimeframe${sourceChartId}`).value;
    const targetTF = document.getElementById(`chartTimeframe${targetChartId}`).value;
    
    const sourceMs = TF_MS[sourceTF] || 300000;
    const targetMs = TF_MS[targetTF] || 900000;
    const ratio = targetMs / sourceMs;
    
    isSyncingZoom = true;
    
    const sourceMin = chart.scales.x.min;
    const sourceMax = chart.scales.x.max;
    const sourceSpan = sourceMax - sourceMin;
    
    const targetSpan = sourceSpan * ratio;
    
    // Neo ở cạnh phải để lúc nào nến cuối cùng cũng bằng nhau về mặt thời gian
    targetChart.options.scales.x.min = sourceMax - targetSpan;
    targetChart.options.scales.x.max = sourceMax;
    targetChart.update('none');
    
    // Unlock sau tick
    setTimeout(() => { isSyncingZoom = false; }, 0);
}

let isSyncingHover = false;

function renderChart(data, chartId) {
    const canvas = document.getElementById(`tradingChart${chartId}`);
    const ctx = canvas.getContext('2d');
    
    // Xoá tooltip của biểu đồ kia khi chuột rời khỏi canvas này
    canvas.onmouseleave = () => {
        if (isSyncingHover) return;
        const otherChartId = chartId === 1 ? 2 : 1;
        const otherCanvas = document.getElementById(`tradingChart${otherChartId}`);
        if (otherCanvas) {
            isSyncingHover = true;
            otherCanvas.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }));
            setTimeout(() => { isSyncingHover = false; }, 0);
        }
    };
    
    // Đọc trạng thái ẩn/hiện từ chung một khóa
    let hiddenStates = JSON.parse(localStorage.getItem('chartHiddenStates')) || {};
    if (chartInstances[chartId]) {
        chartInstances[chartId].data.datasets.forEach((ds, index) => {
            const meta = chartInstances[chartId].getDatasetMeta(index);
            if (meta && hiddenStates[ds.label] === undefined) {
                hiddenStates[ds.label] = meta.hidden;
            }
        });
        chartInstances[chartId].destroy();
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
        
        const smaBasisData = data.map(d => ({
            x: d.x, 
            y: d.sma_basis === null ? null : d.sma_basis, 
            momentum: d.sma_momentum,
            slope_pct: d.sma_slope_pct,
            momentum_pct: d.sma_momentum_pct
        }));

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
        // ── Histogram với 4 màu ──────────────────────────────────────────────
        const histData = data.map(d => ({
            x: d.x,
            y: d.macd_hist,
            color: d.macd_hist_color || 'above_grow'
        }));

        const HIST_COLORS = {
            'above_grow': '#26A69A',  // xanh ngọc đậm
            'above_fall': '#B2DFDB',  // xanh ngọc nhạt
            'below_grow': '#FFCDD2',  // đỏ nhạt
            'below_fall': '#FF5252',  // đỏ đậm
        };

        datasets.push({
            type: 'bar',
            label: 'MACD Hist',
            data: histData,
            backgroundColor: histData.map(d => HIST_COLORS[d.color] || '#888'),
            yAxisID: 'y_macd'
        });

        // ── MACD line + momentum cross ───────────────────────────────────────
        const macdWithMom = data.map(d => ({
            x: d.x,
            y: d.macd,
            momentum: d.macd_momentum || 'yellow'
        }));

        datasets.push({
            type: 'line',
            label: 'MACD',
            data: macdWithMom,
            borderColor: '#2962FF',
            borderWidth: 1.5,
            pointRadius: 0,
            yAxisID: 'y_macd'
        });

        datasets.push({
            type: 'scatter',
            label: 'MACD-Cross',
            data: macdWithMom,
            borderColor: function(context) {
                const mom = context.raw?.momentum;
                if (!mom) return 'transparent';
                const MAP = {
                    'yellow': '#FFEB3B', 'orange': '#FF9800', 'purple': '#9C27B0',
                    'blue': '#2196F3', 'red': '#f6465d', 'green': '#4CAF50'
                };
                return MAP[mom] || mom;
            },
            pointStyle: 'cross',
            pointRadius: 3,
            borderWidth: 2,
            yAxisID: 'y_macd'
        });

        // ── Signal line + momentum cross ─────────────────────────────────────
        const signalWithMom = data.map(d => ({
            x: d.x,
            y: d.macd_signal,
            momentum: d.macd_sig_momentum || 'yellow'
        }));

        datasets.push({
            type: 'line',
            label: 'MACD Signal',
            data: signalWithMom,
            borderColor: '#FF6D00',
            borderWidth: 1.5,
            pointRadius: 0,
            yAxisID: 'y_macd'
        });

        datasets.push({
            type: 'scatter',
            label: 'MACD-Signal-Cross',
            data: signalWithMom,
            borderColor: function(context) {
                const mom = context.raw?.momentum;
                if (!mom) return 'transparent';
                const MAP = {
                    'yellow': '#FFEB3B', 'orange': '#FF9800', 'purple': '#9C27B0',
                    'blue': '#2196F3', 'red': '#f6465d', 'green': '#4CAF50'
                };
                return MAP[mom] || mom;
            },
            pointStyle: 'cross',
            pointRadius: 3,
            borderWidth: 2,
            yAxisID: 'y_macd'
        });
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

    chartInstances[chartId] = new Chart(ctx, {
        type: 'candlestick',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, scales: chartScales,
            interaction: { mode: 'index', intersect: false },
            onHover: (event, elements, chart) => {
                if (isSyncingHover) return;
                
                const targetChartId = chartId === 1 ? 2 : 1;
                const targetChart = chartInstances[targetChartId];
                if (!targetChart || elements.length === 0) return;

                const dataIndex = elements[0].index;
                if (!chart.data.datasets[0].data[dataIndex]) return;
                const timestamp = chart.data.datasets[0].data[dataIndex].x;

                const targetCanvas = document.getElementById(`tradingChart${targetChartId}`);
                if (!targetCanvas) return;
                
                const rect = targetCanvas.getBoundingClientRect();
                const targetX = targetChart.scales.x.getPixelForValue(timestamp);
                
                let clientY = event.native ? event.native.clientY : (rect.top + event.y);

                isSyncingHover = true;
                const mouseEvent = new MouseEvent('mousemove', {
                    clientX: rect.left + targetX,
                    clientY: clientY,
                    bubbles: true
                });
                targetCanvas.dispatchEvent(mouseEvent);
                setTimeout(() => { isSyncingHover = false; }, 0);
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            
                            // Xử lý riêng cho biểu đồ nến (Giá)
                            if (label === 'Giá') {
                                const raw = context.raw;
                                if (raw && raw.c !== undefined) {
                                    return `Giá: O: ${raw.o.toFixed(2)}  H: ${raw.h.toFixed(2)}  L: ${raw.l.toFixed(2)}  C: ${raw.c.toFixed(2)}`;
                                }
                                return label;
                            }
                            
                            if (label) label += ': ';
                            if (context.parsed.y !== null && context.parsed.y !== undefined && !isNaN(context.parsed.y)) {
                                label += Number(context.parsed.y).toFixed(4);
                            } else {
                                return null; // Ẩn tooltip nếu không có dữ liệu tại điểm này
                            }
                            
                            if (context.dataset.label === 'TVT-MA') {
                                const slopePct = context.raw?.slope_pct;
                                if (slopePct !== undefined && slopePct !== null) {
                                    label += ` (Dốc: ${slopePct > 0 ? '+' : ''}${slopePct.toFixed(4)}%)`;
                                }
                            }
                            if (context.dataset.label === 'TVT-MA-Cross') {
                                const momPct = context.raw?.momentum_pct;
                                if (momPct !== undefined && momPct !== null) {
                                    label += ` (Gia tốc: ${momPct > 0 ? '+' : ''}${momPct.toFixed(4)}%)`;
                                }
                            }
                            return label;
                        }
                    }
                },
                legend: { 
                    display: false 
                },
                zoom: { 
                    pan: { 
                        enabled: true, mode: 'x', 
                        onPan: (ctx) => syncPanZoom(ctx, chartId),
                        onPanComplete: (ctx) => handlePanZoom(ctx, chartId) 
                    }, 
                    zoom: { 
                        wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x', 
                        onZoom: (ctx) => syncPanZoom(ctx, chartId),
                        onZoomComplete: (ctx) => handlePanZoom(ctx, chartId) 
                    } 
                }
            }
        },
        plugins: [splitPanePlugin, customCanvasBackgroundColor, currentPricePlugin]
    });
}
