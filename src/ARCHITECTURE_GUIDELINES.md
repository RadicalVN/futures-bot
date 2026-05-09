# ARCHITECTURE_GUIDELINES.md — Trading Platform Architecture Rules (v1.0)

> Tai lieu nay mo ta **kien truc ky thuat** cua he thong sau khi refactor Phase 4.
> Doc cung voi `DEVELOPMENT_GUIDELINES.md` (quy trinh lam viec, coding standards).
>
> **Self-Update Rule**: AI bat buoc cap nhat file nay moi khi kien truc thay doi.

---

## 1. Nguyen tac Zero-Core-Edit

### Dinh nghia

> Them mot chien luoc giao dich moi = **tao 1 file `.py`** trong `src/strategies/`.
> **Khong duoc sua** bat ky file core nao.

### Tai sao khong duoc sua `bot_engine.py` va `exit_monitor_service.py`?

**`bot_engine.py`** la engine dieu phoi chung cho moi bot. Truoc khi refactor, no chua
chuoi `if/elif` hardcode ten strategy de khoi tao va tinh lookback. Moi lan them strategy
moi phai sua file nay — tao ra coupling chat va nguy co regression cho toan bo he thong
dang chay production.

Sau refactor, `bot_engine.py` chi biet 2 dieu:

```python
self.strategy = StrategyFactory.create(self.strategy_name, self.parameters)
self.lookback = max(self.lookback, self.strategy.get_required_lookback(self.parameters))
```

**`exit_monitor_service.py`** la service cross-bot quet va dong lenh. Truoc day no chua
`_build_strategy()` va `_build_sma_macd_meta()` — hardcode logic indicator cho tung
strategy. Moi strategy moi phai them branch vao day.

Sau refactor, service chi goi:

```python
strategy = StrategyFactory.create(strategy_name, parameters)
meta = await strategy.prepare_metadata(df)
```

**He qua**: Ca hai file nay la **Protected Files** — chi duoc sua khi co bug hoac them
tinh nang infrastructure, khong bao gio sua vi them strategy moi.

### Protected Files (khong sua khi them strategy)

| File | Ly do bao ve |
|---|---|
| `src/core/bot_engine.py` | Engine dieu phoi — dung Factory, khong biet strategy cu the |
| `src/apps/monitoring/exit_monitor_service.py` | Cross-bot service — delegate sang `prepare_metadata()` |
| `src/strategies/factory.py` | Auto-discovery qua `pkgutil` — khong can dang ky thu cong |
| `src/strategies/base_strategy.py` | Contract — chi sua khi mo rong contract toan platform |

---

## 2. Contract Enforcement — BaseStrategy

Moi strategy **bat buoc** implement day du 5 thanh phan sau (2.1–2.5).
Thanh phan 2.6 la optional nhung phai khai bao ro rang neu can.
Factory se tu choi dang ky class thieu bat ky thanh phan bat buoc nao.

### 2.1 `STRATEGY_NAME: str` — Dinh danh duy nhat

```python
STRATEGY_NAME = "my_new_strategy"
```

- Phai la string khong rong, lowercase, dung dau `_`
- Phai khop voi gia tri `Bot.strategy_name` luu trong DB
- StrategyFactory dung field nay de build registry tu dong

### 2.2 `get_required_lookback(parameters: dict) -> int` — Tu tinh lookback

```python
@classmethod
def get_required_lookback(cls, parameters: dict) -> int:
    signal_len = int(parameters.get("macd_signal_length", 500))
    return signal_len + 50
```

- La `@classmethod` — goi duoc ma khong can khoi tao instance
- Strategy tu tinh so nen toi thieu dua tren tham so cua no
- BotEngine dung `max(config_lookback, strategy.get_required_lookback(params))`
- **Khong duoc** hardcode lookback trong `bot_engine.py`

### 2.3 `prepare_metadata(df: pd.DataFrame) -> dict` — Tinh indicators cho ExitMonitor

```python
async def prepare_metadata(self, df: pd.DataFrame) -> dict:
    df = add_custom_sma_to_df(df, ...)
    return {"trend": ..., "momentum": ..., "slope_pct": ...}
```

- La `async` method — co the goi I/O neu can
- Nhan DataFrame OHLCV, tra ve dict metadata
- ExitMonitorService goi method nay — khong tu tinh indicator
- Tra ve `{}` neu strategy khong can metadata dac biet (default tu BaseStrategy)

