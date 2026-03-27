import asyncio
import logging
import os
import sys
import duckdb
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.scheduler import Scheduler
from core.storage import load_dataframe
from core.config import DATA_PATH
# 新增导入 init 模块
from core import init as core_init

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FactorMachine Web Panel")

scheduler = Scheduler()
bg_scheduler = AsyncIOScheduler()
task_status_store: Dict[str, Dict[str, Any]] = {}

# ----------------------
# 数据模型
# ----------------------

class TaskExecutionRequest(BaseModel):
    task_names: List[str]
    symbols: List[str] 
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    update: bool = False

class ScheduleRequest(BaseModel):
    task_name: str
    cron_expression: str
    params: Dict

# ----------------------
# 辅助函数
# ----------------------

def update_task_status(task_name: str, status: str):
    task_status_store[task_name] = {
        "status": status,
        "last_run": datetime.now().isoformat()
    }

def get_market_from_task_name(task_name: str) -> str:
    """根据任务名推断市场 (ashare/fund/crypto)"""
    # 如果是 Init 任务，返回 system
    if task_name == "Init":
        return "system"
        
    task = scheduler.get_task(task_name)
    if not task:
        return "unknown"
    module = task.metadata.get("module", "")
    parts = module.split(".")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"

async def execute_task_wrapper(task_name: str, tasks_params: List[Dict], update: bool):
    """包装执行逻辑，用于更新状态和捕获异常"""
    update_task_status(task_name, "running")
    try:
        # Init 任务不经过 scheduler.run_tasks
        if task_name == "Init":
            await core_init.init(update=update)
            update_task_status(task_name, "success")
            return {"status": "success"}

        result = await scheduler.run_tasks([task_name], tasks=tasks_params, update=update)
        task_result = result.get(task_name, {})
        if task_result.get("status") == "failed":
            update_task_status(task_name, "failed")
        else:
            update_task_status(task_name, "success")
        logger.info(f"Web execution finished for {task_name}: {task_result}")
    except Exception as e:
        logger.error(f"Web execution error for {task_name}: {e}")
        update_task_status(task_name, "failed")

# ----------------------
# 路由：前端页面服务
# ----------------------

