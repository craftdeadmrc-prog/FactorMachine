# utils/operators/cross_section/zscore.py

description = {
    "description": "对输入数据进行标准化（截面算子），计算 (x - 均值) / 标准差",
    "args": {
        "x": "输入数据序列",
        "group_by": "分组字段，默认为'code'"
    },
    "return": "标准化后的序列（索引与输入一致）",
    "example":  "zscore(close, 'date')"
}

def zscore(x):
    return (x - x.mean()) / x.std()
