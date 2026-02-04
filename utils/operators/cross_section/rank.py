# FactorMachine/utils/operators/cross_section/rank.py

description = {
    "description": "对输入数据在分组内进行排序（截面算子）",
    "args": {
        "x": "输入数据序列",
        "group_by": "分组字段，默认为 None"
    },
    "return": "排序后的排名序列",
    "example": "rank(close, 'industry')"
}

def rank(x):
    """
    排序算子
    """
    return x.rank()
