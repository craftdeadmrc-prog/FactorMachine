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
        return 'unknown'

    def _is_data_complete(self, symbol: str) -> bool:
        sql = f"""
            SELECT 1
            FROM {self.table_name}
            WHERE symbol = '{symbol}'
            LIMIT 1
        """
        try:
            df = load_dataframe(sql, market=self.market)
            return not df.empty
        except Exception as e:
            logger.error(f"Failed to check completeness for {symbol}: {e}")
            return False

    def check(self):
        if self.update:
            logger.info("update=True, skipping completeness check")
            return

        new_tasks = []
        for task in self.tasks:
            symbol = task['symbol']
            if self._is_data_complete(symbol):
                logger.info(f"Data for {symbol} already complete, skipping")
            else:
                new_tasks.append(task)

        self.tasks = new_tasks
        logger.info(f"After check, {len(self.tasks)} tasks remain for {self.market}")