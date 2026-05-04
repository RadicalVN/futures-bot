import sys, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

files = {
    "V1 (bb=50, no trend filter)": "data/backtest/backtest_7_BTCUSDT_5m_20260401_20260430.xlsx",
    "V2 (bb=150, trend filter)":   "data/backtest/backtest_9_BTCUSDT_5m_20260401_20260430.xlsx",
}

for label, f in files.items():
    wb = openpyxl.load_workbook(f)
    ws1 = wb["Tong hop"]
    data = {r[0]: r[1] for r in ws1.iter_rows(values_only=True) if r[0] and r[1] is not None}
    ws2 = wb["Chi tiet lenh"]
    trades = [r for r in ws2.iter_rows(min_row=2, values_only=True) if r[0]]

    sys.stdout.write(f"\n{'='*60}\n{label}\n{'='*60}\n")
    keys = ["Tong so lenh","Lenh thang","Lenh thua","Ti le thang (%)","Tong Pnl (USDT)",
            "Tong loi nhuan (%)","Von cuoi (USDT)","Max Drawdown (%)","Profit Factor",
            "TB lenh thang (USDT)","TB lenh thua (USDT)","Lenh thang lon nhat",
            "Lenh thua lon nhat","TB thoi gian giu (nen)","Sharpe Ratio"]
    for k in keys:
        v = data.get(k, "N/A")
        sys.stdout.write(f"  {k:<32} {v}\n")

    sys.stdout.write(f"\n  Chi tiet lenh ({len(trades)} lenh):\n")
    for t in trades:
        mark = "+" if (t[8] or 0) > 0 else "-"
        sys.stdout.write(f"  {mark} #{t[0]:>2} {t[1]}->{t[2]} {str(t[4]):<6} entry={t[5]:.2f} exit={t[6]:.2f} pnl={t[8]:.4f}({t[9]:+.2f}%) hold={t[11]}n\n")
