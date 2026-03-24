"""
任务模块：定义任务类，并提供日志收集接口。
"""
import logging
from typing import Dict, List, Tuple, Callable


class LogCollector:
    """
    日志收集器：在任务执行期间捕获日志消息，并保留级别信息。
    """
    def __init__(self):
        self.logs: List[Tuple[int, str]] = []  # 存储 (levelno, formatted_message)
        self._handler = None

    def _create_handler(self):
        """创建自定义日志处理器，将日志记录存入列表。"""
        class ListHandler(logging.Handler):
            def __init__(self, log_list):
                super().__init__()
                self.log_list = log_list

            def emit(self, record):
                # 格式化消息，保留级别编号
                msg = self.format(record)
                self.log_list.append((record.levelno, msg))

        handler = ListHandler(self.logs)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        return handler

    def start(self):
        """开始收集日志。"""
        self._handler = self._create_handler()
        logging.getLogger().addHandler(self._handler)

    def stop(self):
        """停止收集日志。"""
        if self._handler:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None

    def get_logs(self) -> List[str]:
        """获取已收集的日志消息（不含级别）。"""
        return [msg for _, msg in self.logs]

    def get_logs_with_level(self) -> List[Tuple[int, str]]:
        """获取带级别的日志记录。"""
        return self.logs


class Task:
    """
    可执行任务的封装，包含元数据、执行方法及日志收集。
    """
    def __init__(self, name: str, description: str, task_type: str, executor: Callable, metadata: Dict = None):
        self.name = name
        self.description = description
        self.type = task_type
        self.executor = executor          # async callable
        self.metadata = metadata or {}
        self._log_collector = None

    async def execute(self, **kwargs) -> Dict:
        """
        执行任务，收集日志并返回结果。
        根据日志中的 WARNING 和 ERROR 级别决定任务状态。
        :param kwargs: 传递给 executor 的参数
        :return: 包含 status, result/error, logs 的字典
        """
        self._log_collector = LogCollector()
        self._log_collector.start()
        try:
            result = await self.executor(**kwargs)
            # 分析日志级别
            logs_with_level = self._log_collector.get_logs_with_level()
            has_error = any(level >= logging.ERROR for level, _ in logs_with_level)
            has_warning = any(level == logging.WARNING for level, _ in logs_with_level)
            if has_error:
                status = "failed"
            elif has_warning:
                status = "warning"
            else:
                status = "success"
            return {
                "status": status,
                "result": result,
                "logs": self._log_collector.get_logs()
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "logs": self._log_collector.get_logs()
            }
        finally:
            self._log_collector.stop()

    def get_logs(self):
        """返回最近一次执行的日志（若未执行则返回空列表）。"""
        return self._log_collector.get_logs() if self._log_collector else []