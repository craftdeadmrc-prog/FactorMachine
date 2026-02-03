# FactorMachine/utils/operators/cross_section/zscore.py

description = {
    "description": "对输入数据进行标准化（截面算子），计算 (x - 均值) / 标准差",
    "args": {
        "x": "输入数据序列",
        "group_by": "分组字段，默认为 'date'，按该字段分组后在组内做标准化"
    },
    "return": "标准化后的序列",
    "example": "zscore(close, 'code')"
}

def zscore(x, group_by='date'):
    """
    标准化算子
    """
    grouped = x.groupby(level=group_by)
    mean = grouped.transform("mean")
    std = grouped.transform("std")
    return (x - mean) / std
    # return (x - x.groupby(group_by).mean()) / x.groupby(group_by).std()
    