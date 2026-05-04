/**
 * backtest_chart.js — Backtest Chart (Windowed Rendering)
 *
 * Chỉ render N nến trong viewport hiện tại (BACKTEST_CHART_CANDLES).
 * Khi pan/zoom → rebuild datasets từ slice mới → không lag dù data lớn.
 */

let _btChartInstance  = null;
let _btChartData      = null;
let _btAllCandles     = null;   // toàn bộ candles (không truyền vào chart)
let _btAllTrades      = null;
let _btDefaultCandles = 200;
let _btTradeLineVis   = true;
let _btRenderLegendFn = null;
let _btTfMs           = 300000;

async function _loadConfig() {
  try {
    const r = await fetch('/api/backtest/config');
    const cfg = await r.json();
    _btDefaultCandles = cfg.chart_candles || 200;
  } catch (_) {}
}
_loadConfig();

// ── Slice data theo window [xMin, xMax] ──────────────────────────────────────
function _sliceByRange(arr, xMin, xMax) {
  // Binary search để tìm start/end index nhanh
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid].x < xMin) lo = mid + 1; else hi = mid;
  }
  const start = Math.max(0, lo - 1);
  let end = start;
  while (end < arr.length && arr[end].x <= xMax) end++;
  end = Math.min(arr.length, end + 1);
  return arr.slice(start, end);
}

