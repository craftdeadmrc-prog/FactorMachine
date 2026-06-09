import os
import logging
from typing import Dict, Any
from fastapi import HTTPException

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import load_dataframe, loadTable, dropTable

logger = logging.getLogger(__name__)


def get_db_name(task_name: str, scheduler) -> str:
    if task_name == "Init":
        raise ValueError("Init task has no market db")
    task = scheduler.get_task(task_name)
    if not task:
        raise ValueError(f"Task not found: {task_name}")

    module = task.metadata.get("module", "")
    parts = module.split(".")
    if len(parts) < 2:
        raise ValueError(f"Invalid task module path: {module}")

    db_name = parts[1]
    if not db_name or not db_name.isalnum() or not db_name.islower() or not (2 <= len(db_name) <= 20):
        raise ValueError(f"Invalid db name in module path: {module}")

    return db_name


def get_task_logs(task_name: str, scheduler) -> Dict[str, Any]:
    get_db_name(task_name, scheduler)

    sql = loadTable("*", task_name, "logs", "order by date desc limit 1000")
    if not sql:
        return {"logs": []}

    try:
        df = load_dataframe(sql, "logs")
        return {"logs": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Failed to load logs for {task_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def clear_task_logs(task_name: str, scheduler) -> Dict[str, Any]:
    get_db_name(task_name, scheduler)

    try:
        deleted = dropTable("logs", task_name)
        if not deleted:
            return {"ok": True, "message": f"No log table for {task_name}", "deleted": False}
        logger.info(f"Cleared logs for {task_name}")
        return {"ok": True, "message": f"Logs cleared for {task_name}", "deleted": True}
    except Exception as e:
        logger.error(f"Failed to clear logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
