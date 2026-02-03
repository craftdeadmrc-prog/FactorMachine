# FactorMachine/utils/operators/time_series/diff.py

description = {
    "description": "对输入序列进行差分运算（时间序列算子）",
    "args": {
        "periods": "差分的阶数，默认为 1"
    },
    "return": "差分后的序列",
    "example": "diff(close, 1)"
}

def diff(series, periods=1):
    """
    简单差分算子
    """
    return series.diff(periods=periods)