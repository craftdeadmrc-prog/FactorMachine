import os
import duckdb
import pandas as pd
import threading
from .config import DATA_PATH

os.makedirs(DATA_PATH, exist_ok=True)

# 用于保护每个市场数据库文件创建表的锁
_market_locks = {}

def _get_lock(market: str) -> threading.Lock:
    """获取指定市场的锁（每个市场独立）"""
    if market not in _market_locks:
        _market_locks[market] = threading.Lock()
    return _market_locks[market]

def _get_db_path(market: str) -> str:
    """获取市场对应的DuckDB文件路径"""
    return os.path.join(DATA_PATH, f"{market}.duckdb")

def save_dataframe(df: pd.DataFrame, table_name: str, db: str, primary_key: list = None):
    """
    将DataFrame写入指定市场的指定表。
    如果表不存在则自动创建，数据类型根据df的dtype映射。
    如果提供primary_key，则创建主键约束。
    插入数据时使用INSERT OR IGNORE，以忽略主键冲突。
    多线程安全：使用按市场的锁保护表的创建。
    """
    if df is None or df.empty:
        return

    lock = _get_lock(db)
    with lock:  # 确保同一市场内创建表的操作是串行的
        db_path = _get_db_path(db)
        con = duckdb.connect(db_path)
        try:
            # 构建列定义
            columns_def = []
            for col_name, dtype in df.dtypes.items():
                dtype_str = str(dtype)
                if 'datetime' in dtype_str:
                    sql_type = 'TIMESTAMP'
                elif 'int' in dtype_str:
                    sql_type = 'BIGINT'  # 统一使用BIGINT避免溢出
                elif 'float' in dtype_str:
                    sql_type = 'DOUBLE'
                elif 'bool' in dtype_str:
                    sql_type = 'BOOLEAN'
                else:
                    sql_type = 'VARCHAR'
                columns_def.append(f'"{col_name}" {sql_type}')

            if primary_key:
                pk_cols = ', '.join([f'"{c}"' for c in primary_key])
                columns_def.append(f'PRIMARY KEY ({pk_cols})')

            create_stmt = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(columns_def)})'
            con.execute(create_stmt)

            # 注册临时表并插入（忽略主键冲突）
            con.register('temp_df', df)
            cols = ', '.join([f'"{c}"' for c in df.columns])
            insert_stmt = f'INSERT OR IGNORE INTO "{table_name}" ({cols}) SELECT {cols} FROM temp_df'
            con.execute(insert_stmt)
        finally:
            con.close()

def load_dataframe(sql: str, db: str) -> pd.DataFrame:
    """
    执行SQL查询，返回结果DataFrame。
    """
    db_path = _get_db_path(db)
    if not os.path.exists(db_path):
        return pd.DataFrame()
    con = duckdb.connect(db_path)
    try:
        df = con.execute(sql).df()
        return df
    finally:
        con.close()