import sys, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

for fname, label in [
    ("data/backtest/backtest_10_BTCUSDT_5m_20260401_20260430.xlsx", "V3 - Thang 4/2026"),
    ("data/backtest/backtest_10_BTCUSDT_5m_20260101_20260430.xlsx", "V3 - 4 thang (Jan-Apr 2026)"),
]:
    wb = openpyxl.load_workbook(fname)
    ws1 = wb["Tong hop"]
    data = {r[0]: r[1] for r in ws1.iter_rows(values_only=True) if r[0] and r[1] is not None}
    ws2 = wb["Chi tiet lenh"]
    trades = [r for r in ws2.iter_rows(min_row=2, values_only=True) if r[0]]

    sys.stdout.write(f"\n{'='*65}\n{label}\n{'='*65}\n")
    keys = ["Tong so lenh","Lenh thang","Lenh thua","Ti le thang (%)","Tong Pnl (USDT)",
            "Tong loi nhuan (%)","Von cuoi (USDT)","Max Drawdown (%)","Profit Factor",
            "TB lenh thang (USDT)","TB lenh thua (USDT)","Lenh thang lon nhat",
            "Lenh thua lon nhat","TB thoi gian giu (nen)","Sharpe Ratio"]
    for k in keys:
        sys.stdout.write(f"  {k:<32} {data.get(k,'N/A')}\n")

    sys.stdout.write(f"\n  Chi tiet ({len(trades)} lenh):\n")
    for t in trades:
        pnl = t[8] or 0
        mark = "+" if pnl > 0 else "-"
        sys.stdout.write(f"  {mark} #{t[0]:>2} {t[1]}->{t[2]} {str(t[4]):<6} entry={t[5]:.2f} exit={t[6]:.2f} pnl={pnl:.4f}({t[9]:+.2f}%) hold={t[11]}n\n")
