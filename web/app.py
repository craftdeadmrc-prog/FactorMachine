# web/app.py
import asyncio
import logging
import os
import sys
import re
import math
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Awaitable
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

# =============================================================================
# 优化点1: WebSocket 路由注册表 + 装饰器
# =============================================================================

# 处理器类型别名：接收 (参数, 事件循环) 返回字典
WSHandler = Callable[[Dict[str, Any], asyncio.AbstractEventLoop], Awaitable[Dict[str, Any]]]

# 路由注册表：endpoint -> handler function
_WS_ROUTES: Dict[str, WSHandler] = {}

def ws_route(endpoint: str):
    """
    装饰器：注册 WebSocket 业务处理器
    用法:
        @ws_route('/kline/data')
        async def handle_kline_data(params, loop):
            return {"data": [...]}
    """
    def decorator(func: WSHandler) -> WSHandler:
        _WS_ROUTES[endpoint] = func
        logger.debug(f"Registered WS endpoint: {endpoint}")
        return func
    return decorator

# =============================================================================
# 优化点2: 缓存类 (保持原逻辑，优化注释)
# =============================================================================

class KlineCache:
    """LRU 缓存：复权数据分块复用，避免重复计算"""
    def __init__(self, max_size: int = 10, ttl: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.lock = Lock()
        self.max_size = max_size
        self.ttl = ttl

    def _key(self, market: str, symbol: str, interval: str, adj: str, start: str, end: str) -> str:
        # 优化：复权因子按 symbol 固定，忽略时间范围提高缓存命中率
        return f"{market}_{symbol}_{interval}_{adj}"

    def get(self, market: str, symbol: str, interval: str, adj: str, start: str, end: str) -> Optional[pd.DataFrame]:
        key = self._key(market, symbol, interval, adj, start, end)
        with self.lock:
            if key in self.cache:
                data, ts = self.cache[key]
                if time.time() - ts < self.ttl:
                    return data
                del self.cache[key]
        return None

    def set(self, market: str, symbol: str, interval: str, adj: str, start: str, end: str, data: pd.DataFrame):
        key = self._key(market, symbol, interval, adj, start, end)
        with self.lock:
            if len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            self.cache[key] = (data, time.time())

kline_cache = KlineCache()

# =============================================================================
# 优化点3: 工具函数 (保持原逻辑，优化类型提示)
# =============================================================================

def clean_nan_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """快速清理单条记录中的 NaN 值"""
    result = {}
    for k, v in record.items():
        if isinstance(v, float) and (v != v):  # NaN != NaN is True
            result[k] = None
        else:
            result[k] = v
    return result

def clean_nan(data: Any) -> Any:
    """高效清理 Kline 数据结构中的 NaN"""
    if isinstance(data, list):
        return [clean_nan_record(item) if isinstance(item, dict) else item for item in data]
    elif isinstance(data, dict):
        return clean_nan_record(data)
    elif isinstance(data, float) and (data != data):
        return None
    return data

# =============================================================================
# 优化点4: 业务处理器 (每个函数职责单一，通过装饰器注册)
# =============================================================================

@ws_route('/kline/data')
async def _handle_kline_data(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """处理 K 线数据查询请求"""
    market = params.get('market')
    interval = params.get('interval')
    symbol = params.get('symbol')
    
    if not re.match(r'^[a-zA-Z0-9_]+$', interval or ''):
        return {"error": "Invalid interval format"}
    
    table_name = f"kline_{interval}"
    range_type = params.get('range_type', '1m')
    start_date = params.get('start_date')
    end_date = params.get('end_date')
    adj = params.get('adj', 'none')
    bar_type = params.get('bar_type', 'time')
    bar_threshold = params.get('bar_threshold')
    offset = int(params.get('offset', 0)) if params.get('offset') is not None else 0
    limit = int(params.get('limit', 250000)) if params.get('limit') is not None else 250000

    now = datetime.now()
    end_dt = pd.to_datetime(end_date) if end_date else now
    start_dt = pd.to_datetime(start_date) if start_date else (
        end_dt - timedelta(weeks=1) if range_type == '1w' else
        end_dt - timedelta(days=30) if range_type == '1m' else
        end_dt - timedelta(days=365) if range_type == '1y' else
        None if range_type == 'all' else
        end_dt - timedelta(days=365)
    )

    cache_key = (market, symbol, interval, adj, str(start_dt), str(end_dt))
    df_full = kline_cache.get(*cache_key) if adj in ['qfq', 'hfq'] else None

    if df_full is None:
        sql = f'SELECT date, open, close, volume, high, low FROM "{table_name}" WHERE symbol = \'{symbol}\''
        if start_dt: sql += f" AND date >= '{start_dt.strftime('%Y-%m-%d')}'"
        if end_date: sql += f" AND date <= '{end_dt.strftime('%Y-%m-%d')}'"
        
        if adj == 'none':
            cnt_df = await loop.run_in_executor(None, load_dataframe, f"SELECT COUNT(*) as cnt FROM ({sql})", market)
            total_count = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
            df = await loop.run_in_executor(None, load_dataframe, f"{sql} ORDER BY date ASC LIMIT {limit} OFFSET {offset}", market)
        else:
            df = await loop.run_in_executor(None, load_dataframe, sql, market)
            if not df.empty:
                df = df.sort_values('date').reset_index(drop=True)
                try:
                    table_check = await loop.run_in_executor(None, load_dataframe, 
                        "SELECT table_name FROM information_schema.tables WHERE table_name = 'adjust_factor'", market)
                    if not table_check.empty:
                        df_factor = await loop.run_in_executor(None, load_dataframe,
                            f"SELECT date, qfq_factor, hfq_factor FROM adjust_factor WHERE symbol = '{symbol}'", market)
                        if not df_factor.empty:
                            if adj == 'qfq' and 'qfq_factor' in df_factor.columns:
                                df = calculate_qfq(df, df_factor[['date', 'qfq_factor']])
                            elif adj == 'hfq' and 'hfq_factor' in df_factor.columns:
                                df = calculate_hfq(df, df_factor[['date', 'hfq_factor']])
                except Exception as e:
                    logger.warning(f"FQ error ({adj}): {e}")
                kline_cache.set(*cache_key, df)
                df_full = df

    if df_full is not None:
        total_count = len(df_full)
        df = df_full.iloc[offset: offset + limit].copy()
    elif adj != 'none':
        total_count, df = 0, pd.DataFrame()
    else:
        total_count = locals().get('total_count', 0)

    if df.empty:
        return {"data": [], "total": total_count, "offset": offset, "limit": limit, "more": False}

    df = df.sort_values('date').reset_index(drop=True)
    if bar_type != 'time':
        try: df = bars.generate_bars(df, bar_type=bar_type, threshold=bar_threshold)
        except Exception as e: logger.error(f"Failed to generate bars: {e}")

    if 'date' in df.columns: df['date'] = df['date'].astype(str)
    records = df.to_dict(orient="records")
    
    return {
        "data": clean_nan(records),
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "more": offset + limit < total_count
    }

@ws_route('/kline/overview')
async def _handle_kline_overview(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """处理市场概览查询"""
    market, interval = params.get('market'), params.get('interval')
    table_name = f"kline_{interval}"
    
    try:
        cnt_df = await loop.run_in_executor(None, load_dataframe, f'SELECT COUNT(*) as cnt FROM "{table_name}"', market)
        total_rows = int(cnt_df.iloc[0, 0]) if not cnt_df.empty else 0
    except: total_rows = 0

    try:
        df_symbols = await loop.run_in_executor(None, load_dataframe, "SELECT symbol, short_name FROM symbols", market)
        if df_symbols.empty: return {"data": []}
        base_data = df_symbols.to_dict('records')
    except Exception as e:
        logger.error(f"Failed to load symbols: {e}")
        return {"data": []}

    if total_rows > 100_000_000:
        return {"data": clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])}

    try:
        data_sql = f'''
            SELECT s.symbol, s.short_name, k.close, k.date
            FROM symbols s
            LEFT JOIN LATERAL (
                SELECT close, date FROM "{table_name}" WHERE symbol = s.symbol ORDER BY date DESC LIMIT 2
            ) k ON true ORDER BY s.symbol, k.date DESC
        '''
        df_raw = await loop.run_in_executor(None, load_dataframe, data_sql, market)
        if df_raw.empty:
            return {"data": clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])}

        results = []
        for sym, group in df_raw.groupby('symbol'):
            group = group.sort_values('date', ascending=False)
            closes = group['close'].values
            item = {'symbol': sym, 'short_name': group['short_name'].iloc[0], 'close': closes[0] if len(closes) > 0 else None, 'pct_change': None}
            if len(closes) >= 2:
                if talib:
                    roc = talib.ROC(closes[::-1], timeperiod=1)
                    if len(roc) > 1 and not np.isnan(roc[1]): item['pct_change'] = round(float(roc[1]), 2)
                elif closes[1] != 0:
                    item['pct_change'] = round((closes[0] - closes[1]) / closes[1] * 100, 2)
            results.append(item)
        return {"data": clean_nan(results)}
    except Exception as e:
        logger.error(f"Overview error: {e}")
        return {"data": clean_nan([{**item, 'close': None, 'pct_change': None} for item in base_data])}

