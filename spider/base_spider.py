import abc
import logging
import pandas as pd
from typing import List, Dict, Optional
from datetime import date, datetime
from core.storage import load_dataframe

logger = logging.getLogger(__name__)


class BaseSpider(abc.ABC):
    resource = None
    table_name = None

    def __init__(self, tasks: Optional[List[Dict]] = None, update: bool = False):
        self.market = self._get_market_from_path()
        self.tasks = tasks if tasks is not None else []
        self.update = update

        self._data_columns_cache = {}

        if not self.update:
            self.check()

    @abc.abstractmethod
    async def run(self, progress=None, task_id=None):
        pass

    @abc.abstractmethod
    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        pass

    @classmethod
    def _get_market_from_path(cls) -> str:
        module_parts = cls.__module__.split('.')
        if len(module_parts) >= 2 and module_parts[0] == 'spider':
            return module_parts[1]

    def check(self):
        """批量检查任务列表中的符号是否已存在数据，过滤出缺失的任务"""
        if self.update:
            logger.info("update=True, skipping completeness check")
            return

        if not self.tasks:
            return

        # 收集所有 symbol
        symbols = [task['symbol'] for task in self.tasks]
        # 转义单引号防止 SQL 注入（虽然符号来自内部，但保持规范）
        escaped_symbols = [s.replace("'", "''") for s in symbols]
        in_clause = "', '".join(escaped_symbols)
        sql = f"""
            SELECT DISTINCT symbol
            FROM {self.table_name}
            WHERE symbol IN ('{in_clause}')
        """
        try:
            df = load_dataframe(sql, db=self.market)
            existing_symbols = set(df['symbol'].tolist()) if not df.empty else set()
        except Exception as e:
            error_msg = str(e)
            # 表不存在是正常情况（首次运行），使用 INFO 级别
            if "does not exist" in error_msg.lower():
                logger.info(f"Table {self.table_name} not initialized yet, will fetch all tasks")
            else:
                logger.error(f"Failed to query existing symbols: {e}, will re-fetch all tasks")
            existing_symbols = set()

        new_tasks = []
        skip_symbols = []
        for task in self.tasks:
            symbol = task['symbol']
            if symbol in existing_symbols:
                skip_symbols.append(symbol)
            else:
                new_tasks.append(task)

        if skip_symbols:
            logger.info(f"Data for {skip_symbols} already complete, skipping")
        self.tasks = new_tasks
        logger.info(f"After check, {len(self.tasks)} tasks remain for {self.market}")