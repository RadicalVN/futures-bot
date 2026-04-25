import sys

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_block = '''  state.priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Giá',
          data: data.map(d => d.close),
          borderColor: '#F0B90B',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'MA Fast',
          data: data.map(d => d.ma_fast),
          borderColor: '#4183f4',
          borderWidth: 1.5,
          borderDash: [],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'MA Slow',
          data: data.map(d => d.ma_slow),
          borderColor: '#f7931a',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
      ],
    },'''

new_block = '''  state.priceChart = new Chart(ctx, {
    type: 'candlestick',
    data: {
      datasets: [
        {
          label: 'Nến Nhật',
          data: data.map(d => ({
            x: new Date(d.timestamp).getTime(),
            o: d.open,
            h: d.high,
            l: d.low,
            c: d.close
          })),
          color: {
            up: 'rgba(14,203,129,1)',
            down: 'rgba(246,70,93,1)',
            unchanged: '#999',
          },
          borderColor: {
            up: 'rgba(14,203,129,1)',
            down: 'rgba(246,70,93,1)',
            unchanged: '#999',
          }
        },
        {
          label: 'MA Fast',
          type: 'line',
          data: data.map(d => ({x: new Date(d.timestamp).getTime(), y: d.ma_fast})),
          borderColor: '#4183f4',
          borderWidth: 1.5,
          borderDash: [],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: 'MA Slow',
          type: 'line',
          data: data.map(d => ({x: new Date(d.timestamp).getTime(), y: d.ma_slow})),
          borderColor: '#f7931a',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
      ],
    },'''

old_options = '''      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#525f74', maxTicksLimit: 10, font: { size: 10 } },
        },'''

new_options = '''      scales: {
        x: {
          type: 'time',
          time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#525f74', maxTicksLimit: 10, font: { size: 10 } },
        },'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("Block replaced!")
else:
    print("Block NOT found!")

if old_options in content:
    content = content.replace(old_options, new_options)
    print("Options replaced!")
else:
    print("Options NOT found!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
