import sys

file_path = r'E:\tuantv1008\sources\trading-service\src\dashboard\static\app.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_tooltip = "label: ctx => ${ctx.dataset.label}: {ctx.raw?.toFixed(4) || '--'},"
new_tooltip = '''label: ctx => {
              if (ctx.dataset.type === 'candlestick' || ctx.dataset.label === 'Nến Nhật') {
                const c = ctx.raw;
                if (!c) return '--';
                return O:  | H:  | L:  | C: ;
              }
              return ${ctx.dataset.label}: {ctx.raw?.y !== undefined ? ctx.raw.y.toFixed(4) : (ctx.raw?.toFixed ? ctx.raw.toFixed(4) : '--')};
            },'''

if old_tooltip in content:
    content = content.replace(old_tooltip, new_tooltip)
    print("Tooltip replaced successfully!")
else:
    print("Tooltip NOT found!")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
