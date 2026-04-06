import logging
import asyncio
import contextvars
from typing import Dict, List, Tuple, Callable
from datetime import datetime
import pandas as pd
from .storage import save_dataframe
# 定义上下文变量，用于在并发环境中标识当前正在运行的任务
current_task_name: contextvars.ContextVar[str] = contextvars.ContextVar('current_task_name', default=None)
class LogCollector:
    """日志收集器，增加时间戳记录"""
    def __init__(self, task_name: str):
        self.logs: List[Tuple[int, str, datetime]] = []
        self._handler = None
        self.task_name = task_name  # 用于日志过滤
    def _create_handler(self):
        class ListHandler(logging.Handler):
            def __init__(self, log_list, task_name):
                super().__init__()
                self.log_list = log_list
                self.task_name = task_name
            def emit(self, record):
                # --- 核心修复：增加上下文过滤逻辑 ---
                # 获取当前上下文中的任务名
                active_task = current_task_name.get()
                # 只有当当前上下文的任务名与本处理器的任务名一致时，才记录日志
                # 这样可以防止并发运行时，任务A的日志被任务B的处理器捕获
                if active_task != self.task_name:
                    return
                msg = self.format(record)
                self.log_list.append((record.levelno, msg, pd.Timestamp.now()))
        handler = ListHandler(self.logs, self.task_name)
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
        # --- 核心修复：设置上下文变量 ---
        # 在当前异步上下文中标记正在运行的任务名称
        token = current_task_name.set(self.name)
        self._log_collector = LogCollector(self.name) # 传入 name 用于过滤
        self._log_collector.start()
        module_path = self.metadata.get('module', '')
        # 增加安全检查防止 index out of range
        parts = module_path.split('.')
        market = parts[1] if len(parts) > 1 else 'unknown'
        db_name = f"{market}_logs"
        try:
            result = await self.executor(**kwargs)
            logs_with_level = self._log_collector.get_logs_with_level()
            if any(level >= logging.ERROR for level, _, _ in logs_with_level):
                status = "failed"
            elif any(level == logging.WARNING for level, _, _ in logs_with_level):
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
            # --- 核心修复：清理上下文变量 ---
            current_task_name.reset(token)
            logs = self._log_collector.get_logs_with_level()
            if logs:
                df = pd.DataFrame(logs, columns=["level", "message", "date"])
                df["level"] = df["level"].map({
                    logging.DEBUG: "DEBUG", logging.INFO: "INFO",
                    logging.WARNING: "WARNING", logging.ERROR: "ERROR",
                    logging.CRITICAL: "CRITICAL"
                }).fillna("UNKNOWN")
                df = df[["date", "level", "message"]]
                # --- 关键修复：异步保存日志 ---
                # 使用 run_in_executor 防止写入数据库时阻塞 Web 服务
                loop = asyncio.get_running_loop()
                try:
                    # 注意：如果 save_dataframe 参数包含关键字参数，建议用 lambda 或 functools.partial
                    # 这里假设 save_dataframe(df, name, db, primary_key)
                    await loop.run_in_executor(
                        None, 
                        save_dataframe, 
                        df, self.name, db_name, ["date"]
                    )
                except Exception as e:
                    logging.error(f"Failed to save logs for {self.name}: {e}")
    def get_logs(self):
        return self._log_collector.get_logs() if self._log_collector else []