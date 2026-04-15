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
        sql = f"SELECT table_name FROM information_schema.tables WHERE table_name='{self.table_name}'"
        table_check = load_dataframe(sql,db=self.market)
        if table_check.empty:
            return
        symbols = [task['symbol'] for task in self.tasks]
        in_clause = "', '".join(symbols)
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
        # 第二段查询：批量获取已存在 symbol 的最大日期
        symbol_max_dates = {}
        if existing_symbols:
            # 针对已存在的 symbol 构建 IN 查询，一次性获取所有最大日期
            in_clause = "', '".join(existing_symbols)
            sql = f"""
                SELECT symbol, MAX(date) as date
                FROM {self.table_name}
                WHERE symbol IN ('{in_clause}')
                GROUP BY symbol
            """
            try:
                df_dates = load_dataframe(sql, db=self.market)
                if not df_dates.empty:
                    # 转换为字典映射 {symbol: max_date}
                    df_dates['date'] = pd.to_datetime(df_dates['date'])
                    symbol_max_dates = dict(zip(df_dates['symbol'], df_dates['date']))
            except Exception as e:
                logger.error(f"Failed to query max dates: {e}")
        # 遍历任务列表进行筛选
        now = pd.Timestamp.now().date()
        if pd.Timestamp.now().hour<=16:
            now = now-pd.Timedelta(days=1)
        if self.market!='crypto' and now.weekday() >= 5:  # 周末
            now = now - pd.Timedelta(days=(now.weekday() - 4))
        for task in self.tasks:
            symbol = task['symbol']
            # 情况1: symbol 不在数据库中，保留任务（全量获取）
            if symbol not in existing_symbols:
                new_tasks.append(task)
                continue
            # 情况2: symbol 在数据库中，检查日期
            newest_date = symbol_max_dates.get(symbol).date()
            # 如果能取到最新日期，进行判断
            if newest_date and not pd.isna(newest_date):
                if newest_date >= now:
                    skip_symbols.append(symbol)
                else:
                    # 未更新到最新，设置起始日期
                    task['start_date'] = newest_date
                    new_tasks.append(task)
            else:
                # 异常情况：symbol存在但未查到日期，为了保险起见也加入任务列表
                new_tasks.append(task)
        if skip_symbols:
            logger.info(f"Data for {skip_symbols} already complete, skipping")
        self.tasks = new_tasks
        logger.info(f"After check, {len(self.tasks)} tasks remain for {self.market}")