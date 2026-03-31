import asyncio
import logging
import os
import sys
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles  # 新增：用于挂载静态文件
# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
# 导入处理模块
from web import task_handler
from web import log_handler
from core.storage import load_dataframe
# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="FactorMachine Web Panel")
# ----------------------
# 静态文件挂载
# ----------------------
# 获取当前文件所在目录 (web/)
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
# ----------------------
# 路由：前端页面服务
# ----------------------
@app.get("/", response_class=HTMLResponse)
async def read_root():
    # index.html 现在位于 static 目录下
    file_path = os.path.join(current_dir, "static", "index.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"前端文件未找到: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()
# ----------------------
# 路由：API 接口
# ----------------------
@app.get("/api/tasks")
def get_all_tasks():
    """
    获取所有任务列表，按数据库标识分组
    """
    tasks = task_handler.scheduler.get_all_tasks()
    grouped = {
        "System": [
            {
                "name": "Init",
                "description": "初始化市场代码列表",
                "type": "system"
            }
        ]
    }
    for task in tasks:
        db_id = log_handler.get_db_identifier(task.name, task_handler.scheduler)
        if db_id == "unknown":
            continue
        if db_id not in grouped:
            grouped[db_id] = []
        grouped[db_id].append({
            "name": task.name,
            "description": task.description,
            "type": task.type
        })
    return grouped
@app.get("/api/status")
def get_status():
    """获取所有任务的当前状态"""
    return task_handler.get_status_info()
@app.post("/api/run")
async def run_tasks(payload: Dict[str, Any] = Body(...)):
    """
    执行选中的任务
    修复：支持多市场任务混合执行，每个任务使用自己对应的市场数据库。
    """
    import pandas as pd
    from datetime import datetime
    task_names = payload.get("task_names", [])
    symbols = payload.get("symbols") # 用户手动输入的代码列表
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    update = payload.get("update", False)
    if not task_names:
        raise HTTPException(status_code=400, detail="未选择任何任务")
    # 处理 Init 任务
    has_init = "Init" in task_names
    other_tasks = [t for t in task_names if t != "Init"]
    if has_init:
        logger.info("Running Init task...")
        asyncio.create_task(task_handler.run_init_task(update=True))
    if not other_tasks:
        return {"message": "Init task submitted."}
    # --- 核心修复：按市场分组任务 ---
    # 结构: { "ashare": [task_name1, task_name2], "crypto": [task_name3] }
    tasks_by_market: Dict[str, List[str]] = {}
    for task_name in other_tasks:
        db_id = log_handler.get_db_identifier(task_name, task_handler.scheduler)
        if db_id == "unknown":
            logger.warning(f"Task {task_name} has unknown market identifier, skipping.")
            continue
        if db_id not in tasks_by_market:
            tasks_by_market[db_id] = []
        tasks_by_market[db_id].append(task_name)
    if not tasks_by_market:
        raise HTTPException(status_code=400, detail="无法识别任务的市场类型")
    # --- 针对每个市场分别处理参数并提交 ---
    submission_count = 0
    for db_id, market_task_names in tasks_by_market.items():
        tasks_params = []
        try:
            # 1. 处理 Symbols 参数
            if not symbols:
                # 如果前端未填写 symbols，则从当前市场(db_id)的数据库读取
                sql = "SELECT market, symbol, date FROM symbols"
                df = load_dataframe(sql, db=db_id)
                if df.empty:
                    logger.warning(f"No symbols found in database for market: {db_id}")
                    continue # 该市场无数据，跳过该组任务
                for _, row in df.iterrows():
                    tasks_params.append({
                        "market": row["market"],
                        "symbol": row["symbol"],
                        "start_date": pd.to_datetime(start_date) if start_date else pd.to_datetime(row['date']), 
                        "end_date": pd.to_datetime(end_date) if end_date else pd.Timestamp.now().date()
                    })
            else:
                # 如果填写了 symbols，查询这些 symbols 在当前市场(db_id)数据库中的信息
                # 这样可以自动过滤掉不属于该市场的代码
                in_clause = "', '".join([s.replace("'", "''") for s in symbols])
                sql = f"SELECT market, symbol, date FROM symbols WHERE symbol IN ('{in_clause}')"
                df = load_dataframe(sql, db=db_id)
                if df.empty:
                    logger.info(f"Provided symbols not found in market {db_id}, skipping tasks for this market.")
                    continue
                for _, row in df.iterrows():
                    tasks_params.append({
                        "market": row["market"],
                        "symbol": row["symbol"],
                        "start_date": pd.to_datetime(start_date) if start_date else pd.to_datetime(row['date']),
                        "end_date": pd.to_datetime(end_date) if end_date else pd.Timestamp.now().date()
                    })
            # 2. 提交该市场下的所有任务
            if tasks_params:
                for task_name in market_task_names:
                    asyncio.create_task(task_handler.execute_task_internal(task_name, tasks_params, update))
                    submission_count += 1
        except Exception as e:
            logger.error(f"Failed to process tasks for market {db_id}: {e}")
            # 即使一个市场失败，也继续尝试其他市场
    return {"message": f"Tasks submitted. Total groups processed: {len(tasks_by_market)}."}
@app.delete("/api/logs/{task_name}")
def clear_task_logs(task_name: str):
    """清理指定任务的日志"""
    return log_handler.clear_task_logs(task_name, task_handler.scheduler)
@app.get("/api/logs/{task_name}")
def get_task_logs(task_name: str):
    """读取指定任务的日志"""
    return log_handler.get_task_logs(task_name, task_handler.scheduler)
# ----------------------
# 生命周期
# ----------------------
@app.on_event("startup")
async def startup_event():
    logger.info("Web panel startup. Running init...")
    asyncio.create_task(task_handler.run_init_task(update=False))
    task_handler.start_background_scheduler()
@app.on_event("shutdown")
async def shutdown_event():
    task_handler.bg_scheduler.shutdown()