@ws_route('/kline/symbols')
async def _handle_kline_symbols(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取市场股票代码列表"""
    market = params.get('market')
    if not market: return {"error": "market parameter required"}
    try:
        df = await loop.run_in_executor(None, load_dataframe, "SELECT DISTINCT symbol FROM symbols ORDER BY symbol", market)
        return {"data": df['symbol'].tolist() if not df.empty else []}
    except Exception as e:
        logger.error(f"Failed to get symbols: {e}")
        return {"data": []}

@ws_route('/kline/tables')
async def _handle_kline_tables(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取市场 K 线表结构"""
    market = params.get('market')
    if not market: return {"error": "market parameter required"}
    try:
        df = await loop.run_in_executor(None, load_dataframe,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_name LIKE 'kline_%'", market)
        if df.empty: return {"data": []}
        pattern = re.compile(r"^kline_(.+)$")
        tables = [{"interval": match.group(1), "table_name": row['table_name']} 
                 for _, row in df.iterrows() if (match := pattern.match(row['table_name']))]
        return {"data": tables}
    except Exception as e:
        logger.error(f"Failed to get kline tables: {e}")
        return {"data": []}

@ws_route('/status')
async def _handle_status(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取任务状态和调度信息"""
    return task_handler.get_status_info()

@ws_route('/tasks')
async def _handle_tasks(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取所有可执行任务列表"""
    return _get_all_tasks_ws()

@ws_route('/run')
async def _handle_run_task(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """
    执行选定任务 - 优化版
    • 列表推导式替代显式 for 循环
    • 16 点截止规则：未过 16 点则默认日期取昨日
    • 并发处理多市场任务提交
    """
    
    # === 参数提取 ===
    task_names = params.get('task_names', [])
    symbols = params.get('symbols', [])
    start_date = params.get('start_date')
    end_date = params.get('end_date')
    update = params.get('update', False)
    
    if not task_names:
        return {"error": "No tasks selected"}
    
    # === 任务分离：Init 特殊处理 ===
    has_init = 'Init' in task_names
    other_tasks = [t for t in task_names if t != 'Init']
    
    if has_init:
        logger.info("Running Init task via WS...")
        asyncio.create_task(task_handler.run_init_task(update=True))
        if not other_tasks:
            return {"message": "Init task submitted."}
    
    # === 任务分组：列表推导式 + groupby ===
    tasks_with_ids = [
        (log_handler.get_db_identifier(t, task_handler.scheduler), t) 
        for t in other_tasks
    ]
    valid_tasks = sorted(
        [(db_id, t) for db_id, t in tasks_with_ids if db_id not in ("unknown", "system")],
        key=lambda x: x[0]
    )
    tasks_by_market = {
        db_id: [item[1] for item in group]
        for db_id, group in groupby(valid_tasks, key=lambda x: x[0])
    }
    
    if not tasks_by_market:
        return {"error": "No valid tasks found"}
    
    # === 关键修复：16 点日期逻辑 ===
    now = pd.Timestamp.now()
    # 规则：若当前时间 < 16:00，默认日期取昨日；否则取今日
    # 原因：16 点后当日数据才完整，16 点前默认查昨日避免空数据
    reference_date = (now - pd.Timedelta(days=1)).date() if now.hour < 16 else now.date()
    
    # 解析日期参数：优先使用传入值，否则应用参考日期（含 16 点规则）
    parsed_start = pd.to_datetime(start_date) if start_date else None
    parsed_end = pd.to_datetime(end_date) if end_date else pd.to_datetime(reference_date)
    
    # === 内部异步函数：处理单个市场（避免全局污染）===
    async def _process_market(db_id: str, market_task_names: List[str]) -> Optional[int]:
        try:
            # 构建 SQL：列表推导式构建 IN 子句，避免 for 循环
            in_clause = "', '".join([s.replace("'", "''") for s in symbols]) if symbols else None
            sql = (
                f"SELECT market, symbol, date FROM symbols WHERE symbol IN ('{in_clause}')"
                if in_clause 
                else "SELECT market, symbol, date FROM symbols"
            )
            
            # 异步读取数据库（线程池执行同步操作）
            df = await loop.run_in_executor(None, load_dataframe, sql, db_id)
            if df.empty:
                logger.warning(f"No symbols found for market: {db_id}")
                return None
            
            # 应用日期逻辑：
            # • start_date: 优先参数值，否则用原始 date 列（按 symbol 的实际起始日）
            # • end_date: 优先参数值，否则用参考日期（含 16 点规则）
            df['start_date'] = parsed_start if parsed_start else pd.to_datetime(df['date'])
            df['end_date'] = parsed_end
            
            tasks_params = df[['market', 'symbol', 'start_date', 'end_date']].to_dict('records')
            
            # 提交任务执行：列表推导式创建所有 task，避免显式 for
            [
                asyncio.create_task(task_handler.execute_task_internal(tn, tasks_params, update))
                for tn in market_task_names
            ]
            
            return len(market_task_names)
            
        except Exception as e:
            logger.error(f"Failed to process tasks for market {db_id}: {e}")
            return None
    
    # === 并发处理所有市场：asyncio.gather 替代串行 for ===
    results = await asyncio.gather(*[
        _process_market(db_id, names) 
        for db_id, names in tasks_by_market.items()
    ])
    
    # 统计成功提交的任务组数量
    total_count = sum(c for c in results if c is not None)
    
    return {"message": f"Tasks submitted. Total: {total_count}"}

@ws_route('/logs')
async def _handle_logs(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取或清理任务日志 (endpoint: /logs/{task_name})"""
    # 注意：/logs/xxx 的 task_name 在 endpoint 字符串中，不在 params 里
    # 此处理器由主函数特殊处理，这里仅作占位
    return {"error": "Use /logs/{task_name} format"}

# =============================================================================
# 优化点5: 辅助函数 (保持原逻辑)
# =============================================================================

def _get_all_tasks_ws() -> Dict[str, List[Dict]]:
    tasks = task_handler.scheduler.get_all_tasks()
    valid_tasks_with_ids = [
        (log_handler.get_db_identifier(t.name, task_handler.scheduler), {
            "name": t.name, "description": t.description, "type": t.type
        })
        for t in tasks if log_handler.get_db_identifier(t.name, task_handler.scheduler) not in ("unknown", "system")
    ]
    valid_tasks_with_ids.sort(key=lambda x: x[0])
    grouped_tasks = {db_id: [item[1] for item in group] for db_id, group in groupby(valid_tasks_with_ids, key=lambda x: x[0])}
    return {"System": [{"name": "Init", "description": "初始化市场代码列表", "type": "system"}], **grouped_tasks}

# =============================================================================
# 优化点6: 静态文件服务 + WebSocket 主入口
# =============================================================================

@app.get("/{full_path:path}")
async def serve_static_files(full_path: str):
    if full_path.startswith("ws/") or full_path == "ws":
        return JSONResponse(status_code=404, content={"error": "WebSocket endpoint"})
    file_path = os.path.join(current_dir, full_path) if full_path else current_dir
    if os.path.isfile(file_path): return FileResponse(file_path)
    index_path = os.path.join(file_path, "index.html")
    if os.path.isfile(index_path): return FileResponse(index_path)
    root_index = os.path.join(current_dir, "index.html")
    if os.path.isfile(root_index): return FileResponse(root_index)
    return HTMLResponse(status_code=404, content="Not found")

@app.websocket("/ws/kline")
async def kline_websocket(websocket: WebSocket):
    """
    WebSocket 主入口：消息路由分发中心
    职责：解析消息 → 查找处理器 → 执行并返回结果
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if not data or not data.strip(): continue
            
            data_stripped = data.strip()
            if data_stripped == 'ping':
                await websocket.send_text(json.dumps({'type': 'pong'}))
                continue
            if data_stripped == 'pong': continue
            
            try:
                msg = json.loads(data)
                if msg.get('type') != 'request': continue
                
                req_id = msg.get('reqId')
                endpoint = msg.get('endpoint', '')
                params = msg.get('params', {}) if isinstance(msg.get('params'), dict) else {}
                
                # 解析 URL 查询参数 (兼容 /endpoint?key=value 格式)
                if '?' in endpoint:
                    base_endpoint, query_string = endpoint.split('?', 1)
                    query_params = parse_qs(query_string)
                    for k, v in query_params.items():
                        if k not in params: params[k] = v[0] if len(v) == 1 else v
                    endpoint = base_endpoint
                
                loop = asyncio.get_running_loop()
                
                # === 特殊处理：/logs/{task_name} 路径参数提取 ===
                if endpoint.startswith('/logs/') and endpoint not in _WS_ROUTES:
                    task_name = endpoint.split('/')[-1]
                    if task_name:
                        result = log_handler.get_task_logs(task_name, task_handler.scheduler)
                        await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                    else:
                        await websocket.send_text(json.dumps({'reqId': req_id, 'error': 'task_name required'}, default=str))
                    continue
                
                # === 路由分发：查表 → 执行 → 返回 ===
                handler = _WS_ROUTES.get(endpoint)
                if handler:
                    result = await handler(params, loop)
                    await websocket.send_text(json.dumps({'reqId': req_id, **result}, default=str))
                else:
                    await websocket.send_text(json.dumps({'reqId': req_id, 'error': f'Unknown endpoint: {endpoint}'}, default=str))
                    
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

# =============================================================================
# 生命周期管理
# =============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("Web panel startup. Running init...")
    asyncio.create_task(task_handler.run_init_task(update=False))
    task_handler.start_background_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    task_handler.bg_scheduler.shutdown()