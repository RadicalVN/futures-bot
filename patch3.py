import sys, re

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

pattern3 = r"label:\s*ctx\s*=>\s*\$\{ctx\.dataset\.label\}:\s*\$\$\{ctx\.raw\?\.toFixed\(4\)\s*\|\|\s*'--'\},"
new_tooltip = '''label: ctx => {
              if (ctx.dataset.type === 'candlestick' || ctx.dataset.label === 'Nến Nhật') {
                const c = ctx.raw;
                if (!c) return '--';
                return O:  | H:  | L:  | C: ;
              }
              return ${ctx.dataset.label}: {ctx.raw?.y !== undefined ? ctx.raw.y.toFixed(4) : (ctx.raw?.toFixed ? ctx.raw.toFixed(4) : '--')};
            },'''

content, count3 = re.subn(pattern3, new_tooltip, content)
if count3 > 0:
    print("Tooltip replaced!")
else:
    print("Tooltip NOT found!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
