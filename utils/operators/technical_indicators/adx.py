# FactorMachine/utils/operators/technical_indicators/adx.py

description = {
    "description": "计算平均趋向指数 ADX（技术指标）",
    "args": {
        "high": "最高价序列",
        "low": "最低价序列",
        "close": "收盘价序列",
        "period": "计算周期，默认为 14"
    },
    "return": "ADX 序列",
    "example": "adx(high, low, close, 14)"
}

def adx(high, low, close, period=14):
    """
    平均趋向指数 ADX
    """
    import pandas as pd

    # 真实波幅 TR
    tr = pd.DataFrame()
    tr["h-l"] = high - low
    tr["h-c"] = (high - close.shift(1)).abs()
    tr["l-c"] = (low - close.shift(1)).abs()
    tr["tr"] = tr.max(axis=1)

    # 方向运动 DM
    dm_pos = high.diff()
    dm_neg = low.diff().abs()

    dm_pos[dm_pos < 0] = 0
    dm_neg[dm_neg < 0] = 0
    dm_pos[dm_pos < dm_neg] = 0
    dm_neg[dm_neg < dm_pos] = 0

    # 平滑
    tr_sm = tr["tr"].rolling(window=period).sum()
    dm_pos_sm = dm_pos.rolling(window=period).sum()
    dm_neg_sm = dm_neg.rolling(window=period).sum()

    # 方向指标 DI
    di_pos = dm_pos_sm / tr_sm * 100
    di_neg = dm_neg_sm / tr_sm * 100

    # DX
    dx = (di_pos - di_neg).abs() / (di_pos + di_neg) * 100

    # ADX
    adx = dx.rolling(window=period).mean()
    return adx