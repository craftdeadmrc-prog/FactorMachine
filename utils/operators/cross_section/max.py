description = {
    "description": "计算最大值（截面算子）",
    "args": {
        "x": "输入序列",
        "group_by": "分组字段，默认'code'"
    },
    "return": "最大值序列",
    "example": "max(close, 'date')"
}

def max(x, group_by='code'):
    """
    最大值算子
    """
    grouped = x.groupby(level=group_by)
    return grouped.transform("max")
    # return x.groupby(group_by).transform('max')