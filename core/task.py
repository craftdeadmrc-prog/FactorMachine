# core/task.py

import logging
from typing import Dict, List, Tuple, Callable
from datetime import datetime
import pandas as pd
from .storage import save_dataframe

class LogCollector:
    """日志收集器，增加时间戳记录"""
    def __init__(self):
        self.logs: List[Tuple[int, str, datetime]] = []  # (levelno, msg, timestamp)
        self._handler = None

    def _create_handler(self):
        class ListHandler(logging.Handler):
            def __init__(self, log_list):
                super().__init__()
                self.log_list = log_list

            def emit(self, record):
                msg = self.format(record)
                self.log_list.append((record.levelno, msg, datetime.now()))
        handler = ListHandler(self.logs)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        return handler

    def start(self):
        self._handler = self._create_handler()
        logging.getLogger().addHandler(self._handler)

    def stop(self):
        if self._handler:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None

    def get_logs(self) -> List[str]:
        return [msg for _, msg, _ in self.logs]

    def get_logs_with_level(self) -> List[Tuple[int, str, datetime]]:
        return self.logs


class Task:
    def __init__(self, name: str, description: str, task_type: str, executor: Callable, metadata: Dict = None):
        self.name = name
        self.description = description
        self.type = task_type
        self.executor = executor
        self.metadata = metadata or {}
        self._log_collector = None

    async def execute(self, **kwargs) -> Dict:
        self._log_collector = LogCollector()
        self._log_collector.start()

        # 提前获取任务类及其可能的 market 属性
        module_path = self.metadata.get('module', '')
        market = module_path.split('.')[1]
        db_name = f"{market}_logs"

        try:
            result = await self.executor(**kwargs)
            logs_with_level = self._log_collector.get_logs_with_level()
            has_error = any(level >= logging.ERROR for level, _, _ in logs_with_level)
            has_warning = any(level == logging.WARNING for level, _, _ in logs_with_level)
            if has_error:
                status = "failed"
            elif has_warning:
                status = "warning"
            else:
                status = "success"
            return {
                "status": status,
                "result": result,
                "logs": [msg for _, msg, _ in logs_with_level]
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "logs": [msg for _, msg, _ in self._log_collector.get_logs_with_level()]
            }
        finally:
            self._log_collector.stop()
            # 将收集的日志写入数据库
            logs = self._log_collector.get_logs_with_level()
            if logs:
                df = pd.DataFrame(logs, columns=["level", "message", "date"])
                df["level"] = df["level"].map({logging.DEBUG: "DEBUG",
                                               logging.INFO: "INFO",
                                               logging.WARNING: "WARNING",
                                               logging.ERROR: "ERROR",
                                               logging.CRITICAL: "CRITICAL"}).fillna("UNKNOWN")
                df = df[["date", "level", "message"]]  # 确保顺序
                save_dataframe(df, self.name, db=db_name, primary_key=["date"])  # 不设主键，允许重复

    def get_logs(self):
        return self._log_collector.get_logs() if self._log_collector else []