// ── Build datasets từ slice ───────────────────────────────────────────────────
function _buildDatasets(slice, trades, slopeColor, MOM_COLOR, HIST_COLORS, slopeBarColor) {
  const smaBasisData  = slice.map(d => ({ x:d.x, y:d.sma_basis??null, momentum:d.sma_momentum, slope_pct:d.sma_slope_pct, momentum_pct:d.sma_momentum_pct }));
  const smaBasisDataN = slice.map(d => ({ x:d.x, y:d.sma_basis??null, momentum_n:d.sma_momentum_n, momentum_n_pct:d.sma_momentum_n_pct }));
  const smaBasisYArr  = slice.map(d => d.sma_basis);
  const trendData     = slice.map(d => { let v=null; if(d.sma_trend===1&&d.sma_up!==0)v=d.sma_up; else if(d.sma_trend===-1&&d.sma_dn!==0)v=d.sma_dn; return {x:d.x,y:v,trend:d.sma_trend}; });
  const smaSlopeData  = slice.map(d => ({ x:d.x, y:d.sma_slope_pct??null }));
  const smaAccelData  = slice.map(d => ({ x:d.x, y:d.sma_momentum_pct??null, momentum:d.sma_momentum }));
  const histData      = slice.map(d => ({ x:d.x, y:d.macd_hist??null, color:d.macd_hist_color||'above_grow' }));
  const macdWithMom   = slice.map(d => ({ x:d.x, y:d.macd??null, momentum:d.macd_momentum||'yellow' }));
  const signalWithMom = slice.map(d => ({ x:d.x, y:d.macd_signal??null, momentum:d.macd_sig_momentum||'yellow', slope_pct:d.macd_sig_slope_pct }));
  const macdYArr      = slice.map(d => d.macd);
  const sigYArr       = slice.map(d => d.macd_signal);
  const macdSlopeData = slice.map(d => ({ x:d.x, y:d.macd_slope_pct??null }));
  const sigSlopeData  = slice.map(d => ({ x:d.x, y:d.macd_sig_slope_pct??null }));
  const sigAccelData  = slice.map(d => ({ x:d.x, y:d.macd_sig_momentum_pct??null, momentum:d.macd_sig_momentum }));

  // Entry/Exit markers — chỉ lấy trades trong range
  const xMin = slice.length ? slice[0].x : 0;
  const xMax = slice.length ? slice[slice.length-1].x : Infinity;
  const longEntries=[], shortEntries=[], exitWins=[], exitLosses=[];
  trades.forEach((t, idx) => {
    const inRange = (t.entry_ts >= xMin && t.entry_ts <= xMax) || (t.exit_ts >= xMin && t.exit_ts <= xMax);
    if (!inRange) return;
    const ep = { x:t.entry_ts, y:t.entry_price, _idx:idx };
    const xp = { x:t.exit_ts,  y:t.exit_price,  _idx:idx };
    if (t.side==='long') longEntries.push(ep); else shortEntries.push(ep);
    if ((t.pnl??0)>=0) exitWins.push(xp); else exitLosses.push(xp);
  });

  return [
    { label:'Giá', data:slice, backgroundColors:{up:'rgba(0,0,0,0)',down:'#000',unchanged:'#000'}, borderColors:'#000', yAxisID:'y' },
    { type:'scatter', label:'TVT-Trend', data:trendData, backgroundColor:c=>{const t=c.raw?.trend;return t===1?'#2196F3':(t===-1?'#FFEB3B':'transparent');}, borderColor:'transparent', pointStyle:'circle', pointRadius:4, borderWidth:0, yAxisID:'y' },
    { type:'line', label:'TVT-MA', data:smaBasisData, spanGaps:true, segment:{borderColor:slopeColor}, borderWidth:2, pointRadius:0, yAxisID:'y' },
    { type:'scatter', label:'TVT-MA-Cross', data:smaBasisData, borderColor:c=>MOM_COLOR[c.raw?.momentum]||'transparent', pointStyle:'cross', pointRadius:4, borderWidth:2, yAxisID:'y' },
    { type:'scatter', label:'TVT-MA-Cross-N', data:smaBasisDataN, borderColor:c=>MOM_COLOR[c.raw?.momentum_n]||'transparent', pointStyle:'crossRot', pointRadius:6, borderWidth:2, yAxisID:'y' },
    { type:'bar', label:'TVT-MA Slope', data:smaSlopeData, backgroundColor:smaBasisYArr.map((_,i)=>slopeBarColor(smaBasisYArr,i)), borderWidth:0, barPercentage:0.6, categoryPercentage:1.0, yAxisID:'y_sma_slope' },
    { type:'bar', label:'TVT-MA Accel', data:smaAccelData, backgroundColor:slice.map(d=>MOM_COLOR[d.sma_momentum]||'#888'), borderWidth:0, barPercentage:0.6, categoryPercentage:1.0, yAxisID:'y_sma_slope' },
    { type:'bar',  label:'MACD Hist', data:histData, backgroundColor:histData.map(d=>HIST_COLORS[d.color]||'#888'), yAxisID:'y_macd' },
    { type:'line', label:'MACD', data:macdWithMom, spanGaps:true, segment:{borderColor:slopeColor}, borderWidth:1.5, pointRadius:0, yAxisID:'y_macd' },
    { type:'scatter', label:'MACD-Cross', data:macdWithMom, borderColor:c=>MOM_COLOR[c.raw?.momentum]||'transparent', pointStyle:'cross', pointRadius:3, borderWidth:2, yAxisID:'y_macd' },
    { type:'line', label:'MACD Signal', data:signalWithMom, spanGaps:true, segment:{borderColor:slopeColor}, borderWidth:1.5, pointRadius:0, yAxisID:'y_macd' },
    { type:'scatter', label:'MACD-Signal-Cross', data:signalWithMom, borderColor:c=>MOM_COLOR[c.raw?.momentum]||'transparent', pointStyle:'cross', pointRadius:3, borderWidth:2, yAxisID:'y_macd' },
    { type:'bar', label:'MACD Slope', data:macdSlopeData, backgroundColor:macdYArr.map((_,i)=>slopeBarColor(macdYArr,i)), borderWidth:0, barPercentage:0.6, categoryPercentage:1.0, yAxisID:'y_macd_slope' },
    { type:'bar', label:'Signal Slope', data:sigSlopeData, backgroundColor:sigYArr.map((_,i)=>slopeBarColor(sigYArr,i)), borderWidth:0, barPercentage:0.6, categoryPercentage:1.0, yAxisID:'y_sig_slope' },
    { type:'bar', label:'Signal Accel', data:sigAccelData, backgroundColor:slice.map(d=>MOM_COLOR[d.macd_sig_momentum]||'#888'), borderWidth:0, barPercentage:0.6, categoryPercentage:1.0, yAxisID:'y_sig_slope' },
    { type:'scatter', label:'Long Entry',  data:longEntries,  backgroundColor:'#0ecb81', borderColor:'#0ecb81', pointStyle:'triangle', pointRadius:9, rotation:0,   yAxisID:'y', order:-2 },
    { type:'scatter', label:'Short Entry', data:shortEntries, backgroundColor:'#f6465d', borderColor:'#f6465d', pointStyle:'triangle', pointRadius:9, rotation:180, yAxisID:'y', order:-2 },
    { type:'scatter', label:'Exit Win',    data:exitWins,     backgroundColor:'rgba(14,203,129,0.9)', borderColor:'#0ecb81', pointStyle:'crossRot', pointRadius:8, borderWidth:2.5, yAxisID:'y', order:-2 },
    { type:'scatter', label:'Exit Loss',   data:exitLosses,   backgroundColor:'rgba(246,70,93,0.9)',  borderColor:'#f6465d', pointStyle:'crossRot', pointRadius:8, borderWidth:2.5, yAxisID:'y', order:-2 },
  ];
}

