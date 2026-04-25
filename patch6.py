import sys, re

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r"tooltip:\s*\{[\s\S]*?callbacks:\s*\{[\s\S]*?\},?\s*\}"
new_tooltip = '''tooltip: {
          backgroundColor: '#161a22',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          titleColor: '#e8eaf0',
          bodyColor: '#8892a4',
          callbacks: {
            label: ctx => {
              if (ctx.dataset.type === 'candlestick' || ctx.dataset.label === 'Nến Nhật') {
                const c = ctx.raw;
                if (!c || typeof c !== 'object') return '--';
                return O:  | H:  | L:  | C: ;
              }
              return ${ctx.dataset.label}: {ctx.raw?.y !== undefined ? ctx.raw.y.toFixed(4) : (ctx.raw?.toFixed ? ctx.raw.toFixed(4) : '--')};
            }
          }
        }'''

content, count = re.subn(pattern, new_tooltip, content, count=1)
if count > 0:
    print("Tooltip replaced!")
else:
    print("Tooltip NOT found!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
