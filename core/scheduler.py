import os
import importlib
import inspect
import asyncio
import logging
from typing import List, Dict, Optional, Callable
from .task import Task
from .config import MAX_CONCURRENCY
logger = logging.getLogger(__name__)
def task(description: str = ""):
    def decorator(cls):
        cls._is_task = True
        if description:
            cls.description = description
        return cls
    return decorator
class ResourceLockManager:
    _locks: Dict[str, asyncio.Lock] = {}
    @classmethod
    def get_lock(cls, resource_id: str) -> asyncio.Lock:
        if resource_id not in cls._locks:
            cls._locks[resource_id] = asyncio.Lock()
        return cls._locks[resource_id]
class Scheduler:
    def __init__(self, max_concurrency: int = None, scan_paths: List[str] = None):
        self.max_concurrency = max_concurrency or MAX_CONCURRENCY
        self.scan_paths = scan_paths or ["spider"]
        self.tasks: Dict[str, Task] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        # 优化1: 信号量提升为实例属性，确保全局生效
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self.load_tasks()

    def load_tasks(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        for path in self.scan_paths:
            full_dir = os.path.join(project_root, path)
            if not os.path.exists(full_dir):
                continue
            for root, _, files in os.walk(full_dir):
                for file in files:
                    if file.endswith(".py") and not file.startswith("_"):
                        self._load_module_from_file(root, file, project_root)

    def _load_module_from_file(self, root: str, file: str, project_root: str):
        rel_path = os.path.relpath(os.path.join(root, file), project_root)
        module_name = rel_path.replace(os.sep, ".")[:-3]
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(f"加载模块 {module_name} 失败: {e}")
            return

        for attr_name, obj in inspect.getmembers(module):
            if not inspect.isclass(obj) or not getattr(obj, '_is_task', False):
                continue
            description = getattr(obj, "description", "无描述")
            task_type = rel_path.split(os.sep)[0] if rel_path.split(os.sep) else "unknown"

            async def executor(instance_class=obj, **exec_kwargs):
                tasks = exec_kwargs.get('tasks')
                update = exec_kwargs.get('update', False)
                instance = instance_class(tasks=tasks, update=update)
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

    async def run_tasks(self, task_names: List[str], **kwargs) -> Dict[str, Dict]:
        tasks = [self.get_task(name) for name in task_names if self.get_task(name) is not None]
        if not tasks:
            return {}
        async def run_one(task: Task):
            # 获取资源锁（如果需要）
            task_class = task.metadata.get("class")
            resource = getattr(task_class, "resource", None) if task_class else None
            lock = ResourceLockManager.get_lock(resource) if resource else None
 
            # 优化2: 调整锁顺序 - 先等资源，再占信号量
            # 这避免了占用并发名额去等待资源锁，从而允许其他不同资源的任务并行
            if lock:
                await lock.acquire()
            
            try:
                # 等待全局并发槽位
                async with self._sem:
                    async def execute():
                        logger.info(f"任务 {task.name} 开始执行")
                        try:
                            result = await task.execute(**kwargs)
                            status = result.get("status", "unknown")
                            logger.info(f"任务 {task.name} 执行结束，状态: {status}")
                            return result
                        except asyncio.CancelledError:
                            logger.warning(f"任务 {task.name} 被取消")
                            raise
 
                    return await execute()
            finally:
                # 确保释放资源锁
                if lock:
                    lock.release()
        # 创建所有任务
        for task in tasks:
            self._running_tasks[task.name] = asyncio.create_task(run_one(task))
        # 等待结果
        results = await asyncio.gather(*[self._running_tasks[task.name] for task in tasks])
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
        return await self.run_tasks([task_name], **kwargs)
    def terminate_task(self, task_name: str) -> bool:
        if task_name in self._running_tasks:
            self._running_tasks[task_name].cancel()
            return True
        return False