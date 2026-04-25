import sys, re

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the type: 'line' and data block
pattern = r"type:\s*'line',\s*data:\s*\{\s*labels,\s*datasets:\s*\[[\s\S]*?tension:\s*0\.3,\s*fill:\s*false,\s*},\s*\],\s*\},"

new_data = '''type: 'candlestick',
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

content, count = re.subn(pattern, new_data, content, count=1)
if count > 0:
    print("Block replaced!")
else:
    print("Block NOT found!")

# Replace x scale
pattern2 = r"scales:\s*\{\s*x:\s*\{\s*grid:\s*\{\s*color:\s*'rgba\(255,255,255,0\.04\)'\s*\},"
new_x = '''scales: {
        x: {
          type: 'time',
          time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
          grid: { color: 'rgba(255,255,255,0.04)' },'''

content, count2 = re.subn(pattern2, new_x, content, count=1)
if count2 > 0:
    print("X-axis replaced!")

# Replace the tooltip callback because ctx.raw is now an object for candlesticks
pattern3 = r"label:\s*ctx\s*=>\s*\$\{ctx\.dataset\.label\}:\s*\$\$\{ctx\.raw\?\.toFixed\(4\)\s*\|\|\s*'--'\},"
new_tooltip = '''label: ctx => {
              if (ctx.dataset.type === 'candlestick' || ctx.dataset.label === 'Nến Nhật') {
                const c = ctx.raw;
                if (!c) return '--';
                return O:  | H:  | L:  | C: ;
              }
              return ${ctx.dataset.label}: {ctx.raw?.y !== undefined ? ctx.raw.y.toFixed(4) : (ctx.raw?.toFixed ? ctx.raw.toFixed(4) : '--')};
            },'''

content, count3 = re.subn(pattern3, new_tooltip, content, count=1)
if count3 > 0:
    print("Tooltip replaced!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
