import abc
import logging
import pandas as pd
from typing import List, Dict, Optional
from core.storage import loadTable, load_dataframe

logger = logging.getLogger(__name__)


class BaseSpider(abc.ABC):
    resource = None
    table = None

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

    def loadTable(self, field, table, cond=""):
        return loadTable(field=field,table=table,db=self.market,cond=cond)

    def check(self):
        """批量检查任务列表中的符号是否已存在数据，过滤出缺失的任务"""
        if self.update:
            logger.info("update=True, skipping completeness check")
            return

        task_map = {task["symbol"]: task for task in self.tasks}
        symbols = list(task_map.keys())
        in_clause = "', '".join(symbols)

        try:
            sql = loadTable("top 1 date(date) as date",self.table,self.market,"order by date desc")
            df = load_dataframe(sql, self.market)
            if df.empty or pd.isna(df.loc[0, "date"]):
                logger.info(f"Table {self.table} has no data yet, will fetch all tasks")
                return
            latest_day = pd.to_datetime(df.loc[0, "date"]).strftime("%Y.%m.%d")
        except Exception as e:
            logger.error(f"Failed to query latest day: {e}, will fetch all tasks")
            return

        sql = loadTable(
            "distinct symbol, date(date) as date",
            self.table,
            self.market,
            f"where symbol IN ('{in_clause}') and date={latest_day}",
        )
        df = load_dataframe(sql, self.market)
        latest_day_symbols = (
            set(df["symbol"].tolist()) if not df.empty else set()
        )

        missing_symbols = sorted(set(symbols) - latest_day_symbols)
        if not missing_symbols:
            self.tasks = []
            logger.info(f"After check, {len(self.tasks)} tasks remain for {self.market}")
            return

        missing_in_clause = "', '".join(missing_symbols)
        sql = loadTable(
            ["symbol", "max(date(date)) as date"],
            self.table,
            self.market,
            f"where symbol IN ('{missing_in_clause}') group by symbol",
        )
        missing_dates_df = load_dataframe(sql, self.market)
        missing_start_dates = {}
        if not missing_dates_df.empty:
            missing_dates_df["date"] = pd.to_datetime(missing_dates_df["date"])
            missing_start_dates = (
                missing_dates_df.dropna(subset=["date"])
                .set_index("symbol")["date"]
                .to_dict()
            )
        new_tasks = []
        for symbol in missing_symbols:
            task = task_map[symbol]
            start_date = missing_start_dates.get(symbol)
            if start_date is not None and pd.notna(start_date):
                task["start_date"] = pd.Timestamp(start_date)
            new_tasks.append(task)
        self.tasks = new_tasks
        logger.info(f"After check, {len(self.tasks)} tasks remain for {self.market}")
