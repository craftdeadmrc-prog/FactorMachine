"""
收益率因子计算
基于收盘价计算日收益率
"""
dependencies = ["code", "close"]

provided_columns = ["return_ratio"]

description = {
    "name": {
        "中文名": "日收益率",
        "英文名": "Daily Return Ratio",
        "变量名": "return_ratio"
    },
    "info": {
        "介绍": "日收益率，反映股票每日的价格变化幅度，是风险调整因子的基础数据",
        "日期": "",
        "计算公式": "return_ratio = (close_t - close_{t-1}) / close_{t-1} * 100"
    }
}

def compute_factor(df):
    df['return_ratio'] = df.groupby('code')['close'].transform(lambda x: x.pct_change() * 100)
    return df