// ── Update chart với window mới (khi pan/zoom) ────────────────────────────────
function _updateWindow(xMin, xMax) {
  if (!_btChartInstance || !_btAllCandles) return;
  const chart = _btChartInstance;

  // Lấy hidden states trước khi update
  const hiddenMap = {};
  chart.data.datasets.forEach((ds, i) => {
    hiddenMap[ds.label] = chart.getDatasetMeta(i).hidden ?? ds.hidden ?? false;
  });

  const slice = _sliceByRange(_btAllCandles, xMin, xMax);
  if (!slice.length) return;

  const slopeColor = chart._btSlopeColor;
  const MOM_COLOR  = chart._btMomColor;
  const HIST_COLORS = chart._btHistColors;
  const slopeBarColor = chart._btSlopeBarColor;

  const newDatasets = _buildDatasets(slice, _btAllTrades, slopeColor, MOM_COLOR, HIST_COLORS, slopeBarColor);

  // Cập nhật data từng dataset (giữ nguyên hidden state)
  newDatasets.forEach((nd, i) => {
    if (i < chart.data.datasets.length) {
      chart.data.datasets[i].data = nd.data;
      if (nd.backgroundColor && typeof nd.backgroundColor !== 'function') {
        chart.data.datasets[i].backgroundColor = nd.backgroundColor;
      }
      // Khôi phục hidden
      const wasHidden = hiddenMap[nd.label] ?? false;
      chart.data.datasets[i].hidden = wasHidden;
      chart.getDatasetMeta(i).hidden = wasHidden;
    }
  });

  chart.options.scales.x.min = xMin;
  chart.options.scales.x.max = xMax;
  chart.update('none');
}

