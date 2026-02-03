# FactorMachine/utils/operators/cross_section/zscore.py

description = {
    "description": "对输入数据进行标准化（截面算子），计算 (x - 均值) / 标准差",
    "args": {
        "x": "输入数据序列",
        "group_by": "分组字段，默认为 None，按该字段分组后在组内做标准化"
    },
    "return": "标准化后的序列",
    "example": "zscore(close, 'industry')"
}

def zscore(x, group_by=None):
    """
    标准化算子
    """
    if group_by is None:
        return (x - x.mean()) / x.std()
    else:
        return (x - x.groupby(group_by).mean()) / x.groupby(group_by).std()