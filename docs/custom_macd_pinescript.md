# Custom MACD - TuanTV1008 - Pine Script Source

## Mô tả
MACD tùy chỉnh với Signal Length dài (mặc định 500) và hệ thống màu sắc Momentum giống Custom SMA.

## Tham số
| Param | Default | Mô tả |
|-------|---------|-------|
| `fast_length` | 12 | Chu kỳ MA nhanh |
| `slow_length` | 26 | Chu kỳ MA chậm |
| `src` | close | Nguồn giá |
| `signal_length` | 500 | Chu kỳ làm mượt Signal (rất dài → Signal mượt hơn chuẩn) |
| `sma_source` | EMA | Loại MA cho Oscillator (SMA/EMA) |
| `sma_signal` | EMA | Loại MA cho Signal Line (SMA/EMA) |

## Màu sắc Histogram
- Above Grow: `#26A69A` (xanh ngọc đậm)
- Above Fall: `#B2DFDB` (xanh ngọc nhạt)
- Below Grow: `#FFCDD2` (đỏ nhạt)
- Below Fall: `#FF5252` (đỏ đậm)

## Hệ thống Momentum (giống Custom SMA)
Áp dụng cho cả MACD line và Signal line:
- `yellow` — Giữ nguyên xu hướng
- `blue` — Tăng độ dốc lên
- `orange` — Giảm/Hãm độ dốc xuống
- `purple` — Đảo chiều
- `red` — Tăng độ dốc xuống
- `green` — Giảm/Hãm độ dốc lên

## Pine Script gốc

```pine
//@version=5
indicator(title="MACD-TuanTV1008", shorttitle="MACD-TuanTV1008", timeframe="", timeframe_gaps=true)

fast_length = input(title="Fast Length", defval=12)
slow_length = input(title="Slow Length", defval=26)
src = input(title="Source", defval=close)
signal_length = input.int(title="Signal Smoothing", minval=1, maxval=501, defval=500)
sma_source = input.string(title="Oscillator MA Type", defval="EMA", options=["SMA", "EMA"])
sma_signal = input.string(title="Signal Line MA Type", defval="EMA", options=["SMA", "EMA"])

col_macd    = input(#2962FF, "MACD Line  ", group="Color Settings", inline="MACD")
col_signal  = input(#FF6D00, "Signal Line  ", group="Color Settings", inline="Signal")
col_grow_above = input(#26A69A, "Above   Grow", group="Histogram", inline="Above")
col_fall_above = input(#B2DFDB, "Fall",         group="Histogram", inline="Above")
col_grow_below = input(#FFCDD2, "Below Grow",   group="Histogram", inline="Below")
col_fall_below = input(#FF5252, "Fall",          group="Histogram", inline="Below")

fast_ma = sma_source == "SMA" ? ta.sma(src, fast_length) : ta.ema(src, fast_length)
slow_ma = sma_source == "SMA" ? ta.sma(src, slow_length) : ta.ema(src, slow_length)
macd    = fast_ma - slow_ma
signal  = sma_signal == "SMA" ? ta.sma(macd, signal_length) : ta.ema(macd, signal_length)
hist    = macd - signal

// Hàm tính Momentum (giống Custom SMA)
sma21(sma2, sma1)     => sma2 - sma1
sma10(sma1, sma0)     => sma1 - sma0
sma0Hope(sma2, sma1)  => 2*sma1 - sma2
trend(sma2, sma1, sma0) => sma0 - sma0Hope(sma2, sma1)

function(sma2, sma1, sma0) =>
    if trend(sma2, sma1, sma0) == 0
        color.yellow
    else if (trend(sma2, sma1, sma0) > 0)
        if sma21(sma2, sma1) > 0
            if sma10(sma1, sma0) > 0
                color.orange
            else
                color.purple
        else
            color.blue
    else
        if sma21(sma2, sma1) > 0
            color.red
        else
            if sma10(sma1, sma0) < 0
                color.green
            else
                color.purple

// Plots
plot(macd,   title="MACD",    color=col_macd)
plot(macd,   title="MACD1",   color=function(macd[2], macd[1], macd[0]),   style=plot.style_cross, linewidth=2)
plot(signal, title="Signal",  color=col_signal)
plot(signal, title="Signal1", color=function(signal[2], signal[1], signal[0]), style=plot.style_cross, linewidth=2)
```

## Điểm khác biệt so với MACD chuẩn
1. **Signal Length = 500** (chuẩn = 9) → Signal line cực mượt, ít nhiễu
2. **Histogram 4 màu** theo chiều và vị trí (above/below zero + grow/fall)
3. **Momentum cross markers** trên cả MACD line và Signal line
