# FactorMachine/utils/operators/time_series/shift.py

description = {
    "description": "对输入序列进行位移操作（时间序列算子）",
    "args": {
        "periods": "位移的期数，正数为向下位移，负数为向上位移"
    },
    "return": "位移后的序列",
    "example": "shift(close, 1)"
}

def shift(x, periods=1):
    """
    序列位移算子
    """
    return x.shift(periods=periods)