@app.get("/", response_class=HTMLResponse)
async def read_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
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
    获取所有任务列表，按大市场
    同时在最上方添加 System 组，包含 Init 任务
    """
    tasks = scheduler.get_all_tasks()
    
    # 初始化分组
    grouped = {
        "System": [
            {
                "name": "Init",
                "description": "初始化市场代码列表 (A Share / Fund / Crypto)",
                "type": "system"
            }
        ]
    }
    
    # 按市场分组普通任务
    for task in tasks:
        # 获取大市场名称
        market = get_market_from_task_name(task.name)
        
        if market == "unknown":
            continue # 跳过无法识别的任务
            
        if market not in grouped:
            grouped[market] = []
            
        grouped[market].append({
            "name": task.name,
            "description": task.description,
            "type": task.type
        })
        
    return grouped

@app.get("/api/status")
def get_status():
    """获取所有任务的当前状态"""
    # 获取普通任务
    all_tasks = scheduler.get_all_tasks()
    status_list = []
    
    # 1. 处理 Init 任务状态
    init_status = task_status_store.get("Init", {"status": "idle"})
    i_status_text = "Idle"
    i_color = "gray"
    
    if init_status.get("status") == "running":
        i_color = "green"
        i_status_text = "Running"
    elif init_status.get("status") == "success":
        i_color = "green"
        i_status_text = "Success"
    elif init_status.get("status") == "failed":
        i_color = "red"
        i_status_text = "Error"
        
    status_list.append({
        "name": "Init",
        "color": i_color,
        "status": i_status_text,
        "type": "system"
    })

    # 2. 处理其他任务
    running_names = set(scheduler._running_tasks.keys())
    
    for task in all_tasks:
        name = task.name
        is_running = name in running_names
        color = "gray"
        status_text = "Idle"
        
        if is_running:
            color = "green"
            status_text = "Running"
        elif name in task_status_store:
            last_status = task_status_store[name]["status"]
            if last_status == "failed":
                color = "red"
                status_text = "Error"
            elif last_status == "success":
                color = "green"
                status_text = "Success"
                
        status_list.append({
            "name": name,
            "color": color,
            "status": status_text,
            "type": task.type
        })
    
    jobs = []
    for job in bg_scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
        })
        
    return {
        "tasks": status_list,
        "schedules": jobs
    }

@app.post("/api/run")
async def run_tasks(request: TaskExecutionRequest, background_tasks: BackgroundTasks):
    """执行选中的任务，支持 Init 任务"""
    if not request.task_names:
         raise HTTPException(status_code=400, detail="未选择任何任务")

    # 检查是否包含 Init 任务
    has_init = "Init" in request.task_names
    other_tasks = [t for t in request.task_names if t != "Init"]

    # 1. 处理 Init 任务
    if has_init:
        logger.info("Running Init task...")
        # Init 任务不需要 symbols 和日期参数
        asyncio.create_task(execute_task_wrapper("Init", [], update=True))

    # 2. 处理其他普通爬虫/因子任务
    if other_tasks:
        # 推断市场：取第一个非 Init 任务的市场
        first_task = other_tasks[0]
        target_market = get_market_from_task_name(first_task)
        
        if target_market == "unknown":
             logger.warning(f"Cannot infer market for {first_task}, skipping standard tasks")

        constructed_tasks = []
        target_symbols = request.symbols
        
        # 如果未传 symbols，则全市场
        if not target_symbols:
            try:
                logger.info(f"No symbols provided, fetching all symbols for market: {target_market}")
                sql = "SELECT DISTINCT symbol FROM symbols"
                df_all = load_dataframe(sql, db=target_market)
                
                if df_all.empty:
                    logger.warning(f"Database empty for {target_market}. Standard tasks might fail.")
                else:
                    target_symbols = df_all['symbol'].tolist()
            except Exception as e:
                logger.error(f"Failed to load symbols: {e}")

        if target_symbols:
            # 构建参数
            if not request.start_date:
                try:
                    symbols_str = ",".join([f"'{s}'" for s in target_symbols])
                    sql = f"SELECT symbol, date FROM symbols WHERE symbol IN ({symbols_str})"
                    df_dates = load_dataframe(sql, db=target_market)
                    date_map = dict(zip(df_dates['symbol'], df_dates['date'])) if not df_dates.empty else {}
                    
                    for symbol in target_symbols:
                        s_date = date_map.get(symbol)
                        constructed_tasks.append({
                            "market": target_market,
                            "symbol": symbol,
                            "start_date": str(s_date) if pd.notna(s_date) else None,
                            "end_date": request.end_date
                        })
                except Exception as e:
                    logger.error(f"Date query failed: {e}")
            else:
                for symbol in target_symbols:
                    constructed_tasks.append({
                        "market": target_market,
                        "symbol": symbol,
                        "start_date": request.start_date,
                        "end_date": request.end_date
                    })

            # 启动任务
            for task_name in other_tasks:
                asyncio.create_task(execute_task_wrapper(task_name, constructed_tasks, request.update))

    return {"message": "Tasks submitted."}

@app.delete("/api/logs/{task_name}")
def clear_task_logs(task_name: str):
    """清理指定任务的日志"""
    try:
        market = get_market_from_task_name(task_name)
        if market == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Init 任务通常没有独立的日志数据库表，或者不在这里清理，视情况而定
        # 这里假设 Init 也不需要清理，或者它的日志在 core 层面处理了
        if market == "system":
            return {"message": "System tasks do not support log clearing via this endpoint."}

        db_name = f"{market}_logs"
        db_path = os.path.join(DATA_PATH, f"{db_name}.duckdb")
        
        if not os.path.exists(db_path):
            return {"message": "Log database does not exist."}

        con = duckdb.connect(db_path)
        try:
            con.execute(f'DELETE FROM "{task_name}"')
            logger.info(f"Cleared logs for {task_name}")
            return {"message": f"Logs cleared for {task_name}"}
        finally:
            con.close()
            
    except Exception as e:
        logger.error(f"Failed to clear logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/{task_name}")
def get_task_logs(task_name: str):
    """读取指定任务的日志"""
    try:
        market = get_market_from_task_name(task_name)
        
        # Init 任务不支持此查询
        if market == "system":
             return {"logs": [], "error": "System task logs are not stored in the standard log DB."}

        db_name = f"{market}_logs"
        sql = f"SELECT * FROM \"{task_name}\" ORDER BY date DESC LIMIT 1000"
        df = load_dataframe(sql, db=db_name)
        return {"logs": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Failed to load logs: {e}")
        return {"logs": [], "error": str(e)}

@app.post("/api/schedule")
def add_schedule(request: ScheduleRequest):
    """添加定时任务"""
    try:
        def job_wrapper():
            logger.info(f"Scheduled task {request.task_name} triggered.")
        
        bg_scheduler.add_job(
            job_wrapper, 
            'cron', 
            **parse_cron(request.cron_expression),
            id=f"{request.task_name}_{request.cron_expression}",
            replace_existing=True
        )
        return {"message": "Schedule added"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------
# 生命周期与工具函数
# ----------------------

@app.on_event("startup")
async def startup_event():
    # 1. 启动 APScheduler
    bg_scheduler.start()
    
    # 2. Web 面板启动时必须运行一次 Init
    logger.info("Web panel started. Running initialization task...")
    try:
        # await core_init.init(update=False)  # 非阻塞方式启动更好，或者直接 await
        # 为了保证启动时数据就绪，这里直接 await
        await core_init.init(update=False)
        logger.info("Initialization task completed on startup.")
    except Exception as e:
        logger.error(f"Initialization failed on startup: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    bg_scheduler.shutdown()

def parse_cron(expr: str):
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Invalid cron expression")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4]
    }