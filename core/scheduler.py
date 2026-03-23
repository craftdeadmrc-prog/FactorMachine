"""
任务调度器：基于任务（Task）进行并发执行，支持进度显示和资源锁。
"""
import asyncio
from typing import List, Dict, Optional

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .task import Task, get_task, get_all_tasks
from .config import MAX_CONCURRENCY


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
    支持并发执行多个任务，并提供进度条反馈和资源锁控制。
    """
    def __init__(self, max_concurrency: int = None):
        self.max_concurrency = max_concurrency or MAX_CONCURRENCY
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            expand=True
        )

    async def run_tasks(self, task_names: List[str], **kwargs) -> Dict[str, Dict]:
        """
        并发执行指定的多个任务。
        :param task_names: 任务名称列表
        :param kwargs: 传递给每个任务执行器的参数（如 start_date, end_date, progress, task_id 等）
        :return: 字典，键为任务名，值为任务执行结果（含 status、logs 等）
        """
        tasks = [get_task(name) for name in task_names if get_task(name) is not None]
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
                task_id = task_progress_ids[task]
                # 获取资源锁（若任务类定义了 resource 属性）
                task_class = task.metadata.get("class")
                resource = getattr(task_class, "resource", None) if task_class else None
                lock = ResourceLockManager.get_lock(resource) if resource else None

                async def execute():
                    # 将进度条对象和任务ID传递给执行器（部分任务可能需要）
                    exec_kwargs = kwargs.copy()
                    exec_kwargs['progress'] = self.progress
                    exec_kwargs['task_id'] = task_id
                    result = await task.execute(**exec_kwargs)
                    if result['status'] == 'failed':
                        self.progress.update(task_id, description=f"{task.name} [red]ERROR")
                    elif result['status'] == 'warning':
                        self.progress.update(task_id, description=f"{task.name} [yellow]WARNING")
                    else:
                        self.progress.update(task_id, completed=100, description=f"{task.name} [green]DONE")
                    return result

                if lock:
                    async with lock:
                        return await execute()
                else:
                    return await execute()

            # 并发执行所有任务，允许异常传播（通过 return_exceptions 收集）
            results = await asyncio.gather(*(run_one(task) for task in tasks), return_exceptions=True)
            result_dict = {}
            for task, res in zip(tasks, results):
                if isinstance(res, Exception):
                    result_dict[task.name] = {"status": "failed", "error": str(res)}
                else:
                    result_dict[task.name] = res
            return result_dict

    async def run_task(self, task_name: str, **kwargs) -> Dict:
        """运行单个任务。"""
        return await self.run_tasks([task_name], **kwargs)