// ── Trade popup ───────────────────────────────────────────────────────────────
function _showTradePopup(trade, clientX, clientY) {
  let popup = document.getElementById('btTradePopup');
  if (!popup) {
    popup = document.createElement('div');
    popup.id = 'btTradePopup';
    popup.style.cssText = 'position:fixed;z-index:9999;background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:12px 16px;font-size:12px;color:var(--text-primary);pointer-events:none;box-shadow:0 4px 20px rgba(0,0,0,0.6);min-width:210px;';
    document.body.appendChild(popup);
  }
  const pnlColor  = (trade.pnl??0)>=0 ? '#0ecb81' : '#f6465d';
  const sideColor = trade.side==='long' ? '#0ecb81' : '#f6465d';
  const sideIcon  = trade.side==='long' ? '▲' : '▼';
  popup.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="color:${sideColor};font-weight:bold;font-size:13px;">${sideIcon} ${trade.side.toUpperCase()}</span>
      <span style="color:${pnlColor};font-weight:bold;">${(trade.pnl??0)>=0?'+':''}${(trade.pnl??0).toFixed(2)} USDT</span>
    </div>
    <div style="display:grid;grid-template-columns:auto auto;gap:3px 12px;color:var(--text-secondary);">
      <span>Vào:</span><span style="color:var(--text-primary);">${trade.entry_time}</span>
      <span>Ra:</span><span style="color:var(--text-primary);">${trade.exit_time}</span>
      <span>Giá vào:</span><span style="color:var(--text-primary);">${(trade.entry_price??0).toFixed(4)}</span>
      <span>Giá ra:</span><span style="color:var(--text-primary);">${(trade.exit_price??0).toFixed(4)}</span>
      <span>PnL %:</span><span style="color:${pnlColor};">${(trade.pnl_pct??0)>=0?'+':''}${(trade.pnl_pct??0).toFixed(2)}%</span>
      <span>Giữ:</span><span style="color:var(--text-primary);">${trade.holding_candles} nến</span>
    </div>
    ${trade.exit_reason?`<div style="margin-top:8px;padding-top:8px;border-top:1px solid #2d3748;color:#888;font-size:11px;">${trade.exit_reason}</div>`:''}
  `;
  const vpW=window.innerWidth, vpH=window.innerHeight, pw=220, ph=170;
  let px=clientX+14, py=clientY-ph/2;
  if(px+pw>vpW) px=clientX-pw-14;
  if(py<4) py=4;
  if(py+ph>vpH) py=vpH-ph-4;
  popup.style.left=`${px}px`; popup.style.top=`${py}px`; popup.style.display='block';
}
function _hideTradePopup() { const p=document.getElementById('btTradePopup'); if(p) p.style.display='none'; }
function _highlightTradeRow(idx) {
  document.querySelectorAll('#btTradesBody tr.bt-highlight').forEach(r=>r.classList.remove('bt-highlight'));
  const rows=document.querySelectorAll('#btTradesBody tr[data-trade-idx]');
  if(rows[idx]) { rows[idx].classList.add('bt-highlight'); rows[idx].scrollIntoView({behavior:'smooth',block:'nearest'}); }
}

// ── Main render ───────────────────────────────────────────────────────────────
export async function renderBacktestChart(jobId) {
  let chartData;
  try {
    const r = await fetch(`/api/backtest/chart-data/${jobId}`);
    if (!r.ok) { console.warn('chart-data not available:', r.status); return; }
    chartData = await r.json();
  } catch (e) { console.error('fetch chart-data error:', e); return; }

  _btChartData  = chartData;
  _btAllCandles = chartData.candles;
  _btAllTrades  = chartData.trades;
  if (!_btAllCandles?.length) return;

  _btTfMs = _guessTfMs(_btAllCandles);

  const container = document.getElementById('btChartContainer');
  if (container) container.style.display = 'block';
  if (_btChartInstance) { _btChartInstance.destroy(); _btChartInstance = null; }

  const canvas = document.getElementById('btPriceChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // ── Helpers ───────────────────────────────────────────────────────────────
  function slopeColor(c) {
    if (!c.p0?.parsed || !c.p1?.parsed) return '#2196F3';
    const curr=c.p1.parsed.y, prev=c.p0.parsed.y;
    if (curr===prev) return '#FFEB3B';
    const p0idx=c.p0DataIndex, ds=c.chart.data.datasets[c.datasetIndex];
    const older=(p0idx>0&&ds.data[p0idx-1]?.y!=null)?ds.data[p0idx-1].y:prev;
    const sc=curr-prev, sp=prev-older;
    if (curr>prev) return sc>=sp?'#2196F3':'#4CAF50';
    return sc<=sp?'#f6465d':'#FF9800';
  }
  const MOM_COLOR   = {yellow:'#FFEB3B',blue:'#2196F3',green:'#4CAF50',orange:'#FF9800',red:'#f6465d',purple:'#9C27B0'};
  const HIST_COLORS = {above_grow:'#26A69A',above_fall:'#B2DFDB',below_grow:'#FFCDD2',below_fall:'#FF5252'};
  function slopeBarColor(arr,i) {
    if(i<1||arr[i]==null||arr[i-1]==null) return '#888';
    const curr=arr[i],prev=arr[i-1],older=i>=2&&arr[i-2]!=null?arr[i-2]:prev;
    if(curr===prev) return '#FFEB3B';
    const sc=curr-prev,sp=prev-older;
    if(curr>prev) return sc>=sp?'#2196F3':'#4CAF50';
    return sc<=sp?'#f6465d':'#FF9800';
  }

  // ── Initial window ────────────────────────────────────────────────────────
  const lastTs = _btAllCandles[_btAllCandles.length-1].x;
  const xMax   = lastTs + _btTfMs * 5;
  const xMin   = lastTs - _btTfMs * (_btDefaultCandles - 1);
  const initSlice = _sliceByRange(_btAllCandles, xMin, xMax);
  const datasets  = _buildDatasets(initSlice, _btAllTrades, slopeColor, MOM_COLOR, HIST_COLORS, slopeBarColor);

  // ── Scales ────────────────────────────────────────────────────────────────
  const chartScales = {
    x: {type:'time',time:{tooltipFormat:'yyyy-MM-dd HH:mm'},grid:{color:'rgba(0,0,0,0.1)'},ticks:{color:'#333'},min:xMin,max:xMax},
    y: {type:'linear',display:true,position:'right',stack:'main',stackWeight:3,grid:{color:'rgba(0,0,0,0.1)'},ticks:{color:'#333',callback:(v,i)=>i===0?'':v}},
    y_macd: {type:'linear',display:true,position:'right',stack:'main',stackWeight:1,grid:{color:'rgba(0,0,0,0.1)',drawOnChartArea:true},ticks:{color:'#333',callback:(v,i,t)=>i===t.length-1?'':v}},
    y_macd_slope: {type:'linear',display:true,position:'right',stack:'main',stackWeight:0.6,grid:{color:'rgba(0,0,0,0.08)',drawOnChartArea:true},ticks:{color:'#333',maxTicksLimit:3,callback:(v,i,t)=>i===t.length-1?'':v.toFixed(4)+'%'}},
    y_sig_slope:  {type:'linear',display:true,position:'left', stack:'main',stackWeight:0.6,grid:{drawOnChartArea:false},ticks:{color:'#2196F3',maxTicksLimit:3,callback:(v,i,t)=>i===t.length-1?'':v.toFixed(4)+'%'}},
    y_sma_slope:  {type:'linear',display:false,position:'left',stack:'main',stackWeight:3},
  };

  // ── Plugins ───────────────────────────────────────────────────────────────
  const crosshairPlugin = {
    id:'btCrosshair', _mx:null, _my:null,
    afterEvent(chart,args) {
      const e=args.event;
      if(e.type==='mousemove'){this._mx=e.x;this._my=e.y;chart.draw();}
      else if(e.type==='mouseout'){this._mx=null;this._my=null;chart.draw();}
    },
    afterDraw(chart) {
      const mx=this._mx,my=this._my;
      if(mx==null||my==null) return;
      const {left,right,top,bottom}=chart.chartArea;
      if(mx<left||mx>right||my<top||my>bottom) return;
      const c=chart.ctx; c.save();
      c.beginPath();c.setLineDash([4,4]);c.strokeStyle='rgba(150,150,150,0.7)';c.lineWidth=1;
      c.moveTo(mx,top);c.lineTo(mx,bottom);c.stroke();
      c.beginPath();c.moveTo(left,my);c.lineTo(right,my);c.stroke();c.setLineDash([]);
      let yAxis=chart.scales['y'];
      if(chart.scales['y_macd']&&my>=chart.scales['y_macd'].top&&my<=chart.scales['y_macd'].bottom) yAxis=chart.scales['y_macd'];
      const price=yAxis.getValueForPixel(my);
      if(price==null){c.restore();return;}
      const pt=price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:price<10?4:2});
      c.font='bold 11px Inter,sans-serif';
      const tw=c.measureText(pt).width,bw=tw+10,bh=20,bx=right,by=my-bh/2;
      c.fillStyle='rgba(50,50,60,0.92)';
      c.beginPath();c.moveTo(bx-6,my);c.lineTo(bx,by);c.lineTo(bx+bw,by);c.lineTo(bx+bw,by+bh);c.lineTo(bx,by+bh);c.closePath();c.fill();
      c.fillStyle='#fff';c.textAlign='center';c.textBaseline='middle';c.fillText(pt,bx+bw/2,my);
      const ts=chart.scales['x'].getValueForPixel(mx);
      if(ts!=null){
        const d=new Date(ts);
        const ts2=d.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
        const ttw=c.measureText(ts2).width+12,tth=20,ttx=mx-ttw/2,tty=bottom+2;
        c.fillStyle='rgba(50,50,60,0.92)';c.fillRect(ttx,tty,ttw,tth);
        c.fillStyle='#fff';c.textAlign='center';c.textBaseline='middle';c.fillText(ts2,mx,tty+tth/2);
      }
      c.restore();
    }
  };

  const splitPanePlugin = {
    id:'btSplitPane',
    beforeDraw(chart) {
      const c=chart.ctx;
      ['y_macd','y_macd_slope'].forEach(key=>{
        const ax=chart.scales[key]; if(!ax) return;
        c.save();
        c.fillStyle=key==='y_macd'?'rgba(0,0,0,0.15)':'rgba(0,0,0,0.10)';
        c.fillRect(chart.chartArea.left,ax.top,chart.chartArea.right-chart.chartArea.left,ax.bottom-ax.top);
        c.beginPath();c.moveTo(chart.chartArea.left,ax.top);c.lineTo(chart.chartArea.right,ax.top);
        c.lineWidth=key==='y_macd'?2:1;c.strokeStyle=key==='y_macd'?'#444':'#555';c.stroke();
        if(key==='y_macd_slope'&&!isNaN(ax.getPixelForValue(0))){
          const zy=ax.getPixelForValue(0);
          c.beginPath();c.setLineDash([3,3]);c.moveTo(chart.chartArea.left,zy);c.lineTo(chart.chartArea.right,zy);
          c.lineWidth=1;c.strokeStyle='rgba(150,150,150,0.5)';c.stroke();c.setLineDash([]);
        }
        c.restore();
      });
    }
  };

  const bgPlugin = {
    id:'btBg',
    beforeDraw(chart){
      const c=chart.canvas.getContext('2d');c.save();c.globalCompositeOperation='destination-over';
      c.fillStyle='white';c.fillRect(0,0,chart.width,chart.height);c.restore();
    }
  };

  const tradeLinePlugin = {
    id:'btTradeLines',
    afterDraw(chart) {
      if(!_btTradeLineVis) return;
      const xS=chart.scales['x'],yS=chart.scales['y'];
      if(!xS||!yS) return;
      const {left,right,top,bottom}=chart.chartArea;
      const c=chart.ctx; c.save();
      c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
      _btAllTrades.forEach(t=>{
        const x1=xS.getPixelForValue(t.entry_ts),x2=xS.getPixelForValue(t.exit_ts);
        const y1=yS.getPixelForValue(t.entry_price),y2=yS.getPixelForValue(t.exit_price);
        if(x1==null||x2==null||y1==null||y2==null) return;
        if(x2<left||x1>right) return;
        const win=(t.pnl??0)>=0;
        c.beginPath();c.setLineDash([3,3]);
        c.strokeStyle=win?'rgba(14,203,129,0.55)':'rgba(246,70,93,0.55)';
        c.lineWidth=1.2;c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke();c.setLineDash([]);
      });
      c.restore();
    }
  };

  // ── Tooltip ───────────────────────────────────────────────────────────────
  const tooltipCallbacks = {
    label(context) {
      const label=context.dataset.label||'';
      if(label==='Giá'){const r=context.raw;if(r?.c!==undefined)return `Giá: O:${r.o?.toFixed(2)} H:${r.h?.toFixed(2)} L:${r.l?.toFixed(2)} C:${r.c?.toFixed(2)}`;return label;}
      if(['Long Entry','Short Entry','Exit Win','Exit Loss'].includes(label)) return null;
      if(context.parsed.y==null||isNaN(context.parsed.y)) return null;
      let lbl=label+': '+Number(context.parsed.y).toFixed(4);
      if(label==='TVT-MA'){const s=context.raw?.slope_pct;if(s!=null)lbl+=` (Dốc: ${s>0?'+':''}${s.toFixed(4)}%)`;}
      if(label==='MACD Signal'){const s=context.raw?.slope_pct;if(s!=null)lbl+=` (Dốc: ${s>0?'+':''}${s.toFixed(6)}%)`;}
      return lbl;
    }
  };

  // ── Legend ────────────────────────────────────────────────────────────────
  const LABEL_COLORS = {
    'Giá':'#888','TVT-Trend':'#2196F3','TVT-MA':'#2196F3','TVT-MA-Cross':'#FFEB3B','TVT-MA-Cross-N':'#FF9800',
    'TVT-MA Slope':'#2196F3','TVT-MA Accel':'#9C27B0','MACD Hist':'#26A69A','MACD':'#2196F3',
    'MACD-Cross':'#FFEB3B','MACD Signal':'#FF9800','MACD-Signal-Cross':'#FF9800',
    'MACD Slope':'#2196F3','Signal Slope':'#2196F3','Signal Accel':'#9C27B0',
    'Long Entry':'#0ecb81','Short Entry':'#f6465d','Exit Win':'#0ecb81','Exit Loss':'#f6465d','Trade Lines':'#888',
  };
  function renderLegend() {
    const el=document.getElementById('btChartLegend');
    if(!el||!_btChartInstance) return;
    const chart=_btChartInstance;
    let html=`<div style="font-size:11px;color:var(--text-secondary);padding:2px 4px 6px;border-bottom:1px solid var(--border);margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;"><span>Chỉ báo</span><span onclick="btShowAllLegend()" style="cursor:pointer;color:#f6465d;font-size:11px;padding:2px 4px;">Hiện tất cả</span></div>`;
    chart.data.datasets.forEach((ds,idx)=>{
      const meta=chart.getDatasetMeta(idx);
      const isHidden=meta.hidden??ds.hidden??false;
      const color=LABEL_COLORS[ds.label]||'#888';
      html+=`<div onclick="btToggleLegend(${idx})" style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:${isHidden?'#666':'var(--text-primary)'};text-decoration:${isHidden?'line-through':'none'};padding:4px;"><div style="width:12px;height:12px;border-radius:2px;background:${color};border:1px solid rgba(255,255,255,0.2);opacity:${isHidden?0.3:1};flex-shrink:0;"></div><span>${ds.label}</span></div>`;
    });
    const tlH=!_btTradeLineVis;
    html+=`<div onclick="btToggleTradeLine()" style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:${tlH?'#666':'var(--text-primary)'};text-decoration:${tlH?'line-through':'none'};padding:4px;"><div style="width:12px;height:12px;border-radius:2px;background:#888;border:1px solid rgba(255,255,255,0.2);opacity:${tlH?0.3:1};flex-shrink:0;"></div><span>Trade Lines</span></div>`;
    el.innerHTML=html;
  }
  _btRenderLegendFn = renderLegend;

  window.btToggleLegend = function(idx) {
    if(!_btChartInstance) return;
    const chart=_btChartInstance, meta=chart.getDatasetMeta(idx), ds=chart.data.datasets[idx];
    const isH=meta.hidden??ds.hidden??false; meta.hidden=!isH; ds.hidden=!isH;
    chart.update('none'); renderLegend();
  };
  window.btShowAllLegend = function() {
    if(!_btChartInstance) return;
    _btChartInstance.data.datasets.forEach((ds,i)=>{ds.hidden=false;_btChartInstance.getDatasetMeta(i).hidden=false;});
    _btTradeLineVis=true; _btChartInstance.update('none'); renderLegend();
  };
  window.btToggleTradeLine = function() {
    _btTradeLineVis=!_btTradeLineVis;
    if(_btChartInstance) _btChartInstance.update('none'); renderLegend();
  };
  window.btToggleLegendMenu = function() {
    const menu=document.getElementById('btChartLegend');
    if(!menu) return;
    if(menu.style.display==='none'||!menu.style.display){renderLegend();menu.style.display='flex';}
    else menu.style.display='none';
  };

  // ── Create chart ──────────────────────────────────────────────────────────
  if(Chart.defaults?.elements?.candlestick){
    Chart.defaults.elements.candlestick.backgroundColors={up:'rgba(0,0,0,0)',down:'#000',unchanged:'#000'};
    Chart.defaults.elements.candlestick.borderColors='#000';
  }

  _btChartInstance = new Chart(ctx, {
    type:'candlestick',
    data:{datasets},
    options:{
      responsive:true, maintainAspectRatio:false, animation:false,
      scales:chartScales,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{callbacks:tooltipCallbacks},
        zoom:{
          pan:{enabled:true,mode:'x',
            onPanComplete({chart}){
              _updateWindow(chart.scales.x.min, chart.scales.x.max);
            }
          },
          zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:'x',
            onZoomComplete({chart}){
              _updateWindow(chart.scales.x.min, chart.scales.x.max);
            }
          },
        },
      },
      onClick(event,elements){
        if(!elements.length){_hideTradePopup();return;}
        const el=elements[0], ds=_btChartInstance.data.datasets[el.datasetIndex], pt=ds.data[el.index];
        if(pt?._idx!==undefined){
          _showTradePopup(_btAllTrades[pt._idx],event.native.clientX,event.native.clientY);
          _highlightTradeRow(pt._idx);
        }
      },
    },
    plugins:[splitPanePlugin,bgPlugin,crosshairPlugin,tradeLinePlugin],
  });

  // Lưu helpers vào chart instance để _updateWindow dùng được
  _btChartInstance._btSlopeColor   = slopeColor;
  _btChartInstance._btMomColor     = MOM_COLOR;
  _btChartInstance._btHistColors   = HIST_COLORS;
  _btChartInstance._btSlopeBarColor = slopeBarColor;

  setTimeout(renderLegend, 50);
  document.addEventListener('click', e=>{
    if(!e.target.closest('#btPriceChart')&&!e.target.closest('#btTradePopup')) _hideTradePopup();
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _guessTfMs(data) {
  if(data.length<2) return 300000;
  const diffs=[];
  for(let i=1;i<Math.min(10,data.length);i++) diffs.push(data[i].x-data[i-1].x);
  diffs.sort((a,b)=>a-b);
  return diffs[Math.floor(diffs.length/2)]||300000;
}

export function scrollChartToTrade(tradeIdx) {
  if(!_btChartData||!_btChartInstance) return;
  const trade=_btAllTrades[tradeIdx];
  if(!trade) return;
  const span=Math.max(trade.exit_ts-trade.entry_ts, _btTfMs*20);
  const pad=span*0.3;
  const xMin=trade.entry_ts-pad, xMax=trade.exit_ts+pad;
  _updateWindow(xMin, xMax);
  _highlightTradeRow(tradeIdx);
}

export function destroyBacktestChart() {
  if(_btChartInstance){_btChartInstance.destroy();_btChartInstance=null;}
  _btChartData=null; _btAllCandles=null; _btAllTrades=null;
  _hideTradePopup();
}
