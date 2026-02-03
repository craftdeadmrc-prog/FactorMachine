# FactorMachine/utils/operators/cross_section/rank.py

description = {
    "description": "对输入数据在分组内进行排序（截面算子）",
    "args": {
        "x": "输入数据序列",
        "group_by": "分组字段，默认为 'date'"
    },
    "return": "排序后的排名序列",
    "example": "rank(close, 'code')"
}

def rank(x, group_by='date'):
    """
    排序算子
    """
    return x.groupby(group_by).rank()