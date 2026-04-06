import asyncio
import logging
import os
import sys
import re
from datetime import datetime, timedelta
from typing import Optional, List
from itertools import groupby
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
import pandas as pd

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 导入处理模块
from web import task_handler
from web import log_handler
from core.storage import load_dataframe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入复权工具
try:
    from utils.data.fq_transfer import calculate_qfq
except ImportError:
    def calculate_qfq(df, factor): return df
    logger.warning("utils.data.fq_transfer not found, QFQ calculation disabled.")

app = FastAPI(title="FactorMachine Web Panel")
current_dir = os.path.dirname(os.path.abspath(__file__))

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
    """获取指定市场的所有代码列表 (仅用于下拉提示)"""
    sql = "SELECT DISTINCT symbol FROM symbols ORDER BY symbol"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
        return df['symbol'].tolist()
    except Exception as e:
        logger.error(f"Failed to get symbols for {market}: {e}")
        return []

# 修复：补全缺失的 get_kline_tables 接口
@app.get("/api/kline/tables/{market}")
async def get_kline_tables(market: str):
    """获取指定市场数据库中符合命名规范(kline_{interval})的K线表列表"""
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_name LIKE 'kline_%'"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
        tables = []
        pattern = re.compile(r"^kline_(.+)$")
        for _, row in df.iterrows():
            table_name = row['table_name']
            match = pattern.match(table_name)
            if match:
                interval = match.group(1)
                tables.append({"interval": interval, "table_name": table_name})
        return tables
    except Exception as e:
        logger.error(f"Failed to get kline tables for {market}: {e}")
        return []

@app.get("/api/kline/overview")
async def get_kline_overview(market: str, interval: str):
    """
    获取市场概览数据：代码、名称、最新价、涨跌幅
    用于左侧列表展示，一次性返回所有数据由前端缓存
    """
    table_name = f"kline_{interval}"
    sql = f"""
    WITH ranked AS (
        SELECT 
            symbol, 
            close, 
            date,
            ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
        FROM "{table_name}"
    )
    SELECT 
        s.symbol, 
        s.short_name,
        r1.close as close,
        CASE 
            WHEN r2.close IS NULL OR r2.close = 0 THEN 0 
            ELSE ROUND((r1.close - r2.close) / r2.close * 100, 2) 
        END as pct_change
    FROM symbols s
    LEFT JOIN ranked r1 ON s.symbol = r1.symbol AND r1.rn = 1
    LEFT JOIN ranked r2 ON s.symbol = r2.symbol AND r2.rn = 2
    WHERE r1.close IS NOT NULL
    ORDER BY s.symbol
    """
    
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
        df = df.fillna(0)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Failed to get overview for {market}: {e}")
        return []

@app.get("/api/kline/data")
async def get_kline_data(
    market: str, 
    interval: str, 
    symbol: str, 
    range_type: str = "1y",
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
):
    """获取K线数据，修复 highest/lowest 字段名"""
    if not re.match(r'^[a-zA-Z0-9_]+$', interval):
        raise HTTPException(status_code=400, detail="Invalid interval format")
    
    table_name = f"kline_{interval}"
    now = datetime.now()
    end_dt = pd.to_datetime(end_date) if end_date else now
    if start_date:
        start_dt = pd.to_datetime(start_date)
    else:
        if range_type == '1w': start_dt = end_dt - timedelta(weeks=1)
        elif range_type == '1m': start_dt = end_dt - timedelta(days=30)
        elif range_type == '1y': start_dt = end_dt - timedelta(days=365)
        elif range_type == 'all': start_dt = None
        else: start_dt = end_dt - timedelta(days=365)

    sql = f"""
        SELECT 
            date, open, close, 
            highest as high, 
            lowest as low, 
            volume 
        FROM "{table_name}" 
        WHERE symbol = '{symbol}'
    """
    
    if start_dt:
        sql += f" AND date >= '{start_dt.strftime('%Y-%m-%d')}'"
    if end_date:
        sql += f" AND date <= '{end_dt.strftime('%Y-%m-%d')}'"
        
    sql += " ORDER BY date DESC LIMIT 2000"

    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
        
        df = df.sort_values('date').reset_index(drop=True)
        
        check_table_sql = f"SELECT table_name FROM information_schema.tables WHERE table_name = 'adjust_factor'"
        try:
            table_check_df = await loop.run_in_executor(None, load_dataframe, check_table_sql, market)
            if not table_check_df.empty:
                factor_sql = f"SELECT date, qfq_factor, hfq_factor FROM adjust_factor WHERE symbol = '{symbol}'"
                df_factor = await loop.run_in_executor(None, load_dataframe, factor_sql, market)
                if not df_factor.empty:
                    df = calculate_qfq(df, df_factor)
        except Exception as e:
            logger.warning(f"Adjust factor check failed: {e}")

        if 'date' in df.columns:
            df['date'] = df['date'].astype(str)
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        logger.error(f"Failed to load kline data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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