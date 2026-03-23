"""
任务模块：定义任务类、任务工厂，并提供日志收集与任务获取接口。
"""
import os
import importlib
import inspect
import logging
from typing import Dict, List, Optional, Type, Callable, Any, Tuple


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


class TaskFactory:
    """
    任务工厂：扫描指定目录，加载任务类（需继承指定基类），并创建 Task 实例。
    """
    def __init__(self, scan_paths: List[str], base_classes: List[Type]):
        """
        :param scan_paths: 相对于项目根目录的扫描路径列表，如 ["spider"]
        :param base_classes: 任务类必须继承的基类列表，如 [BaseSpider]
        """
        self.scan_paths = scan_paths
        self.base_classes = base_classes
        self.tasks: Dict[str, Task] = {}   # name -> Task

    def load_tasks(self):
        """递归扫描所有路径，加载模块并构建任务对象。"""
        project_root = os.path.dirname(os.path.dirname(__file__))  # 项目根目录
        for path in self.scan_paths:
            full_dir = os.path.join(project_root, path)
            if not os.path.exists(full_dir):
                continue
            for root, _, files in os.walk(full_dir):
                for file in files:
                    if file.endswith(".py") and not file.startswith("_"):
                        self._load_module_from_file(root, file, project_root)

    def _load_module_from_file(self, root: str, file: str, project_root: str):
        """从单个文件加载模块，并提取任务类。"""
        rel_path = os.path.relpath(os.path.join(root, file), project_root)
        module_name = rel_path.replace(os.sep, ".")[:-3]  # 转为模块名
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(f"加载模块 {module_name} 失败: {e}")
            return

        for attr_name, obj in inspect.getmembers(module):
            if not inspect.isclass(obj):
                continue
            # 检查是否继承自任一基类且不是基类本身
            if not any(issubclass(obj, base) for base in self.base_classes):
                continue
            if any(obj is base for base in self.base_classes):
                continue

            # 提取描述信息（类属性 description）
            description = getattr(obj, "description", "无描述")
            # 确定任务类型（按第一级目录名）
            task_type = rel_path.split(os.sep)[0] if rel_path.split(os.sep) else "unknown"

            # 创建执行器：每次执行时实例化任务类，并调用其 run 方法
            async def executor(instance_class=obj, **exec_kwargs):
                # 提取 tasks 和 update（如果存在）
                tasks = exec_kwargs.get('tasks')
                update = exec_kwargs.get('update', False)
                # 创建实例，传递 tasks 和 update
                instance = instance_class(tasks=tasks, update=update)
                # 过滤出 run 方法接受的参数（progress, task_id）
                sig = inspect.signature(instance.run)
                valid_kwargs = {k: v for k, v in exec_kwargs.items() if k in sig.parameters}
                await instance.run(**valid_kwargs)
                return True

            executor.__name__ = f"{obj.__name__}_executor"

            task = Task(
                name=obj.__name__,
                description=description,
                task_type=task_type,
                executor=executor,
                metadata={"class": obj, "module": module_name}
            )
            self.tasks[task.name] = task


    def get_task(self, name: str) -> Optional[Task]:
        return self.tasks.get(name)

    def get_all_tasks(self) -> List[Task]:
        return list(self.tasks.values())


# 全局工厂实例
_task_factory = None


def init_task_factory(scan_paths: List[str] = None, base_classes: List[Type] = None):
    """
    初始化任务工厂。可自定义扫描路径和基类，若不指定则默认扫描 spider 目录并基于 BaseSpider。
    """
    global _task_factory
    if scan_paths is None:
        scan_paths = ["spider"]
    if base_classes is None:
        # 延迟导入，避免循环依赖
        from spider.base_spider import BaseSpider
        base_classes = [BaseSpider]
    _task_factory = TaskFactory(scan_paths, base_classes)
    _task_factory.load_tasks()


def get_task(name: str) -> Optional[Task]:
    """根据任务名称获取任务对象。"""
    if _task_factory is None:
        init_task_factory()
    return _task_factory.get_task(name)


def get_all_tasks() -> List[Task]:
    """获取所有已加载的任务列表。"""
    if _task_factory is None:
        init_task_factory()
    return _task_factory.get_all_tasks()