### 2.4 `PARAMETERS_SCHEMA: dict` — Schema cho Dynamic UI

```python
PARAMETERS_SCHEMA = {
    "type": "object",
    "properties": {
        "timeframe": {
            "type": "string",
            "title": "Timeframe",
            "description": "Khung thoi gian nen",
            "default": "5m",
            "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
            "ui:widget": "select",
        },
        "adx_threshold": {
            "type": "number",
            "title": "ADX Threshold",
            "description": "Nguong ADX toi thieu",
            "default": 20.0,
            "minimum": 5.0,
            "maximum": 60.0,
            "ui:widget": "number",
        },
    },
}
```

- JSON Schema Draft-7 subset voi extension `ui:widget`
- Dashboard dung de tu dong render form nhap tham so
- Supported `ui:widget`: `"number"`, `"select"`, `"boolean"`, `"text"`
- Tra ve `{}` neu chua khai bao — UI fallback ve raw JSON editor

### 2.5 `analyze(symbol, ohlcv_data, current_positions) -> StrategySignal` — Logic giao dich

```python
async def analyze(
    self,
    symbol: str,
    ohlcv_data: list,
    current_positions: list,
) -> StrategySignal:
    ...
```

- **Bat buoc** implement (abstract method)
- Tra ve `StrategySignal` voi `signal`, `price`, `reason`, `metadata`
- Uu tien kiem tra exit truoc entry trong than ham

### 2.6 `requires_one_shot_check: bool` — Bat/Tat logic One-shot (optional)

```python
# Chi khai bao khi strategy can gioi han 1 lenh moi phase Signal
requires_one_shot_check = True
```

- **Thuoc tinh lop** (class attribute), mac dinh `False` tu BaseStrategy
- Khi `True`, BotEngine tu dong goi `_check_one_shot_phase()` truoc khi dat lenh
- Ngan strategy vao nhieu hon 1 lenh trong cung 1 phase Signal bullish/bearish
- **Khong can sua `bot_engine.py`** — Engine doc thuoc tinh nay va xu ly tu dong:

```python
# bot_engine.py — khong hardcode ten strategy
if signal.is_entry and self.strategy.requires_one_shot_check:
    blocked, reason = await self._check_one_shot_phase(signal, symbol)
    if blocked:
        return
```

**Cac strategy hien tai bat True:**

| Strategy | Ly do |
|---|---|
| `sma_macd_cross` (v1-v7) | Moi phase Signal bullish/bearish chi duoc vao 1 lenh |

**Cac strategy giu False (default):**

| Strategy | Ly do |
|---|---|
| `adts`, `ma_macd`, `custom_sma`, ... | Khong co gioi han so lenh theo phase |

### Checklist them strategy moi

```
[ ] Tao file src/strategies/my_strategy.py
[ ] Khai bao STRATEGY_NAME = "my_strategy"
[ ] Implement get_required_lookback()
[ ] Implement prepare_metadata()
[ ] Khai bao PARAMETERS_SCHEMA
[ ] Implement analyze()
[ ] (Optional) Set requires_one_shot_check = True neu can gioi han 1 lenh/phase
[ ] Chay: StrategyFactory.list_names() → phai thay "my_strategy"
[ ] KHONG sua bot_engine.py, exit_monitor_service.py, factory.py
```

---

## 3. Indicator Migration Rule

### Quy dinh

> **Logic toan hoc tinh indicator phai nam trong `src/data/indicators.py`.**
> Strategy files chi duoc *goi* ham tu `indicators.py`, khong duoc tu implement lai.

### Ly do

Truoc khi refactor, ADTS co file `adts/indicators.py` rieng voi cac ham `calculate_adx()`,
`calculate_bbwidth()`, `calculate_ema_slope()`. Cac ham nay duplicate logic voi
`src/data/indicators.py` va khong the tai su dung cho strategy khac.

Sau refactor, tat ca indicator functions duoc tap trung tai `src/data/indicators.py`:

