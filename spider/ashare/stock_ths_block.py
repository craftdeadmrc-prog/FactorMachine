import asyncio
import logging
import multiprocessing
from typing import Dict, List

import pandas as pd

from ..base_spider import BaseSpider
from core.config import MAX_CONCURRENCY, THS_CONFIG
from core.scheduler import task
from core.storage import save_dataframe
from thsdk import THS

logger = logging.getLogger(__name__)


@task(description="获取A股同花顺行业和概念成份")
class StockThsBlock(BaseSpider):
    resource = "ashare_ths"
    table = "concept_ths"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _strip_prefix(self, value: str, prefix: str) -> str:
        value = str(value)
        return value[len(prefix):] if value.startswith(prefix) else value

    def _fetch_blocks(self, block_kind: str):
        try:
            ths = THS(THS_CONFIG)
            ths.connect()
            if block_kind == "industry":
                resp = ths.ths_industry()
            else:
                resp = ths.ths_concept()
            ths.disconnect()

            if not resp.data:
                logger.warning(f"同花顺{block_kind}板块为空")
                return []
            return [
                {
                    "block_kind": block_kind,
                    "block_code": row["代码"],
                    "block_name": row["名称"],
                }
                for row in resp.data
                if row.get("代码") and row.get("名称")
            ]
        except Exception as e:
            logger.error(f"获取同花顺{block_kind}板块失败: {e}")
            return []

    def _fetch_block_constituents(self, block: Dict):
        try:
            ths = THS(THS_CONFIG)
            ths.connect()
            resp = ths.block_constituents(block["block_code"])
            ths.disconnect()

            if not resp.data:
                logger.warning(f"同花顺板块 {block['block_code']} 无成份")
                return None
            return {
                "block_kind": block["block_kind"],
                "block_code": block["block_code"],
                "block_name": block["block_name"],
                "data": resp.data,
            }
        except Exception as e:
            logger.warning(f"获取同花顺板块 {block.get('block_code')} 成份失败: {e}")
            return None

    async def _run_multiprocess_batch(self, func, args_list):
        if not args_list:
            return []

        processes = len(args_list)
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=processes) as pool:
            async_results = [pool.apply_async(func, args=args) for args in args_list]
            while True:
                if all(r.ready() for r in async_results):
                    break
                await asyncio.sleep(0.05)
            return [r.get() for r in async_results]

    def _rename_columns(self, df: pd.DataFrame):
        concept_cols = ["date", "symbol", "market", "concept", "concept_symbol"]
        industry_cols = ["date", "symbol", "market", "industry", "industry_symbol"]
        if df is None or df.empty:
            return pd.DataFrame(columns=concept_cols), pd.DataFrame(columns=industry_cols)

        task_market_map = dict(zip(df.loc[df["row_type"] == "task", "symbol"], df.loc[df["row_type"] == "task", "market"]))
        concept_records = []
        industry_records = []
        for row in df[df["row_type"] == "constituent"].to_dict("records"):
            symbol = self._strip_prefix(row["code"], str(row["code"])[:4])
            if symbol not in task_market_map or task_market_map[symbol] not in {"sh", "sz"}:
                continue

            block_symbol = self._strip_prefix(row["block_code"], "URFI")
            if row["block_kind"] == "concept":
                concept_records.append({
                    "date": row["date"],
                    "symbol": symbol,
                    "market": task_market_map[symbol],
                    "concept": row["block_name"],
                    "concept_symbol": block_symbol,
                })
            else:
                industry_records.append({
                    "date": row["date"],
                    "symbol": symbol,
                    "market": task_market_map[symbol],
                    "industry": row["block_name"],
                    "industry_symbol": block_symbol,
                })

        return (
            pd.DataFrame(concept_records, columns=concept_cols).drop_duplicates().sort_values(["symbol", "date", "concept"]).reset_index(drop=True),
            pd.DataFrame(industry_records, columns=industry_cols).drop_duplicates().sort_values(["symbol", "date", "industry"]).reset_index(drop=True),
        )

    def check(self):
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        try:
            block_results = await self._run_multiprocess_batch(
                self._fetch_blocks,
                [("industry",), ("concept",)],
            )
        except Exception as e:
            logger.error(f"获取同花顺行业和概念板块失败: {e}")
            return

        blocks = [block for result in block_results for block in result]
        if not blocks:
            logger.warning("同花顺行业和概念板块为空")
            return

        results = []
        batch_size = MAX_CONCURRENCY
        block_args = [(block,) for block in blocks]
        for i in range(0, len(block_args), batch_size):
            batch_results = await self._run_multiprocess_batch(self._fetch_block_constituents, block_args[i:i+batch_size])
            results.extend([r for r in batch_results if r is not None])

        if not results:
            logger.warning("同花顺行业和概念成份数据为空")
            return

        date = pd.Timestamp.today().normalize()
        rows = [{"row_type": "task", "symbol": task["symbol"], "market": task["market"]} for task in self.tasks]
        for result in results:
            rows.extend([
                {
                    "row_type": "constituent",
                    "block_kind": result["block_kind"],
                    "block_code": result["block_code"],
                    "block_name": result["block_name"],
                    "code": row["代码"],
                    "name": row["名称"],
                    "date": date,
                }
                for row in result["data"]
                if row.get("代码")
            ])

        concept_df, industry_df = self._rename_columns(pd.DataFrame(rows))
        if concept_df.empty and industry_df.empty:
            logger.warning("同花顺行业和概念成份过滤后为空")
            return

        try:
            if not concept_df.empty:
                await asyncio.to_thread(
                    save_dataframe,
                    concept_df,
                    table=self.table,
                    db=self.market,
                    primary_key=["market", "symbol", "concept", "date"],
                )
            if not industry_df.empty:
                await asyncio.to_thread(
                    save_dataframe,
                    industry_df,
                    table="industry_ths",
                    db=self.market,
                    primary_key=["market", "symbol", "industry", "date"],
                )
            logger.info(f"{self.__class__.__name__}: 保存概念 {len(concept_df)} 条，行业 {len(industry_df)} 条")
        except Exception as e:
            logger.error(f"插入同花顺行业和概念成份数据失败: {e}")
