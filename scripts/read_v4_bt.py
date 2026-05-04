import sys, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

f = "data/backtest/backtest_11_BTCUSDT_5m_20260101_20260501.xlsx"
wb = openpyxl.load_workbook(f)
ws1 = wb["Tong hop"]
data = {r[0]: r[1] for r in ws1.iter_rows(values_only=True) if r[0] and r[1] is not None}
ws2 = wb["Chi tiet lenh"]
trades = [r for r in ws2.iter_rows(min_row=2, values_only=True) if r[0]]

sys.stdout.write("=== TONG HOP ===\n")
for k in ["Tong so lenh","Lenh thang","Lenh thua","Ti le thang (%)","Tong Pnl (USDT)",
          "Tong loi nhuan (%)","Von cuoi (USDT)","Max Drawdown (%)","Profit Factor",
          "TB lenh thang (USDT)","TB lenh thua (USDT)","TB thoi gian giu (nen)","Sharpe Ratio"]:
    sys.stdout.write(f"  {k:<32} {data.get(k,'N/A')}\n")

sys.stdout.write(f"\n=== LENH GIU LAU (>100 nen) ===\n")
long_holds = [(t[0], t[1], t[2], t[4], t[5], t[6], t[8], t[9], t[11]) for t in trades if (t[11] or 0) > 100]
for t in long_holds:
    sys.stdout.write(f"  #{t[0]:>2} {t[1]}->{t[2]} {t[3]:<6} entry={t[4]:.2f} exit={t[5]:.2f} pnl={t[6]:.4f}({t[7]:+.2f}%) hold={t[8]}n\n")

sys.stdout.write(f"\n=== TAT CA LENH ===\n")
for t in trades:
    pnl = t[8] or 0
    mark = "+" if pnl > 0 else "-"
    sys.stdout.write(f"  {mark} #{t[0]:>2} {t[1]}->{t[2]} {str(t[4]):<6} entry={t[5]:.2f} exit={t[6]:.2f} pnl={pnl:.4f}({t[9]:+.2f}%) hold={t[11]}n\n")
