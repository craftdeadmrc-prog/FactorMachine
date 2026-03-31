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
        if status == "failed":
            update_task_status(task_name, "failed")
        else:
            update_task_status(task_name, "success")
        logger.info(f"Task {task_name} execution finished with status: {status}")
    except Exception as e:
        logger.error(f"Error executing task {task_name}: {e}")
        update_task_status(task_name, "failed")
async def execute_default_scheduled_task(task_name: str):
    """
    执行定时任务的默认逻辑：
    1. 从数据库读取 symbols (market, symbol)
    2. start_date 和 end_date 处理默认值
    """
    logger.info(f"Starting default scheduled execution for {task_name}")
    # 获取数据库标识以查询 symbols
    # 这里需要引用 log_handler 的函数，避免循环导入，可以将 get_db_identifier 移到公共区域，
    # 或者在这里简单复制逻辑（为了模块独立，这里复用逻辑）
    task = scheduler.get_task(task_name)
    if not task:
        return
    module = task.metadata.get("module", "")
    parts = module.split(".")
    if len(parts) < 2:
        return
    db_identifier = parts[1]
    # 从数据库读取所有代码
    sql = "SELECT market, symbol, date FROM symbols"
    try:
        df = load_dataframe(sql, db=db_identifier)
        if df.empty:
            logger.warning(f"No symbols found for scheduled task {task_name}")
            return
        # 构造参数，日期为 None
        tasks_params = []
        for _, row in df.iterrows():
            tasks_params.append({
                "market": row["market"],
                "symbol": row["symbol"],
                "start_date": row["date"],
                "end_date": pd.Timestamp.now()
            })
        # 执行
        await execute_task_internal(task_name, tasks_params, update=True)
    except Exception as e:
        logger.error(f"Failed to prepare default task data for {task_name}: {e}")
def setup_scheduled_jobs():
    """
    设置默认定时任务：每日凌晨 2 点运行 (除 Init 外)
    """
    all_tasks = scheduler.get_all_tasks()
    for task in all_tasks:
        if task.name == "Init":
            continue
        job_id = f"daily_{task.name}"
        # 添加定时任务
        bg_scheduler.add_job(
            execute_default_scheduled_task,
            CronTrigger(hour=2, minute=0),
            id=job_id,
            args=[task.name],
            replace_existing=True
        )
        logger.info(f"Scheduled job added for {task.name} at 2:00 AM daily.")
def start_background_scheduler():
    """启动定时调度器"""
    bg_scheduler.start()
    setup_scheduled_jobs()
    logger.info("Background scheduler started.")
def get_status_info() -> Dict:
    """获取状态信息"""
    all_tasks = scheduler.get_all_tasks()
    status_list = []
    # Init 状态
    init_status = task_status_store.get("Init", {"status": "idle"})
    status_text = "Idle"
    color = "gray"
    if init_status["status"] == "running": status_text, color = "Running", "green"
    elif init_status["status"] == "success": status_text, color = "Success", "green"
    elif init_status["status"] == "failed": status_text, color = "Error", "red"
    status_list.append({"name": "Init", "color": color, "status": status_text, "type": "system"})
    # 其他任务状态
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
            last = task_status_store[name]["status"]
            if last == "failed": color, status_text = "red", "Error"
            elif last == "success": color, status_text = "green", "Success"
        status_list.append({"name": name, "color": color, "status": status_text, "type": task.type})
    jobs = []
    for job in bg_scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
        })
    return {"tasks": status_list, "schedules": jobs}