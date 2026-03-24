"""
任务调度器：基于任务（Task）进行并发执行，支持进度显示、资源锁，以及任务的加载与生命周期管理。
任务类需使用 @task 装饰器进行标记，不再强制继承任何基类。
"""
import os
import importlib
import inspect
import asyncio
from typing import List, Dict, Optional, Callable, Type

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .task import Task
from .config import MAX_CONCURRENCY


def task(description: str = ""):
    """
    装饰器，用于标记一个类为可调度任务。
    使用方式：
        @task(description="抓取A股日线数据")
        class MySpider:
            ...
    """
    def decorator(cls):
        cls._is_task = True
        if description:
            cls.description = description
        return cls
    return decorator


class ResourceLockManager:
    """全局资源锁管理器，防止同一资源的任务并发执行。"""
    _locks: Dict[str, asyncio.Lock] = {}

    @classmethod
    def get_lock(cls, resource_id: str) -> asyncio.Lock:
        if resource_id not in cls._locks:
            cls._locks[resource_id] = asyncio.Lock()
        return cls._locks[resource_id]


class Scheduler:
    """
    任务调度器。
    支持自动加载任务、并发执行多个任务，并提供进度条反馈、资源锁控制以及任务的终止功能。
    只需初始化一次实例，即可通过它获取任务、指定任务执行或者终止。
    """
    def __init__(self, max_concurrency: int = None, scan_paths: List[str] = None):
        self.max_concurrency = max_concurrency or MAX_CONCURRENCY
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            expand=True
        )

        # 任务工厂相关属性
        self.scan_paths = scan_paths or ["spider"]
        self.tasks: Dict[str, Task] = {}                  # 存储已加载的所有任务 (name -> Task)
        self._running_tasks: Dict[str, asyncio.Task] = {} # 存储运行中的任务以支持终止

        # 初始化时即扫描并加载任务
        self.load_tasks()

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
            # 检查是否有 @task 装饰器标记
            if not getattr(obj, '_is_task', False):
                continue

            # 提取描述信息（优先使用装饰器传入的 description，其次使用类属性 description）
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
        """根据任务名称获取任务对象。"""
        return self.tasks.get(name)

    def get_all_tasks(self) -> List[Task]:
        """获取所有已加载的任务列表。"""
        return list(self.tasks.values())

    async def run_tasks(self, task_names: List[str], **kwargs) -> Dict[str, Dict]:
        """
        并发执行指定的多个任务。
        :param task_names: 任务名称列表
        :param kwargs: 传递给每个任务执行器的参数
        :return: 字典，键为任务名，值为任务执行结果
        """
        tasks = [self.get_task(name) for name in task_names if self.get_task(name) is not None]
        if not tasks:
            return {}

        with self.progress:
            # 为每个任务创建进度条条目
            task_progress_ids = {}
            for task in tasks:
                task_id = self.progress.add_task(task.name, total=100)
                task_progress_ids[task] = task_id

            sem = asyncio.Semaphore(self.max_concurrency)

            async def run_one(task: Task):
                async with sem:
                    task_id = task_progress_ids[task]
                    # 获取资源锁（如果任务类定义了 resource 属性）
                    task_class = task.metadata.get("class")
                    resource = getattr(task_class, "resource", None) if task_class else None
                    lock = ResourceLockManager.get_lock(resource) if resource else None

                    async def execute():
                        exec_kwargs = kwargs.copy()
                        exec_kwargs['progress'] = self.progress
                        exec_kwargs['task_id'] = task_id
                        try:
                            result = await task.execute(**exec_kwargs)
                            if result['status'] == 'failed':
                                self.progress.update(task_id, description=f"{task.name} [red]ERROR")
                            elif result['status'] == 'warning':
                                self.progress.update(task_id, description=f"{task.name} [yellow]WARNING")
                            else:
                                self.progress.update(task_id, completed=100, description=f"{task.name} [green]DONE")
                            return result
                        except asyncio.CancelledError:
                            self.progress.update(task_id, description=f"{task.name} [yellow]CANCELLED")
                            raise

                    if lock:
                        async with lock:
                            return await execute()
                    else:
                        return await execute()

            # 注册 asyncio.Task 到字典中以支持外部指定终止
            for task in tasks:
                self._running_tasks[task.name] = asyncio.create_task(run_one(task))

            # 并发执行所有任务，收集异常且不阻断未被取消的任务
            results = await asyncio.gather(
                *[self._running_tasks[task.name] for task in tasks],
                return_exceptions=True
            )
            
            result_dict = {}
            for task, res in zip(tasks, results):
                self._running_tasks.pop(task.name, None)
                
                if isinstance(res, Exception):
                    if isinstance(res, asyncio.CancelledError):
                        result_dict[task.name] = {"status": "cancelled", "error": "Task was manually terminated"}
                    else:
                        result_dict[task.name] = {"status": "failed", "error": str(res)}
                else:
                    result_dict[task.name] = res
            return result_dict

    async def run_task(self, task_name: str, **kwargs) -> Dict:
        """运行单个任务。"""
        return await self.run_tasks([task_name], **kwargs)

    def terminate_task(self, task_name: str) -> bool:
        """
        指定终止正在运行的任务。
        :param task_name: 任务名称
        :return: 若该任务处于运行中并成功下发取消指令，返回 True
        """
        if task_name in self._running_tasks:
            self._running_tasks[task_name].cancel()
            return True
        return False