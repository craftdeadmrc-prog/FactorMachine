import pandas as pd
import logging
logger = logging.getLogger(__name__)

def calculate_qfq(df_kline: pd.DataFrame, df_factor: pd.DataFrame) -> pd.DataFrame:
    """
    计算前复权数据
    """
    if df_kline.empty or df_factor.empty:
        return df_kline
    
    try:
        # 1. 深拷贝数据，避免 SettingWithCopyWarning
        df = df_kline.copy()
        factor = df_factor.copy()
        
        # 2. 强制统一日期格式为 datetime64[ns]，解决 dtype 不匹配问题
        df['date'] = pd.to_datetime(df['date']).astype('datetime64[ns]')
        factor['date'] = pd.to_datetime(factor['date']).astype('datetime64[ns]')
        
        # 3. 数据清洗
        # 确保因子列存在且有效
        if 'qfq_factor' not in factor.columns:
            return df
            
        factor_map = factor[['date', 'qfq_factor']].drop_duplicates('date').sort_values('date')
        
        # 4. 使用 merge_asof 匹配最近因子
        # direction='backward': 对于K线某天，寻找 <= 该天的最近因子日期
        merged = pd.merge_asof(
            df.sort_values('date'), 
            factor_map, 
            on='date', 
            direction='backward'
        )
        
        # 5. 填充处理
        # bfill: 处理 K线早于最早因子的情况
        # ffill: 处理 K线晚于最新因子的情况 (通常最新因子为1)
        merged['qfq_factor'] = merged['qfq_factor'].bfill()
        merged['qfq_factor'] = merged['qfq_factor'].ffill()
        merged['qfq_factor'] = merged['qfq_factor'].fillna(1.0)
        
        # 6. 应用公式：前复权 = 原价 / 因子
        cols_to_adj = ['open', 'high', 'low', 'close']
        for col in cols_to_adj:
            merged[col] = merged[col] / merged['qfq_factor']
            
        return merged.drop(columns=['qfq_factor'])
        
    except Exception as e:
        logger.error(f"Error calculating QFQ: {e}")
        return df_kline

def calculate_hfq(df_kline: pd.DataFrame, df_factor: pd.DataFrame) -> pd.DataFrame:
    """
    计算后复权数据
    """
    if df_kline.empty or df_factor.empty:
        return df_kline
        
    try:
        # 1. 深拷贝数据
        df = df_kline.copy()
        factor = df_factor.copy()
        
        # 2. 强制统一日期格式
        df['date'] = pd.to_datetime(df['date']).astype('datetime64[ns]')
        factor['date'] = pd.to_datetime(factor['date']).astype('datetime64[ns]')
        
        if 'hfq_factor' not in factor.columns:
            return df
            
        factor_map = factor[['date', 'hfq_factor']].drop_duplicates('date').sort_values('date')
        
        # 3. 匹配因子
        merged = pd.merge_asof(
            df.sort_values('date'), 
            factor_map, 
            on='date', 
            direction='backward'
        )
        
        # 4. 填充处理
        merged['hfq_factor'] = merged['hfq_factor'].bfill()
        merged['hfq_factor'] = merged['hfq_factor'].ffill()
        merged['hfq_factor'] = merged['hfq_factor'].fillna(1.0)
        
        # 5. 应用公式：后复权 = 原价 * 因子
        cols_to_adj = ['open', 'high', 'low', 'close']
        for col in cols_to_adj:
            merged[col] = merged[col] * merged['hfq_factor']
            
        return merged.drop(columns=['hfq_factor'])
        
    except Exception as e:
        logger.error(f"Error calculating HFQ: {e}")
        return df_kline