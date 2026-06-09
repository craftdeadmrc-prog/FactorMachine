# web/app.py
import asyncio
import logging
import os
import sys
import re
import json
from typing import List, Dict, Any, Callable, Awaitable
from itertools import groupby
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import pandas as pd
from core.storage import loadTable,load_dataframe

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from web import task_handler
from web import log_handler
from utils.data import bars

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入复权工具
from utils.data.fq_transfer import calculate_fq

app = FastAPI(title="FactorMachine Web Panel")
current_dir = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# 优化点1: WebSocket 路由注册表 + 装饰器
# =============================================================================

# 处理器类型别名：接收 (参数, 事件循环) 返回字典
WSHandler = Callable[[Dict[str, Any], asyncio.AbstractEventLoop], Awaitable[Dict[str, Any]]]

# 路由注册表：method -> handler function
WS_ROUTES: Dict[str, WSHandler] = {}

def ws_route(method: str):
    """
    装饰器：注册 WebSocket 业务处理器
    用法:
        @ws_route('kline.data')
        async def handle_kline_data(params, loop):
            return {"data": [...]}
    """
    def decorator(func: WSHandler) -> WSHandler:
        WS_ROUTES[method] = func
        logger.debug(f"Registered WS method: {method}")
        return func
    return decorator

def clean_orderbook_quote_values(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    for price_col in [name for name in df.columns if re.match(r'^[ab]\d+_p$', str(name))]:
        volume_col = price_col[:-2] + '_v'
        if volume_col not in df.columns:
            continue
        df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
        df[volume_col] = pd.to_numeric(df[volume_col], errors='coerce')
        df.loc[df[price_col] == 2147483648, price_col] = df.loc[df[price_col] == 2147483648, 'open']
        df.loc[(df[price_col] <= 0) & (df[volume_col] == 2147483648), volume_col] = 0
    return df

# =============================================================================
# 优化点4: 业务处理器 (每个函数职责单一，通过装饰器注册)
# =============================================================================

@ws_route('kline.data')
async def _handle_kline_data(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """处理 K 线数据查询请求"""
    market = params.get('market')
    interval = params.get('interval')
    symbol = params.get('symbol')
        
    table = f"kline_{interval}"
    start_date = params.get('start_date')
    end_date = params.get('end_date')
    adj = params.get('adj', 'none')
    year_cursor = params.get('year_cursor')
    
    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else pd.Timestamp.now()

    more_flag = False
    df = pd.DataFrame()
    total_count = 0

    sql = loadTable(["date","symbol","open","high","low","close","volume"],table,market,f"where symbol = '{symbol}'")
    if start_dt is not None:
        sql += f" and date >= {start_dt.strftime('%Y.%m.%d')}"
    if end_dt is not None:
        sql += f" and date <= {end_dt.strftime('%Y.%m.%d')}"
    
    if adj == 'none':
        if year_cursor is not None and interval!='1d':
            y = int(year_cursor)
            df = await loop.run_in_executor(None, load_dataframe, f"{sql} and year(date) = {y} order by date asc", market)
            ydf = await loop.run_in_executor(None, load_dataframe, f"select min(year(date)) as min_year from ({sql})", market)
            min_year = int(ydf.iloc[0, 0]) if not ydf.empty and pd.notna(ydf.iloc[0, 0]) else y
            more_flag = y > min_year
        else:
            df = await loop.run_in_executor(None, load_dataframe, f"{sql} order by date asc", market)
    else:
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if not df.empty:
            df = df.sort_values('date').reset_index(drop=True)
            try:
                have_adj = await loop.run_in_executor(None, load_dataframe, f"existsTable('dfs://{market}_day','adjust_factor')", market)
                if have_adj:
                    sql_factor = loadTable("*", "adjust_factor", market, f"where symbol = '{symbol}'")
                    df_factor = await loop.run_in_executor(None, load_dataframe, sql_factor, market)
                    if not df_factor.empty and "date" in df_factor.columns:
                        df_factor = df_factor.sort_values("date").reset_index(drop=True)
                    df = calculate_fq(df, df_factor, adj)
            except Exception as e:
                logger.warning(f"FQ error ({adj}): {e}")

    total_count = len(df)

    if df.empty:
        return {"data": [], "total": total_count,"more": False}

    df = df.sort_values('date').reset_index(drop=True)
    if 'date' in df.columns: df['date'] = df['date'].astype(str)
    records = df.to_dict(orient="records")
    
    return {
        "data": records,
        "total": total_count,
        "more": more_flag if adj == 'none' else False
    }

@ws_route('hft.data')
async def _handle_hft_data(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    market = params.get('market')
    interval = params.get('interval')
    symbol = params.get('symbol')
    mode = params.get('mode')
    threshold = params.get('threshold')
    adj = params.get('adj', 'none')
    start_date = params.get('start_date')
    end_date = params.get('end_date')

    if mode in {'cusum', 'volume'} and (threshold is None or float(threshold) <= 0):
        return {"error": "threshold must be positive"}

    table = f"kline_{interval}"
    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else pd.Timestamp.now()

    sql = loadTable(["date","symbol","open","high","low","close","volume"], table, market, f"where symbol = '{symbol}'")
    # sql = loadTable(["date","symbol","open","high","low","close","volume"], table, market, f"where symbol = '{symbol}'")
    if start_dt is not None:
        sql += f" and date >= {start_dt.strftime('%Y.%m.%d')}"
    if end_dt is not None:
        sql += f" and date <= {end_dt.strftime('%Y.%m.%d')}"

    df = await loop.run_in_executor(None, load_dataframe, f"{sql} order by date asc", market)
    if df.empty:
        return {"data": [], "total": 0}

    if adj != 'none':
        try:
            have_adj = await loop.run_in_executor(None, load_dataframe, f"existsTable('dfs://{market}_day','adjust_factor')", market)
            if have_adj:
                sql_factor = loadTable("*", "adjust_factor", market, f"where symbol = '{symbol}'")
                df_factor = await loop.run_in_executor(None, load_dataframe, sql_factor, market)
                if not df_factor.empty and "date" in df_factor.columns:
                    df_factor = df_factor.sort_values("date").reset_index(drop=True)
                df = calculate_fq(df, df_factor, adj)
        except Exception as error:
            logger.warning(f"HFT FQ error ({adj}): {error}")

    df = df.sort_values('date').reset_index(drop=True)

    if mode in {'cusum', 'volume'}:
        df = bars.generate_bars(df, bar_type=mode, threshold=float(threshold))
        if df is None:
            return {"error": "Bar generation failed"}
    else:
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()

    if 'date' in df.columns:
        df['date'] = df['date'].astype(str)
    return {"data": df.to_dict(orient="records"), "total": len(df)}

@ws_route('hft.tick')
async def _handle_hft_tick(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    market = params.get('market')
    symbol = params.get('symbol')
    mode = params.get('mode')
    adj = params.get('adj', 'none')
    start_date = params.get('start_date')
    end_date = params.get('end_date')

    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else pd.Timestamp.now()
    if start_dt is not None and end_dt < start_dt:
        return {"error": "end_date must be greater than or equal to start_date"}
    if mode == 'orderbook' and start_dt is not None and start_dt < (end_dt - pd.DateOffset(years=1)):
        return {"error": "orderbook mode supports at most 1 year"}
    table = "kline_1t"
    probe_sql = loadTable("*", table, market, f"where symbol = '{symbol}'")
    probe_df = await loop.run_in_executor(None, load_dataframe, f"{probe_sql} order by date desc limit 1", market)
    if probe_df.empty:
        return {"data": [], "total": 0}

    tick_columns = set(probe_df.columns.astype(str).tolist())
    selected_columns = ['date', 'open', 'volume']
    if market != 'index':
        selected_columns.append('action')
        selected_columns.append('trade_num')
    if mode == 'orderbook':
        orderbook_levels = sorted({
            int(match.group(2))
            for name in tick_columns
            if (match := re.match(r'^([ab])(\d+)_[pv]$', name))
        })
        for level in orderbook_levels:
            for side in ('a', 'b'):
                price_col = f'{side}{level}_p'
                volume_col = f'{side}{level}_v'
                if price_col in tick_columns:
                    selected_columns.append(price_col)
                if volume_col in tick_columns:
                    selected_columns.append(volume_col)

    sql = loadTable(selected_columns, table, market, f"where symbol = '{symbol}'")
    if start_dt is not None:
        sql += f" and date >= {start_dt.strftime('%Y.%m.%d')}"
    if end_dt is not None:
        sql += f" and date <= {end_dt.strftime('%Y.%m.%d')}"
    df = await loop.run_in_executor(None, load_dataframe, f"{sql} order by date asc", market)
    if df.empty:
        return {"data": [], "total": 0}
    if market == 'index':
        df['action'] = 'neutral'
        df['trade_num'] = 0
    df = clean_orderbook_quote_values(df)

    if adj != 'none':
        try:
            have_adj = await loop.run_in_executor(None, load_dataframe, f"existsTable('dfs://{market}_day','adjust_factor')", market)
            if have_adj:
                sql_factor = loadTable("*", "adjust_factor", market, f"where symbol = '{symbol}'")
                df_factor = await loop.run_in_executor(None, load_dataframe, sql_factor, market)
                if not df_factor.empty and "date" in df_factor.columns:
                    df_factor = df_factor.sort_values("date").reset_index(drop=True)
                df = calculate_fq(df, df_factor, adj)
        except Exception as error:
            logger.warning(f"HFT tick FQ error ({adj}): {error}")

    if 'date' in df.columns:
        df['date'] = df['date'].astype(str)
    return {"data": df.to_dict(orient='records'), "total": len(df), "columns": list(df.columns)}

@ws_route('hft.overview')
async def _handle_hft_overview(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    market = params.get('market')
    try:
        sql = loadTable(["symbol", "short_name"], "symbols", market, "order by symbol")
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        if df.empty:
            return {"data": []}
        return {"data": df[['symbol', 'short_name']].astype(object).where(pd.notna(df[['symbol', 'short_name']]), None).to_dict('records')}
    except Exception as error:
        logger.error(f"HFT overview error: {error}")
        return {"data": []}

@ws_route('kline.overview')
async def _handle_kline_overview(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """处理市场概览查询"""
    market, interval = params.get('market'), params.get('interval')
    try:
        sql = loadTable(["TOP 1 symbol", "open", "close", "date"], f"kline_{interval}", market, "context by symbol csort date desc")
        df = await loop.run_in_executor(None, load_dataframe, loadTable(["s.symbol", "s.short_name", "k.open", "k.close"], "symbols", market, f"s left join ({sql}) k on s.symbol = k.symbol order by s.symbol"), market)
        if df.empty: return {"data": []}
        df['pct_change'] = ((df['close'] - df['open']) / df['open'] * 100).round(2).where(df['open'].notna() & (df['open'] != 0) & df['close'].notna(), None)
        return {"data": df[['symbol', 'short_name', 'close', 'pct_change']].astype(object).where(pd.notna(df[['symbol', 'short_name', 'close', 'pct_change']]), None).to_dict('records')}
    except Exception as e:
        logger.error(f"Overview error: {e}")
        return {"data": []}

@ws_route('kline.symbols')
async def _handle_kline_symbols(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取市场股票代码列表"""
    market = params.get('market')
    try:
        sql = loadTable("distinct symbol", "symbols", market, "order by symbol")
        df = await loop.run_in_executor(None, load_dataframe, sql, market)
        return {"data": df['symbol'].tolist() if not df.empty else []}
    except Exception as e:
        logger.error(f"Failed to get symbols: {e}")
        return {"data": []}

@ws_route('kline.tables')
async def _handle_kline_tables(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取市场 K 线表结构"""
    market = params.get('market')
    try:
        sql = f"select * from loadTable('dfs://{market}_metadata', 'freq')"
        table_list = await loop.run_in_executor(None, load_dataframe, sql, market)
        if len(table_list)==0: return {"data": []}
        pattern = re.compile(r"^kline_(.+)$")
        names = [str(x).split("/")[-1] for x in table_list["table"]]
        tables = [{"interval": match.group(1), "table": name}
                 for name in names if (match := pattern.match(name))]
        return {"data": tables}
    except Exception as e:
        logger.error(f"Failed to get kline tables: {e}")
        return {"data": []}

@ws_route('status.get')
async def _handle_status(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取任务状态和调度信息"""
    return task_handler.get_status_info()

@ws_route('tasks.get')
async def _handle_tasks(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """获取所有可执行任务列表"""
    tasks = task_handler.scheduler.get_all_tasks()
    valid_tasks_with_db = [
        (log_handler.get_db_name(task.name, task_handler.scheduler), {
            "name": task.name, "description": task.description, "type": task.type
        })
        for task in tasks
        if task.name != "Init"
    ]
    valid_tasks_with_db.sort(key=lambda item: item[0])
    grouped_tasks = {
        db_name: [item[1] for item in group]
        for db_name, group in groupby(valid_tasks_with_db, key=lambda item: item[0])
    }
    return {"System": [{"name": "Init", "description": "初始化市场代码列表", "type": "system"}], **grouped_tasks}

@ws_route('tasks.run')
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
    tasks_with_db = sorted(
        [(log_handler.get_db_name(task_name, task_handler.scheduler), task_name) for task_name in other_tasks],
        key=lambda item: item[0]
    )
    tasks_by_market = {
        market: [item[1] for item in group]
        for market, group in groupby(tasks_with_db, key=lambda item: item[0])
    }
    
    if not tasks_by_market:
        return {"error": "No valid tasks found"}
    
    reference_date = pd.Timestamp.now()
    if pd.Timestamp.now().hour<=16:
        reference_date = reference_date-pd.Timedelta(days=1)    
    # 解析日期参数：优先使用传入值，否则应用参考日期
    parsed_start = pd.to_datetime(start_date) if start_date else None
    parsed_end = pd.to_datetime(end_date) if end_date else pd.to_datetime(reference_date)
    
    # === 内部异步函数：处理单个市场（避免全局污染）===
    async def _process_market(market: str, market_task_names: List[str]) -> int | None:
        try:
            # 构建 SQL：列表推导式构建 IN 子句，避免 for 循环
            in_clause = "', '".join([s.replace("'", "''") for s in symbols]) if symbols else None
            sql = (
                loadTable(["market","symbol","date"],"symbols",market, f" where symbol IN ('{in_clause}')")
                if in_clause
                else loadTable(["market","symbol", "date"], "symbols", market)
            )
            
            # 异步读取数据库（线程池执行同步操作）
            df = await loop.run_in_executor(None, load_dataframe, sql, market)
            if df.empty:
                logger.warning(f"No symbols found for market: {market}")
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
            logger.error(f"Failed to process tasks for market {market}: {e}")
            return None
    
    # === 并发处理所有市场：asyncio.gather 替代串行 for ===
    results = await asyncio.gather(*[
        _process_market(market, names)
        for market, names in tasks_by_market.items()
    ])
    
    # 统计成功提交的任务组数量
    total_count = sum(c for c in results if c is not None)
    
    return {"message": f"Tasks submitted. Total: {total_count}"}

@ws_route('logs.get')
async def _handle_logs_get(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    task_name = params.get("task_name")
    if not task_name:
        return {"error": "task_name required"}
    return log_handler.get_task_logs(task_name, task_handler.scheduler)

@ws_route('logs.clear')
async def _handle_logs_clear(params: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    task_name = params.get("task_name")
    if not task_name:
        return {"error": "task_name required"}
    return log_handler.clear_task_logs(task_name, task_handler.scheduler)


# =============================================================================
# 优化点6: 静态文件服务 + WebSocket 主入口
# =============================================================================

@app.get("/{full_path:path}")
async def serve_static_files(full_path: str):
    if full_path.startswith("ws/") or full_path == "ws":
        return JSONResponse(status_code=404, content={"error": "WebSocket endpoint"})
    file_path = os.path.join(current_dir, full_path) if full_path else current_dir
    for path in (file_path, os.path.join(file_path, "index.html"), os.path.join(current_dir, "index.html")):
        if os.path.isfile(path):
            response = FileResponse(path)
            response.headers["Cache-Control"] = "no-store"
            return response
    return HTMLResponse(status_code=404, content="Not found")

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """
    WebSocket 主入口：消息路由分发中心
    职责：解析消息 → 查找处理器 → 执行并返回结果
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if not data or not data.strip(): continue
            
            request_id = None
            try:
                msg = json.loads(data)
                if msg.get('type') != 'request': continue
                
                method = msg.get('method', '')
                params = msg.get('params', {}) if isinstance(msg.get('params'), dict) else {}
                request_id = msg.get('id')

                loop = asyncio.get_running_loop()

                if handler := WS_ROUTES.get(method):
                    result = await handler(params, loop)
                    await websocket.send_text(json.dumps({'id': request_id, 'type': 'response', **({'error': {'msg': result["error"]}} if isinstance(result, dict) and "error" in result else {'result': result})}, default=str))
                else:
                    await websocket.send_text(json.dumps({'id': request_id, 'type': 'response', 'error': {'msg': f'Unknown method: {method}'}}, default=str))
                    
            except json.JSONDecodeError as e:
                logger.error(f"WS JSON decode error: {e}")
                continue
            except Exception as e:
                logger.error(f"WS handler error: {e}", exc_info=True)
                await websocket.send_text(json.dumps({'id': request_id, 'type': 'response', 'error': {'msg': str(e)}}, default=str))
                
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

