# web/app.py
import asyncio
import logging
import os
import sys
import re
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from itertools import groupby
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
import pandas as pd
import numpy as np
from threading import Lock
import time

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from web import task_handler
from web import log_handler
from core.storage import load_dataframe
from utils.data import bars

# 导入 talib
try:
    import talib
except ImportError:
    talib = None
    logging.warning("TA-Lib not found. Overview calculation will fallback to pandas.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入复权工具
try:
    from utils.data.fq_transfer import calculate_qfq, calculate_hfq
except ImportError:
    def calculate_qfq(df, factor): return df
    def calculate_hfq(df, factor): return df
    logger.warning("utils.data.fq_transfer not found, FQ calculation disabled.")

app = FastAPI(title="FactorMachine Web Panel")
current_dir = os.path.dirname(os.path.abspath(__file__))

# ----------------------
# 简单的内存缓存 (用于复权数据分块)
# ----------------------
class KlineCache:
    def __init__(self, max_size=10, ttl=300):
        self.cache = {}
        self.lock = Lock()
        self.max_size = max_size
        self.ttl = ttl # seconds

    def _key(self, market, symbol, interval, adj, start, end):
        return f"{market}_{symbol}_{interval}_{adj}_{start}_{end}"

    def get(self, market, symbol, interval, adj, start, end):
        key = self._key(market, symbol, interval, adj, start, end)
        with self.lock:
            if key in self.cache:
                data, ts = self.cache[key]
                if time.time() - ts < self.ttl:
                    return data
                else:
                    del self.cache[key]
        return None

    def set(self, market, symbol, interval, adj, start, end, data):
        key = self._key(market, symbol, interval, adj, start, end)
        with self.lock:
            # 简单的 LRU：如果满了，删掉最旧的一个
            if len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            self.cache[key] = (data, time.time())

kline_cache = KlineCache()

# ----------------------
# 工具函数
# ----------------------
def clean_nan(data):
    if isinstance(data, dict):
        return {k: clean_nan(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_nan(item) for item in data]
    elif isinstance(data, float) and math.isnan(data):
        return None
    else:
        return data
 
# ----------------------
# 路由：API 接口
# ----------------------
 
@app.get("/api/tasks")
def get_all_tasks():
    tasks = task_handler.scheduler.get_all_tasks()
    valid_tasks_with_ids = [
        (log_handler.get_db_identifier(t.name, task_handler.scheduler), {
            "name": t.name,
            "description": t.description,
            "type": t.type
        })
        for t in tasks
        if log_handler.get_db_identifier(t.name, task_handler.scheduler) != "unknown"
    ]
    valid_tasks_with_ids.sort(key=lambda x: x[0])
    grouped_tasks = {
        db_id: [item[1] for item in group]
        for db_id, group in groupby(valid_tasks_with_ids, key=lambda x: x[0])
    }
    grouped = {
        "System": [{"name": "Init", "description": "初始化市场代码列表", "type": "system"}],
        **grouped_tasks
    }
    return grouped
 
@app.get("/api/status")
def get_status():
    return task_handler.get_status_info()
 
@app.post("/api/run")
async def run_tasks(payload: Dict[str, Any] = Body(...)):
    # 保持原有逻辑不变
    task_names = payload.get("task_names", [])
    symbols = payload.get("symbols") 
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    update = payload.get("update", False)
    if not task_names:
        raise HTTPException(status_code=400, detail="未选择任何任务")
    has_init = "Init" in task_names
    other_tasks = [t for t in task_names if t != "Init"]
    if has_init:
        logger.info("Running Init task...")
        asyncio.create_task(task_handler.run_init_task(update=True))
    if not other_tasks:
        return {"message": "Init task submitted."}
    loop = asyncio.get_running_loop() 
    tasks_with_ids = [
        (log_handler.get_db_identifier(t, task_handler.scheduler), t) 
        for t in other_tasks
    ]
    valid_tasks = sorted(
        [(db_id, t) for db_id, t in tasks_with_ids if db_id != "unknown"],
        key=lambda x: x[0]
    )
    tasks_by_market = {
        db_id: [item[1] for item in group]
        for db_id, group in groupby(valid_tasks, key=lambda x: x[0])
    }
    if not tasks_by_market:
        raise HTTPException(status_code=400, detail="无法识别任务的市场类型")
    submission_count = 0
    default_end_date = pd.Timestamp.now().date()
    for db_id, market_task_names in tasks_by_market.items():
        try:
            if not symbols:
                sql = "SELECT market, symbol, date FROM symbols"
            else:
                in_clause = "', '".join([s.replace("'", "''") for s in symbols])
                sql = f"SELECT market, symbol, date FROM symbols WHERE symbol IN ('{in_clause}')"
            df = await loop.run_in_executor(None, load_dataframe, sql, db_id)
            if df.empty:
                logger.warning(f"No symbols found in database for market: {db_id}")
                continue
            df['start_date'] = pd.to_datetime(start_date) if start_date else pd.to_datetime(df['date'])
            df['end_date'] = pd.to_datetime(end_date) if end_date else pd.to_datetime(default_end_date)
            tasks_params = df[['market', 'symbol', 'start_date', 'end_date']].to_dict('records')
            submitted = [
                asyncio.create_task(task_handler.execute_task_internal(task_name, tasks_params, update))
                for task_name in market_task_names
            ]
            submission_count += len(submitted)
        except Exception as e:
            logger.error(f"Failed to process tasks for market {db_id}: {e}")
    return {"message": f"Tasks submitted. Total groups processed: {len(tasks_by_market)}."}
 
 
@app.delete("/api/logs/{task_name}")
def clear_task_logs(task_name: str):
    return log_handler.clear_task_logs(task_name, task_handler.scheduler)
 
@app.get("/api/logs/{task_name}")
def get_task_logs(task_name: str):
    return log_handler.get_task_logs(task_name, task_handler.scheduler)
 
# ----------------------
# K线接口
# ----------------------
 
@app.get("/api/kline/symbols/{market}")
async def get_kline_symbols(market: str):
    sql = "SELECT DISTINCT symbol FROM symbols ORDER BY symbol"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty: return []
        return df['symbol'].tolist()
    except Exception as e:
        logger.error(f"Failed to get symbols: {e}")
        return []
 
@app.get("/api/kline/tables/{market}")
async def get_kline_tables(market: str):
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_name LIKE 'kline_%'"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty: return []
        tables = []
        pattern = re.compile(r"^kline_(.+)$")
        for _, row in df.iterrows():
            match = pattern.match(row['table_name'])
            if match:
                tables.append({"interval": match.group(1), "table_name": row['table_name']})
        return tables
    except Exception as e:
        logger.error(f"Failed to get kline tables: {e}")
        return []
 
@app.get("/api/kline/overview")
async def get_kline_overview(market: str, interval: str):
    table_name = f"kline_{interval}"
    loop = asyncio.get_running_loop()
 
    # 1. 检查表是否存在及数据量
    try:
        check_sql = f"SELECT COUNT(*) as cnt FROM \"{table_name}\""
        cnt_df = await loop.run_in_executor(None, load_dataframe, check_sql, market)
        total_rows = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
    except Exception:
        # 表不存在
        total_rows = 0
 
    # 获取基础代码列表
    try:
        symbols_sql = "SELECT symbol, short_name FROM symbols"
        df_symbols = await loop.run_in_executor(None, load_dataframe, symbols_sql, market)
        if df_symbols.empty: return []
        base_data = df_symbols.to_dict('records')
    except Exception as e:
        logger.error(f"Failed to load symbols: {e}")
        return []
 
    # 阈值判断：超过1亿条不计算价格
    LARGE_TABLE_THRESHOLD = 100_000_000
    if total_rows > LARGE_TABLE_THRESHOLD:
        logger.info(f"Large table {table_name}, skipping price calculation.")
        return clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])
 
    # 2. 小表：查询价格并计算
    try:
        # 使用 LATERAL JOIN 获取最近两条
        data_sql = f"""
            SELECT s.symbol, s.short_name, k.close, k.date
            FROM symbols s
            LEFT JOIN LATERAL (
                SELECT close, date FROM "{table_name}"
                WHERE symbol = s.symbol
                ORDER BY date DESC LIMIT 2
            ) k ON true
            ORDER BY s.symbol, k.date DESC
        """
        df_raw = await loop.run_in_executor(None, load_dataframe, data_sql, market)
        if df_raw.empty:
            return clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])
 
        results = []
        for sym, group in df_raw.groupby('symbol'):
            group = group.sort_values('date', ascending=False)
            closes = group['close'].values
            
            item = {
                'symbol': sym,
                'short_name': group['short_name'].iloc[0],
                'close': closes[0] if len(closes) > 0 else None,
                'pct_change': None
            }
            
            if len(closes) >= 2:
                # 向量化计算
                # 注意顺序：group是降序，closes[0]是新，closes[1]是旧
                # ROC 需要 [旧, 新]
                if talib:
                    roc = talib.ROC(closes[::-1], timeperiod=1)
                    # ROC[1] 是变化率
                    if len(roc) > 1 and not np.isnan(roc[1]):
                        item['pct_change'] = round(float(roc[1]), 2)
                else:
                    if closes[1] != 0:
                        item['pct_change'] = round((closes[0] - closes[1]) / closes[1] * 100, 2)
            
            results.append(item)
        
        # 关键：清洗 NaN
        return clean_nan(results)
 
    except Exception as e:
        logger.error(f"Overview error: {e}")
        return clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])
 
