import asyncio
import logging
import os
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 设置路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.scheduler import Scheduler
from core.storage import load_dataframe
from core import init as core_init

logger = logging.getLogger(__name__)

# 核心调度器实例
scheduler = Scheduler()

# 定时任务调度器 (仅用于触发，实际执行由 core.scheduler 完成)
bg_scheduler = AsyncIOScheduler()

# 任务状态存储
task_status_store: Dict[str, Dict[str, Any]] = {}

def update_task_status(task_name: str, status: str):
    task_status_store[task_name] = {
        "status": status,
        "last_run": pd.Timestamp.now()
    }

async def run_init_task(update: bool = False):
    """执行 Init 任务"""
    update_task_status("Init", "running")
    try:
        await core_init.init(update=update)
        update_task_status("Init", "success")
        logger.info("Init task finished successfully.")
    except Exception as e:
        update_task_status("Init", "failed")
        logger.error(f"Init task failed: {e}")

async def execute_task_internal(task_name: str, tasks_params: List[Dict], update: bool):
    """
    内部执行逻辑：通过 scheduler.get_task 获取任务，然后运行。
    不自行创建线程或复杂的请求类。
    """
    update_task_status(task_name, "running")
    try:
        # 获取任务对象
        task = scheduler.get_task(task_name)
        if not task:
            logger.error(f"Task {task_name} not found in scheduler.")
            update_task_status(task_name, "failed")
            return
        # 直接调用 scheduler.run_tasks 执行
        result = await scheduler.run_tasks([task_name], tasks=tasks_params, update=update)
        task_result = result.get(task_name, {})
        status = task_result.get("status", "success")
        update_task_status(task_name, "success" if status != "failed" else "failed")
        logger.info(f"Task {task_name} execution finished with status: {status}")
    except Exception as e:
        logger.error(f"Error executing task {task_name}: {e}")
        update_task_status(task_name, "failed")

async def execute_default_scheduled_task(task_name: str):
    """
    执行定时任务的默认逻辑
    修复：数据库读取放入线程池
    """
    logger.info(f"Starting default scheduled execution for {task_name}")
    task = scheduler.get_task(task_name)
    if not task:
        return
    module = task.metadata.get("module", "")
    parts = module.split(".")
    if len(parts) < 2:
        return
    db_identifier = parts[1]
    sql = "SELECT market, symbol, date FROM symbols"
    # --- 关键修复：异步读取数据库 ---
    loop = asyncio.get_running_loop()
    try:
        # 将同步的 load_dataframe 放入线程池
        df = await loop.run_in_executor(None, load_dataframe, sql, db_identifier)
        
        if df.empty:
            logger.warning(f"No symbols found for scheduled task {task_name}")
            return

        df['end_date'] = pd.Timestamp.now()
        df = df.rename(columns={'date': 'start_date'})
        tasks_params = df[['market', 'symbol', 'start_date', 'end_date']].to_dict('records')

        await execute_task_internal(task_name, tasks_params, update=True)
    except Exception as e:
        logger.error(f"Failed to prepare default task data for {task_name}: {e}")

def setup_scheduled_jobs():
    """
    设置默认定时任务：每日凌晨 2 点运行 (除 Init 外)
    优化点：使用列表推导式替代 for 循环进行任务注册
    """
    all_tasks = scheduler.get_all_tasks()
    # 使用列表推导式遍历并执行副作用（注册任务）
    # 过滤掉 Init 任务
    [
        (
            bg_scheduler.add_job(
                execute_default_scheduled_task,
                CronTrigger(hour=2, minute=0),
                id=f"daily_{task.name}",
                args=[task.name],
                replace_existing=True
            ),
            logger.info(f"Scheduled job added for {task.name} at 2:00 AM daily.")
        )
        for task in all_tasks if task.name != "Init"
    ]

def start_background_scheduler():
    """启动定时调度器"""
    bg_scheduler.start()
    setup_scheduled_jobs()
    logger.info("Background scheduler started.")

def get_status_info() -> Dict:
    """获取状态信息"""
    all_tasks = scheduler.get_all_tasks()
    running_names = set(scheduler._running_tasks.keys())
    
    # --- 优化点：封装状态判断逻辑 ---
    def get_task_status_detail(task):
        name = task.name
        is_running = name in running_names
        # 确定状态文本和颜色
        if is_running:
            status_text, color = "Running", "green"
        else:
            last = task_status_store.get(name, {}).get("status")
            if last == "failed":
                status_text, color = "Error", "red"
            elif last == "success":
                status_text, color = "Success", "green"
            else:
                status_text, color = "Idle", "gray"
        return { "name": name, "color": color, "status": status_text, "type": task.type}
    
    # --- 优化点：列表推导式构建状态列表 ---
    # 1. 处理 Init 状态
    init_status_val = task_status_store.get("Init", {}).get("status", "idle")
    status_map = { "running": ("Running", "green"), "success": ("Success", "green"), "failed": ("Error", "red")}
    status_text, color = status_map.get(init_status_val, ("Idle", "gray"))
    init_item = [{ "name": "Init", "color": color, "status": status_text, "type": "system"}]
    
    # 2. 处理其他任务 (过滤掉 Init 以避免重复，如果 all_tasks 中包含它)
    other_items = [get_task_status_detail(t) for t in all_tasks if t.name != "Init"]
    
    status_list = init_item + other_items
    
    # --- 优化点：列表推导式构建调度列表 ---
    jobs = [
        {
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
        }
        for job in bg_scheduler.get_jobs()
    ]
    return { "tasks": status_list, "schedules": jobs}