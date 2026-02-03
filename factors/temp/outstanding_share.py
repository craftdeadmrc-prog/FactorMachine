"""
股票流通量因子计算
"""

dependencies = ["code", "volume", "turnover_ratio"]

provided_columns = ["outstanding_share"]

description = {
    "name": {
        "中文名": "股票流通量",
        "英文名": "Outstanding Share",
        "变量名": "outstanding_share"
    },
    "info": {
        "介绍": "股票流通量，通过成交量和换手率反推得到的股票流通量估计值",
        "日期": "",
        "计算公式": "outstanding_share = volume / turnover_ratio"
    }
}

def compute_factor(df):
    df['outstanding_share'] = (df['volume'] / df['turnover_ratio'])
    return df