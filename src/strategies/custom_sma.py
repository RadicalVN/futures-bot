import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal

class CustomSMAStrategy(BaseStrategy):
    """
    Chiến thuật dựa trên chỉ báo SMA Custom (ittuantruong) của user
    Bắt xu hướng bằng hệ thống băng thông (up/dn) và hệ số factor
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "custom_sma"
        self.fast_length = self.get_param("fast_length", 1)
        self.slow_length = self.get_param("slow_length", 5)
        self.len_c = self.get_param("len_c", 20)
        self.factor = self.get_param("factor", 0.05)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        if len(df) < max(self.slow_length, self.len_c) * 2:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Not enough data")

        close = df['close']

        # co(sFast, sSlow, lFast, lSlow, lC)
        fastC = close.rolling(self.fast_length).mean()
        slowC = close.rolling(self.slow_length).mean()
        cC = fastC + slowC
        closeC = cC.rolling(self.len_c).mean()

        c5 = closeC / 2
        f1 = 1
        f2 = 10
        # log in pine script is natural log (ln)
        log_f2 = np.log(f2)
        
        up = c5 - (f1 * log_f2)
        dn = c5 + (f1 * log_f2)

        # Tính toán trendx (mô phỏng lại vòng lặp state machine của Pine Script)
        n = dn.to_numpy()
        x = up.to_numpy()
        c5_arr = c5.to_numpy()
        
        trendx = np.zeros(len(df))
        hb = np.zeros(len(df))
        lb = np.zeros(len(df))
        hl = np.zeros(len(df))
        l1 = np.zeros(len(df))

        # Tìm index đầu tiên không bị NaN
        first_valid_idx = np.where(~np.isnan(c5_arr))[0]
        if len(first_valid_idx) == 0:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Not enough valid data")
        
        start_idx = first_valid_idx[0]
        
        # barstate.isfirst equivalent
        c_count = 0
        
        for i in range(start_idx, len(df)):
            curr_n = n[i]
            curr_x = x[i]
            curr_c5 = c5_arr[i]
            
            if c_count == 0:
                lb[i] = curr_n
                hb[i] = curr_x
                l1[i] = curr_c5
                hl[i] = curr_c5
            elif c_count == 1:
                if curr_x >= hb[i-1]:
                    hb[i] = curr_x
                    hl[i] = curr_c5
                    trendx[i] = 1
                else:
                    lb[i] = curr_n
                    l1[i] = curr_c5
                    trendx[i] = -1
            else:
                if trendx[i-1] > 0:
                    hl[i] = max(hl[i-1], curr_c5)
                    if curr_x >= hb[i-1]:
                        hb[i] = curr_x
                        trendx[i] = trendx[i-1] # Giữ nguyên trend
                    else:
                        if curr_n < hb[i-1] - hb[i-1] * self.factor:
                            lb[i] = curr_n
                            l1[i] = curr_c5
                            trendx[i] = -1
                        else:
                            hb[i] = hb[i-1]
                            lb[i] = lb[i-1]
                            trendx[i] = trendx[i-1]
                else:
                    l1[i] = min(l1[i-1], curr_c5)
                    if curr_n <= lb[i-1]:
                        lb[i] = curr_n
                        trendx[i] = trendx[i-1] # Giữ nguyên trend
                    else:
                        if curr_x > lb[i-1] + lb[i-1] * self.factor:
                            hb[i] = curr_x
                            hl[i] = curr_c5
                            trendx[i] = 1
                        else:
                            hb[i] = hb[i-1]
                            lb[i] = lb[i-1]
                            trendx[i] = trendx[i-1]
            
            c_count += 1

        current_trend = trendx[-1]
        prev_trend = trendx[-2]
        
        # Mặc định signal none
        final_signal = "none"
        reason = "Chờ tín hiệu"
        
        # Crossover buy/sell
        if current_trend == 1 and prev_trend == -1:
            final_signal = "long"
            reason = "Mở LONG: Custom SMA báo Trend Tăng"
        elif current_trend == -1 and prev_trend == 1:
            final_signal = "short"
            reason = "Mở SHORT: Custom SMA báo Trend Giảm"

        current_price = close.iloc[-1]

        # Quản lý đóng lệnh
        for pos in current_positions:
            pos_symbol = pos.get("symbol", "").replace("/", "")
            if pos_symbol == symbol.replace("/", ""):
                side = pos.get("side", "")
                if side == "long" and current_trend == -1:
                    final_signal = "close_long"
                    reason = "Chốt lệnh LONG: Custom SMA báo Trend Giảm"
                elif side == "short" and current_trend == 1:
                    final_signal = "close_short"
                    reason = "Chốt lệnh SHORT: Custom SMA báo Trend Tăng"

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason
        )
