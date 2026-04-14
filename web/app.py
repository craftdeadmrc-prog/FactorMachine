import asyncio
import logging
import os
import sys
import re
import math
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from itertools import groupby
from urllib.parse import parse_qs
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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
        self.ttl = ttl

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
# 静态文件服务 - 手动路由，排除 /ws/* 路径
# ----------------------
@app.get("/{full_path:path}")
async def serve_static_files(full_path: str):
    # 关键修复：排除 WebSocket 路径，避免与 /ws/kline 冲突
    if full_path.startswith("ws/") or full_path == "ws":
        return JSONResponse(status_code=404, content={"error": "WebSocket endpoint"})
    
    # 构建文件路径
    file_path = os.path.join(current_dir, full_path) if full_path else current_dir
    
    # 如果是文件，直接返回
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # 如果是目录，尝试返回 index.html
    index_path = os.path.join(file_path, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    
    # 兜底：返回根目录 index.html（支持 SPA 路由）
    root_index = os.path.join(current_dir, "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index)
    
    return HTMLResponse(status_code=404, content="Not found")

# ----------------------
# WebSocket 端点 - 纯传输通道
# ----------------------
@app.websocket("/ws/kline")
async def kline_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # 修复1：处理空数据/连接关闭
            if not data or not data.strip():
                continue
            # 修复2：处理纯字符串 ping/pong（非JSON）
            data_stripped = data.strip()
            if data_stripped == 'ping':
                await websocket.send_text(json.dumps({'type': 'pong'}))
                continue
            if data_stripped == 'pong':
                continue
            try:
                msg = json.loads(data)
                msg_type = msg.get('type')
                
                if msg_type == 'request':
                    req_id = msg.get('reqId')
                    endpoint = msg.get('endpoint', '')
                    params = msg.get('params', {})
                    
                    if not isinstance(params, dict):
                        params = {}
                    
                    if '?' in endpoint:
                        base_endpoint, query_string = endpoint.split('?', 1)
                        query_params = parse_qs(query_string)
                        for k, v in query_params.items():
                            if k not in params:
                                params[k] = v[0] if len(v) == 1 else v
                        endpoint = base_endpoint
                    
                    loop = asyncio.get_running_loop()
                    
                    if endpoint == '/kline/data':
                        result = await _get_kline_data_ws(
                            market=params.get('market'),
                            interval=params.get('interval'),
                            symbol=params.get('symbol'),
                            range_type=params.get('range_type', '1m'),
                            start_date=params.get('start_date'),
                            end_date=params.get('end_date'),
                            adj=params.get('adj', 'none'),
                            bar_type=params.get('bar_type', 'time'),
                            bar_threshold=params.get('bar_threshold'),
                            offset=int(params.get('offset', 0)) if params.get('offset') is not None else 0,
                            limit=int(params.get('limit', 50000)) if params.get('limit') is not None else 50000,
                            sort_order='asc'  # 始终正序查询，前端控制加载方向
                        )
                        await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                        
                    elif endpoint == '/kline/overview':
                        result = await _get_kline_overview_ws(
                            market=params.get('market'),
                            interval=params.get('interval')
                        )
                        await websocket.send_text(json.dumps({'reqId': req_id, 'data': result}, default=str))
                        
                    elif endpoint == '/kline/symbols':
                        market = params.get('market')
                        if market:
                            result = await _get_kline_symbols_ws(market)
                            await websocket.send_text(json.dumps({'reqId': req_id, 'data': result}, default=str))
                        else:
                            await websocket.send_text(json.dumps({'reqId': req_id, 'error': 'market parameter required'}, default=str))
                            
                    elif endpoint == '/kline/tables':
                        market = params.get('market')
                        if market:
                            result = await _get_kline_tables_ws(market)
                            await websocket.send_text(json.dumps({'reqId': req_id, 'data': result}, default=str))
                        else:
                            await websocket.send_text(json.dumps({'reqId': req_id, 'error': 'market parameter required'}, default=str))
                            
                    elif endpoint == '/status':
                        result = task_handler.get_status_info()
                        await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                        
                    elif endpoint == '/tasks':
                        result = _get_all_tasks_ws()
                        await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                        
                    elif endpoint.startswith('/logs/'):
                        task_name = endpoint.split('/')[-1]
                        if task_name:
                            result = log_handler.get_task_logs(task_name, task_handler.scheduler)
                            await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                        else:
                            await websocket.send_text(json.dumps({'reqId': req_id, 'error': 'task_name required'}, default=str))
                            
                    else:
                        await websocket.send_text(json.dumps({'reqId': req_id, 'error': f'Unknown endpoint: {endpoint}'}, default=str))
                
                elif msg_type == 'ping':
                    await websocket.send_text(json.dumps({'type': 'pong'}))
                    
            except json.JSONDecodeError as e:
                logger.error(f"WS JSON decode error: {e}")
                continue
            except Exception as e:
                logger.error(f"WS handler error: {e}", exc_info=True)
                await websocket.send_text(json.dumps({'error': str(e)}, default=str))
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WS connection error: {e}", exc_info=True)

# ----------------------
# WS专用业务函数
# ----------------------
async def _get_kline_symbols_ws(market: str):
    sql = "SELECT DISTINCT symbol FROM symbols ORDER BY symbol"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
        return df['symbol'].tolist()
    except Exception as e:
        logger.error(f"Failed to get symbols: {e}")
        return []

async def _get_kline_tables_ws(market: str):
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_name LIKE 'kline_%'"
    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return []
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

async def _get_kline_overview_ws(market: str, interval: str):
    table_name = f"kline_{interval}"
    loop = asyncio.get_running_loop()
    
    try:
        check_sql = f'SELECT COUNT(*) as cnt FROM "{table_name}"'
        cnt_df = await loop.run_in_executor(None, load_dataframe, check_sql, market)
        total_rows = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
    except Exception:
        total_rows = 0

    try:
        symbols_sql = "SELECT symbol, short_name FROM symbols"
        df_symbols = await loop.run_in_executor(None, load_dataframe, symbols_sql, market)
        if df_symbols.empty:
            return []
        base_data = df_symbols.to_dict('records')
    except Exception as e:
        logger.error(f"Failed to load symbols: {e}")
        return []

    LARGE_TABLE_THRESHOLD = 100_000_000
    if total_rows > LARGE_TABLE_THRESHOLD:
        logger.info(f"Large table {table_name}, skipping price calculation.")
        return clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])

    try:
        data_sql = f'''
            SELECT s.symbol, s.short_name, k.close, k.date
            FROM symbols s
            LEFT JOIN LATERAL (
                SELECT close, date FROM "{table_name}"
                WHERE symbol = s.symbol
                ORDER BY date DESC LIMIT 2
            ) k ON true
            ORDER BY s.symbol, k.date DESC
        '''
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
                if talib:
                    roc = talib.ROC(closes[::-1], timeperiod=1)
                    if len(roc) > 1 and not np.isnan(roc[1]):
                        item['pct_change'] = round(float(roc[1]), 2)
                else:
                    if closes[1] != 0:
                        item['pct_change'] = round((closes[0] - closes[1]) / closes[1] * 100, 2)
            
            results.append(item)
        
        return clean_nan(results)

    except Exception as e:
        logger.error(f"Overview error: {e}")
        return clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])

