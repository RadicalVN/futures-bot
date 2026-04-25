import sys, re

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r"callbacks:\s*\{\s*label:\s*ctx\s*=>\s*\$\{ctx\.dataset\.label\}:\s*\$\$\{ctx\.raw\?\.toFixed\(4\)\s*\|\|\s*'--'\},\s*\}"
new_cb = '''callbacks: {
            label: ctx => {
              if (ctx.dataset.type === 'candlestick' || ctx.dataset.label === 'Nến Nhật') {
                const c = ctx.raw;
                if (!c) return '--';
                return O:  | H:  | L:  | C: ;
              }
              return ${ctx.dataset.label}: {ctx.raw?.y !== undefined ? ctx.raw.y.toFixed(4) : (ctx.raw?.toFixed ? ctx.raw.toFixed(4) : '--')};
            }
          }'''

content, count = re.subn(pattern, new_cb, content)
if count > 0:
    print("Tooltip replaced!")
else:
    print("Tooltip NOT found!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
