import os
import duckdb
import logging
from typing import Dict, Any
from fastapi import HTTPException

# 设置路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import load_dataframe
from core.config import DATA_PATH

logger = logging.getLogger(__name__)

def get_db_identifier(task_name: str, scheduler_instance) -> str:
    """
    根据任务名获取数据库标识符。
    严禁将变量命名为 market。
    """
    if task_name == "Init":
        return "system"
    task = scheduler_instance.get_task(task_name)
    if not task:
        return "unknown"
    module = task.metadata.get("module", "")
    parts = module.split(".")
    # 获取模块路径的第二部分作为数据库标识 (如 spider.ashare.xxx -> ashare)
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return "unknown"

def get_task_logs(task_name: str, scheduler_instance) -> Dict[str, Any]:
    """读取指定任务的日志"""
    db_identifier = get_db_identifier(task_name, scheduler_instance)
    # 关键修复：过滤 unknown 和 system 任务，避免返回无效数据
    if db_identifier in ("system", "unknown", "", None):
        if db_identifier == "system":
            return { "logs": [], "error": "System task logs are not stored in the standard log DB." }
        else:
            return { "logs": [], "error": f"Unknown task or invalid module path for {task_name}"}
    
    db_name = f"{db_identifier}_logs"
    sql = f'SELECT * FROM "{task_name}" ORDER BY date DESC LIMIT 1000'
    try:
        df = load_dataframe(sql, db=db_name)
        return { "logs": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Failed to load logs for {task_name}: {e}")
        return { "logs": [], "error": str(e)}

def clear_task_logs(task_name: str, scheduler_instance) -> Dict[str, str]:
    """清理指定任务的日志"""
    db_identifier = get_db_identifier(task_name, scheduler_instance)
    if db_identifier in ("system", "unknown", "", None):
        return { "message": "System or unknown tasks do not support log clearing via this endpoint." }
    
    db_name = f"{db_identifier}_logs"
    db_path = os.path.join(DATA_PATH, f"{db_name}.duckdb")
    if not os.path.exists(db_path):
        return { "message": "Log database does not exist." }
    try:
        con = duckdb.connect(db_path)
        con.execute(f'DELETE FROM "{task_name}"')
        con.close()
        logger.info(f"Cleared logs for {task_name}")
        return { "message": f"Logs cleared for {task_name}" }
    except Exception as e:
        logger.error(f"Failed to clear logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))