async def _get_kline_data_ws(
    market: str,
    interval: str,
    symbol: str,
    range_type: str = "1m",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    adj: str = "none",
    bar_type: str = "time",
    bar_threshold: Optional[float] = None,
    offset: int = 0,
    limit: int = 50000,
    sort_order: str = "asc"  # 始终正序，前端控制加载方向
):
    if not re.match(r'^[a-zA-Z0-9_]+$', interval):
        return {"error": "Invalid interval format"}
    table_name = f"kline_{interval}"

    now = datetime.now()
    end_dt = pd.to_datetime(end_date) if end_date else now

    if start_date:
        start_dt = pd.to_datetime(start_date)
    else:
        if range_type == '1w':
            start_dt = end_dt - timedelta(weeks=1)
        elif range_type == '1m':
            start_dt = end_dt - timedelta(days=30)
        elif range_type == '1y':
            start_dt = end_dt - timedelta(days=365)
        elif range_type == 'all':
            start_dt = None
        else:
            start_dt = end_dt - timedelta(days=365)

    cache_key_params = (market, symbol, interval, adj, str(start_dt), str(end_dt))
    loop = asyncio.get_running_loop()
    df_full = None

    if adj in ['qfq', 'hfq']:
        df_full = kline_cache.get(*cache_key_params)

    if df_full is None:
        sql = f'''
            SELECT 
                date, open, close, volume, high, low
            FROM "{table_name}" 
            WHERE symbol = '{symbol}'
        '''
        
        if start_dt:
            sql += f" AND date >= '{start_dt.strftime('%Y-%m-%d')}'"
        if end_date:
            sql += f" AND date <= '{end_dt.strftime('%Y-%m-%d')}'"
        
        if adj == 'none':
            count_sql = f"SELECT COUNT(*) as cnt FROM ({sql})"
            cnt_df = await loop.run_in_executor(None, load_dataframe, count_sql, market)
            total_count = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
            
            paginated_sql = f"{sql} ORDER BY date ASC LIMIT {limit} OFFSET {offset}"
            df = await loop.run_in_executor(None, load_dataframe, paginated_sql, market)
        else:
            df = await loop.run_in_executor(None, load_dataframe, sql, market)
            
            if not df.empty:
                df = df.sort_values('date').reset_index(drop=True) 
                try:
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
                
                kline_cache.set(*cache_key_params, df)
                df_full = df

    if df_full is not None:
        total_count = len(df_full)
        df = df_full.iloc[offset: offset + limit].copy()
    elif adj != 'none':
        total_count = 0
        df = pd.DataFrame()

    if df.empty:
        if offset == 0:
            return {"data": [], "total": 0, "offset": offset, "limit": limit, "more": False}
        else:
            return {"data": [], "total": total_count, "offset": offset, "limit": limit, "more": False}

    df = df.sort_values('date').reset_index(drop=True)

    if bar_type != 'time':
        try:
            df = bars.generate_bars(df, bar_type=bar_type, threshold=bar_threshold)
        except Exception as e:
            logger.error(f"Failed to generate bars: {e}")

    if 'date' in df.columns:
        df['date'] = df['date'].astype(str)

    records = df.to_dict(orient="records")
    
    # 修复3：返回 more 字段，供前端判断是否还有数据
    has_more = offset + limit < total_count

    return {
        "data": clean_nan(records),
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "more": has_more  # 新增字段
    }

def _get_all_tasks_ws():
    tasks = task_handler.scheduler.get_all_tasks()
    valid_tasks_with_ids = [
        (log_handler.get_db_identifier(t.name, task_handler.scheduler), {
            "name": t.name,
            "description": t.description,
            "type": t.type
        })
        for t in tasks
        if log_handler.get_db_identifier(t.name, task_handler.scheduler) not in ("unknown", "system")
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

@app.on_event("startup")
async def startup_event():
    logger.info("Web panel startup. Running init...")
    asyncio.create_task(task_handler.run_init_task(update=False))
    task_handler.start_background_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    task_handler.bg_scheduler.shutdown()