description = {
    "description": "计算均值（截面算子）",
    "args": {
        "x": "输入序列",
        "group_by": "分组字段，默认'code'"
    },
    "return": "均值序列",
    "example": ["mean(close, 'date')"]
}

def mean(x, group_by='code'):
    """
    均值算子
    """
    return x.groupby(group_by).transform('mean')