@app.get("/api/kline/data") 
async def get_kline_data( 
    market: str, 
    interval: str, 
    symbol: str, 
    range_type: str = "1m",
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None,
    adj: str = "none",
    bar_type: str = "time",
    bar_threshold: Optional[float] = None,
    offset: int = 0,      # 新增：分页偏移
    limit: int = 50000    # 新增：每块大小，默认 5 万条
 ):
    if not re.match(r'^[a-zA-Z0-9_]+$', interval):
        raise HTTPException(status_code=400, detail="Invalid interval format")
    
    table_name = f"kline_{interval}"
    
    now = datetime.now()
    end_dt = pd.to_datetime(end_date) if end_date else now
    
    # 解析时间范围
    if start_date:
        start_dt = pd.to_datetime(start_date)
    else:
        if range_type == '1w': start_dt = end_dt - timedelta(weeks=1)
        elif range_type == '1m': start_dt = end_dt - timedelta(days=30)
        elif range_type == '1y': start_dt = end_dt - timedelta(days=365)
        elif range_type == 'all': start_dt = None
        else: start_dt = end_dt - timedelta(days=365)

    # 缓存键
    cache_key_params = (market, symbol, interval, adj, str(start_dt), str(end_dt))
    
    loop = asyncio.get_running_loop()
    
    # 检查是否需要复权，如果需要复权，我们优先使用缓存
    df_full = None
    
    if adj in ['qfq', 'hfq']:
        df_full = kline_cache.get(*cache_key_params)
    
    # 如果没有缓存或者不复权，则查询数据库
    if df_full is None:
        # 构建 SQL
        sql = f"""
            SELECT 
                date, open, close, volume, high, low
            FROM "{table_name}" 
            WHERE symbol = '{symbol}'
        """
        
        if start_dt:
            sql += f" AND date >= '{start_dt.strftime('%Y-%m-%d')}'"
        if end_date:
            sql += f" AND date <= '{end_dt.strftime('%Y-%m-%d')}'"
        
        # 仅在不复权且需要分页时，直接在 SQL 层面分页，效率最高
        # 如果需要复权，必须先拉取全量数据计算
        if adj == 'none':
            # 获取总数
            count_sql = f"SELECT COUNT(*) as cnt FROM ({sql})"
            cnt_df = await loop.run_in_executor(None, load_dataframe, count_sql, market)
            total_count = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
            
            # 追加分页
            # DuckDB 使用 LIMIT OFFSET
            paginated_sql = f"{sql} ORDER BY date LIMIT {limit} OFFSET {offset}"
            df = await loop.run_in_executor(None, load_dataframe, paginated_sql, market)
        else:
            # 复权逻辑：拉取全量 -> 计算 -> 存入缓存 -> 后续逻辑切片
            df = await loop.run_in_executor(None, load_dataframe, sql, market)
            
            if not df.empty:
                df = df.sort_values('date').reset_index(drop=True)
                try:
                    # 尝试获取复权因子
                    check_sql = "SELECT table_name FROM information_schema.tables WHERE table_name = 'adjust_factor'"
                    table_check = await loop.run_in_executor(None, load_dataframe, check_sql, market)
                    if not table_check.empty:
                        factor_sql = f"SELECT date, qfq_factor, hfq_factor FROM adjust_factor WHERE symbol = '{symbol}'"
                        df_factor = await loop.run_in_executor(None, load_dataframe, factor_sql, market)
                        if not df_factor.empty:
                            if adj == 'qfq' and 'qfq_factor' in df_factor.columns:
                                df = calculate_qfq(df, df_factor[['date', 'qfq_factor']])
                            elif adj == 'hfq' and 'hfq_factor' in df_factor.columns:
                                df = calculate_hfq(df, df_factor[['date', 'hfq_factor']])
                except Exception as e:
                    logger.warning(f"FQ error ({adj}): {e}")
                
                # 存入缓存
                kline_cache.set(*cache_key_params, df)
                df_full = df # 指向全量数据

    # 数据处理逻辑
    if df_full is not None:
        # 如果是复权数据（全量在内存中），手动切片
        total_count = len(df_full)
        # 这里注意：offset/limit 是基于查询结果的
        df = df_full.iloc[offset: offset + limit].copy()
    elif adj != 'none':
        # 如果复权但 df_full 为空（之前查询失败）
        total_count = 0
        df = pd.DataFrame()
    else:
        # 不复权的情况，df 和 total_count 已经在上面 SQL 查询时处理了
        pass

    if df.empty:
        if offset == 0:
            return {"data": [], "total": 0}
        else:
            return {"data": [], "total": total_count} # 后续请求为空直接返回

    df = df.sort_values('date').reset_index(drop=True)
    
    # --- Bar 转换逻辑 ---
    # 注意：如果数据量极大，Bar转换在前端做可能更好，或者后端对当前切片做转换
    # 这里为了保持一致性，对当前切片进行 Bar 转换。
    # 但对于 Volume/Cusum Bar，切片转换可能会导致边界处的 Bar 定义不准确。
    # 建议：如果用户选择了非 Time Bar，提示用户数据范围不宜过大，或者接受切片边界误差。
    if bar_type != 'time':
        try:
            df = bars.generate_bars(df, bar_type=bar_type, threshold=bar_threshold)
        except Exception as e:
            logger.error(f"Failed to generate bars: {e}")

    if 'date' in df.columns:
        df['date'] = df['date'].astype(str)
    
    records = df.to_dict(orient="records")
    
    return {
        "data": clean_nan(records),
        "total": total_count,
        "offset": offset,
        "limit": limit
    }

 
# ----------------------
# 静态文件与生命周期
# ----------------------
app.mount("/", StaticFiles(directory=current_dir, html=True), name="web")
 
@app.on_event("startup")
async def startup_event():
    logger.info("Web panel startup. Running init...")
    asyncio.create_task(task_handler.run_init_task(update=False))
    task_handler.start_background_scheduler()
 
@app.on_event("shutdown")
async def shutdown_event():
    task_handler.bg_scheduler.shutdown()