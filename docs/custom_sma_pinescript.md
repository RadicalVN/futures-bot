# Custom SMA Trend - TradingView Pine Script Source

```pine
// This source code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © tuantv1008
//@version=4
study(shorttitle="TVT-MA", title="TVT-MA", overlay=true, resolution="")

// Chỉ báo SMA Trend cải tiến
lenFast = 1
lenSlow = 5
lenC = input(200, title="Length of Sma", type=input.integer, minval=1)

co(sFast, sSlow, lFast, lSlow, lC)=>
    fastC = sma(sFast, lFast)
    slowC = sma(sSlow, lSlow)
    cC = fastC + slowC
    sma(cC, lC)

closeC = co(close, close, lenFast, lenSlow, lenC)
//              PLOTTING: 
c5 = closeC/2
f1   = 1
f2 = 10
//
up =c5 - (f1 * log(f2))
dn = c5 + (f1 * log(f2))
//

factor = input(title="Factor", defval=0.05, minval=0.01, maxval=5, step=0.01, type=input.float)

hb = 0.00 ,hb := nz(hb[1])
hl = 0.000, hl := nz(hl[1])

lb = 0.00 ,lb := nz(lb[1])
l1 = 0.000,l1 := nz(l1[1])

c = 0
c := nz(c[1]) + 1

trendx = 0,trendx := nz(trendx[1]),n = dn,x =up


if barstate.isfirst
    c := 0
    lb := n
    hb := x                      
    l1 := c5  
    hl := c5
    hl
if c == 1
    if x >= hb[1]
        hb := x
        hl := c5
        trendx := 1  
        trendx
    else
        lb := n
        l1 := c5 
        trendx := -1 
        trendx

if c > 1

    if trendx[1] > 0  
        hl := max(hl[1], c5)
        if x >= hb[1] 
            hb := x
            hb
        else

            
            if n < hb[1] - hb[1] * factor 
                lb := n
                l1 := c5

                trendx := -1  
                trendx
    else

       
        l1 := min(l1[1], c5 )

        if n <= lb[1] 
            lb := n 
            lb
        else

           
            if x > lb[1] + lb[1] * factor
                hb := x 
                hl := c5

                trendx := 1  
                trendx

v = trendx == 1 ? hb : trendx == -1 ? lb : na
plot(v, color=trendx == 1 ? color.blue : color.yellow, style=plot.style_circles, linewidth=1, title="trend", transp=0, join=true)

//

long = trendx == 1 and trendx[1] == -1 
short = trendx == -1 and trendx[1] == 1 
//
last_long = 0.0
last_short = 0.0
last_long := long ? time : nz(last_long[1])
last_short := short ? time : nz(last_short[1])


// Đoạn source cải tiến từ BB (bollinger Bands)
// Biến chiều dài hay số phiên (thanh). minval là giá trị nhỏ nhất mà biến length nhận được
length = input(50, minval=1)
// Nguồn có nghĩa là giá trị lấy tham chiếu là gì
src = input(close, title="Source")
// Đây là hệ số độ lệch chuẩn
mult = input(2.0, minval=0.001, maxval=50, title="StdDev")
// basic là tổng các giá trị chia cho số các giá trị. VD: nguồn là close (giá đóng cửa), length = 20 => basic = (Tổng giá đóng cửa 20 phiên)/ 20
// Đây cũng chính là chỉ báo MA (Moving Average) là đường trung bình động. VD length = 20 ta có MA20
basis = sma(src, length)
// stdev là hàm tính độ lệch chuẩn. 
dev = mult * stdev(src, length)
// Khoảng cách từ MA đến đường chặn trên
upper = basis + dev
// Khoảng cách từ MA đến đường chặn dưới
lower = basis - dev
// Giá trị "bù lại"
offset = input(0, "Offset", type = input.integer, minval = -500, maxval = 500)
sma21(sma2, sma1) => sma2 - sma1
sma10(sma1, sma0) => sma1 - sma0
sma0Hope(sma2, sma1) => 2*sma1 - sma2
trend(sma2, sma1, sma0) => sma0 - sma0Hope(sma2, sma1)

// Hàm function xét xu hướng đang dốc lên hay dốc xuống và giữ nguyên xu hướng đó hay tăng thêm / giảm đi
function(sma2, sma1, sma0) =>
    if trend(sma2, sma1, sma0) == 0
        color = color.yellow // Giữ nguyên xu hướng dốc xuống / dốc lên
    else if (trend(sma2, sma1, sma0) > 0)
        if sma21(sma2, sma1) > 0
            if sma10(sma1, sma0) > 0
                color = color.orange // Giảm / Hãm độ dốc xuống
            else
                color = color.purple // Đảo chiều
        else
            color = color.blue // Tăng độ dốc lên
    else
        if sma21(sma2, sma1) > 0
            color = color.red // Tăng độ dốc xuống
        else
            if sma10(sma1, sma0) < 0
                color = color.green // Giảm / Hãm độ dốc lên
            else
                color = color.purple // Đảo chiều

plot(basis, "SMA",color= basis[0]==basis[1] ? color.yellow: basis[0]>basis[1] ? color.blue : color.red, linewidth = 2, offset = offset)
plot(basis[0], "SMA-1", function(basis[2],basis[1],basis[0]), style=plot.style_cross, linewidth = 3, offset = offset)
```
