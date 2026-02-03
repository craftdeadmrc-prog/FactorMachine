description = {
    "description": "计算标准差（截面算子）",
    "args": {
        "x": "输入序列",
        "group_by": "分组字段，默认'code'"
    },
    "return": "标准差序列",
    "example": ["std(close, 'date')"]
}

def std(x, group_by='code'):
    """
    标准差算子
    """
    return x.groupby(group_by).transform('std')