```
src/data/indicators.py
├── calculate_ema(), calculate_sma(), calculate_ma()
├── calculate_macd(), get_ma_values(), get_macd_values()
├── add_custom_sma_to_df()       <- Custom SMA (TuanTV1008)
├── add_custom_macd_to_df()      <- Custom MACD (TuanTV1008)
├── add_adx_to_df()              <- ADX (Wilder's method)
├── add_bb_to_df()               <- Bollinger Bands
├── add_atr_to_df()              <- ATR (Wilder's RMA)
├── add_ema_slope_to_df()        <- EMA + slope
├── add_bbwidth_to_df()          <- BBWidth = (Upper-Lower)/Middle
├── ADTSSnapshot (dataclass)     <- Snapshot tat ca ADTS indicators
└── build_adts_snapshot()        <- Tinh toan bo ADTS indicators
```

### Quy tac cu the

| Duoc phep | Khong duoc phep |
|---|---|
| `from src.data.indicators import add_adx_to_df` | Tu implement `calculate_adx()` trong strategy file |
| Goi `add_custom_sma_to_df(df, ...)` trong `prepare_metadata()` | Copy-paste logic indicator tu file khac |
| Tao ham moi trong `indicators.py` neu chua co | Tao file `indicators.py` rieng trong subfolder strategy |
| Dung `build_adts_snapshot()` cho ADTS-specific indicators | Tinh indicator truc tiep trong `analyze()` ma khong extract ra ham |

### Khi can indicator moi

1. Them ham `add_xxx_to_df(df, ...) -> pd.DataFrame` vao `src/data/indicators.py`
2. Dat ten theo convention: `add_<indicator_name>_to_df`
3. Ham nhan `pd.DataFrame`, tra ve `pd.DataFrame` (them cot moi)
4. Viet docstring Google-style voi Args/Returns
5. Sau do import va dung trong strategy

---

## 4. Self-Update Rule

### Quy dinh

> AI **bat buoc** cap nhat file `ARCHITECTURE_GUIDELINES.md` moi khi kien truc he thong
> thay doi. Cap nhat phai nam trong cung commit voi thay doi kien truc.

### Cac su kien kich hoat cap nhat

| Su kien | Phan can cap nhat |
|---|---|
| Them Protected File moi | Muc 1 — bang Protected Files |
| Them thuoc tinh/method vao BaseStrategy contract | Muc 2 — Contract Enforcement |
| Them indicator function moi vao `indicators.py` | Muc 3 — danh sach functions |
| Thay doi cau truc thu muc `src/strategies/` | Muc 2 — Checklist |
| Them app moi vao `src/apps/` | Muc 1 — Protected Files |
| Thay doi format `PARAMETERS_SCHEMA` | Muc 2.4 |
| Them class attribute moi vao BaseStrategy | Muc 2 — them muc moi |

### Quy trinh cap nhat

```
1. Hoan thanh implement thay doi kien truc
2. Cap nhat ARCHITECTURE_GUIDELINES.md ngay trong cung commit
3. Ghi chu trong commit message: "docs: update ARCHITECTURE_GUIDELINES"
4. Cap nhat bang Version History ben duoi
```

### Version History

| Version | Ngay | Thay doi |
|---|---|---|
| v1.0 | 2026-05-10 | Khoi tao sau khi hoan thanh Phase 4 (Task 4.1 + 4.2) |
| | | - Zero-Core-Edit: StrategyFactory + BaseStrategy contract |
| | | - Indicator Migration: tap trung tai src/data/indicators.py |
| | | - Dynamic UI Bridge: PARAMETERS_SCHEMA + /api/strategies/manifests |
| | | - One-shot check: requires_one_shot_check thay the hardcode |

---

## 5. Tom tat nhanh (Quick Reference)

| Viec can lam | Lam | Khong lam |
|---|---|---|
| Them strategy moi | Tao 1 file `.py` trong `src/strategies/` | Sua `bot_engine.py` hay `factory.py` |
| Tinh indicator | Dung ham tu `src/data/indicators.py` | Tu implement trong strategy file |
| Khai bao tham so | Dien `PARAMETERS_SCHEMA` trong class | Hardcode trong Dashboard JS |
| Tinh lookback | Implement `get_required_lookback()` | Hardcode so nen trong `bot_engine.py` |
| Tinh metadata cho exit | Implement `prepare_metadata()` | Them branch vao `exit_monitor_service.py` |
| Gioi han 1 lenh/phase | Set `requires_one_shot_check = True` | Them `if strategy_name == "..."` trong Engine |
| Kien truc thay doi | Cap nhat file nay ngay | De outdated |
