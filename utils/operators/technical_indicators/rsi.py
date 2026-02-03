# FactorMachine/utils/operators/technical_indicators/rsi.py

description = {
    "description": "计算相对强弱指标 RSI（技术指标）",
    "args": {
        "close": "收盘价序列",
        "period": "计算周期，默认为 14"
    },
    "return": "RSI 序列",
    "example": "rsi(close, 14)"
}

def rsi(close, period=14):
    """
    相对强弱指标 RSI
    """

    # 计算涨跌幅
    delta = close.diff()

    # 分离上涨和下跌
    gain = delta.copy()
    loss = delta.copy()
    gain[gain < 0] = 0
    loss[loss > 0] = 0

    # 计算平均收益和平均损失
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean().abs()

    # 计算 RS
    rs = avg_gain / avg_loss

    # 计算 RSI
    rsi = 100 - (100 / (1 + rs))
    return rsi