# utils/operators/time_series/zscore.py

description = {
    "description": "对输入数据进行标准化（时序算子）",
    "args": {
        "x": "输入数据序列"
    },
    "return": "标准化后的序列（索引与输入一致）",
    "example":  "ts_zscore(close)"
}

def ts_zscore(x):
    return (x - x.mean()) / x.std()
