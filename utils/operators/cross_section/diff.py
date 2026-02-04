# utils/operators/cross_section/diff.py

description = {
    "description": "对输入序列进行差分运算（截面算子）",
    "args": {
        "periods": "差分的阶数，默认为 1"
    },
    "return": "差分后的序列",
    "example": "diff(close, 1)"
}

def diff(x, periods=1):
    """
    简单差分算子
    """
    return x.diff(periods=periods)