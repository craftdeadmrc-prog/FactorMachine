"""
平均趋向指数因子
计算14日ADX
"""
import pandas as pd
import numpy as np

dependencies = ["code", "high", "low", "close", "date"]

provided_columns = ["adx_14"]

description = {
    "name": {
        "中文名": "14日平均趋向指数",
        "英文名": "14-Day Average Directional Index",
        "变量名": "adx_14"
    },
    "info": {
        "介绍": "14日平均趋向指数(ADX)，衡量趋势的强度而不考虑方向，由威尔斯·怀尔德于1978年提出",
        "日期": "1978",
        "计算公式": "ADX = 平滑移动平均(DX)，其中DX = |(+DI - -DI)| / (+DI + -DI) * 100"
    }
}

def compute_factor(df):
    def calculate_adx(group, period=14):
        high = group['high'].values
        low = group['low'].values
        close = group['close'].values
        
        n = len(high)
        adx_values = np.full(n, np.nan)
        
        if n < period * 2:  # 需要足够的数据
            return pd.Series(adx_values, index=group.index)
        
        # 计算真实波幅(TR)
        tr = np.zeros(n)
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr[i] = max(hl, hc, lc)
        
        # 计算方向运动
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        
        for i in range(1, n):
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move
        
        # 平滑处理
        tr_smooth = np.zeros(n)
        plus_dm_smooth = np.zeros(n)
        minus_dm_smooth = np.zeros(n)
        
        # 初始值
        tr_smooth[period] = np.sum(tr[1:period+1])
        plus_dm_smooth[period] = np.sum(plus_dm[1:period+1])
        minus_dm_smooth[period] = np.sum(minus_dm[1:period+1])
        
        # 后续值
        for i in range(period+1, n):
            tr_smooth[i] = tr_smooth[i-1] - tr_smooth[i-1]/period + tr[i]
            plus_dm_smooth[i] = plus_dm_smooth[i-1] - plus_dm_smooth[i-1]/period + plus_dm[i]
            minus_dm_smooth[i] = minus_dm_smooth[i-1] - minus_dm_smooth[i-1]/period + minus_dm[i]
        
        # 计算方向指标
        plus_di = np.zeros(n)
        minus_di = np.zeros(n)
        
        for i in range(period, n):
            if tr_smooth[i] != 0:
                plus_di[i] = (plus_dm_smooth[i] / tr_smooth[i]) * 100
                minus_di[i] = (minus_dm_smooth[i] / tr_smooth[i]) * 100
        
        # 计算方向指数(DX)
        dx = np.zeros(n)
        for i in range(period, n):
            if (plus_di[i] + minus_di[i]) != 0:
                dx[i] = (abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])) * 100
        
        # 计算ADX
        adx = np.zeros(n)
        adx[period*2-1] = np.mean(dx[period:period*2])
        
        for i in range(period*2, n):
            adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
        
        return pd.Series(adx, index=group.index)
    
    # 计算14日ADX
    adx_series = df.groupby('code').apply(calculate_adx)
    
    # 确保索引正确
    if adx_series.index.nlevels > 1:
        adx_series = adx_series.reset_index(level=0, drop=True)
    
    df['adx_14'] = adx_series
    
    return df