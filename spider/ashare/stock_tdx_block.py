import asyncio
import logging
from typing import Dict, List

import pandas as pd

from ..base_spider import BaseSpider
from core.scheduler import task
from core.storage import save_dataframe
from opentdx.const import BLOCK_FILE_TYPE, BOARD_TYPE
from core.config import TDX_CLIENT

logger = logging.getLogger(__name__)


@task(description="获取A股通达信概念和风格成份")
class StockTdxBlock(BaseSpider):
    resource = "ashare_tdx"
    table = "concept_tdx"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame):
        concept_cols = ["date", "symbol", "market", "concept", "concept_symbol"]
        style_cols = ["date", "symbol", "market", "style", "style_symbol"]
        if df is None or df.empty:
            return pd.DataFrame(columns=concept_cols), pd.DataFrame(columns=style_cols)

        task_market_map = dict(zip(df.loc[df["row_type"] == "task", "symbol"], df.loc[df["row_type"] == "task", "market"]))
        code_maps = {
            board_kind: group_df.drop_duplicates("name").set_index("name")["code"].to_dict()
            for board_kind, group_df in df[df["row_type"] == "board"].groupby("board_kind")
        }

        concept_records = []
        style_records = []
        for row in df[df["row_type"] == "block"].to_dict("records"):
            symbol = row["code"]
            if symbol not in task_market_map or task_market_map[symbol] not in {"sh", "sz"}:
                continue

            code_map = code_maps[row["board_kind"]]
            if row["blockname"] in code_map:
                board_code = code_map[row["blockname"]]
            else:
                matches = [name for name in code_map if name.startswith(row["blockname"])]
                board_code = code_map[matches[0]] if len(matches) == 1 else ""

            if row["board_kind"] == "concept":
                concept_records.append({
                    "date": row["date"],
                    "symbol": symbol,
                    "market": task_market_map[symbol],
                    "concept": row["blockname"],
                    "concept_symbol": board_code,
                })
            else:
                style_records.append({
                    "date": row["date"],
                    "symbol": symbol,
                    "market": task_market_map[symbol],
                    "style": row["blockname"],
                    "style_symbol": board_code,
                })

        return (
            pd.DataFrame(concept_records, columns=concept_cols).drop_duplicates().sort_values(["symbol", "date", "concept"]).reset_index(drop=True),
            pd.DataFrame(style_records, columns=style_cols).drop_duplicates().sort_values(["symbol", "date", "style"]).reset_index(drop=True),
        )

    def check(self):
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        def fetch_boards():
            q_client = TDX_CLIENT.q_client()
            concept_blocks = q_client.get_block_file(BLOCK_FILE_TYPE.GN) or []
            style_blocks = q_client.get_block_file(BLOCK_FILE_TYPE.FG) or []
            concept_boards = q_client.get_board_list(BOARD_TYPE.GN, count=41200) or []
            style_boards = q_client.get_board_list(BOARD_TYPE.FG, count=41200) or []
            return concept_blocks, style_blocks, concept_boards, style_boards

        try:
            concept_blocks, style_blocks, concept_boards, style_boards = await asyncio.to_thread(fetch_boards)
        except Exception as e:
            logger.error(f"获取通达信概念和风格数据失败: {e}")
            return

        if not concept_blocks and not style_blocks:
            logger.warning("通达信概念和风格成份数据为空")
            return

        date = pd.Timestamp.now().normalize()
        concept_df, style_df = self._rename_columns(pd.DataFrame(
            [{"row_type": "task", "symbol": task["symbol"], "market": task["market"]} for task in self.tasks]
            + [dict(row, row_type="block", board_kind="concept", date=date) for row in concept_blocks]
            + [dict(row, row_type="block", board_kind="style", date=date) for row in style_blocks]
            + [dict(row, row_type="board", board_kind="concept") for row in concept_boards]
            + [dict(row, row_type="board", board_kind="style") for row in style_boards]
        ))
        if concept_df.empty and style_df.empty:
            logger.warning("概念和风格成份过滤后为空")
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
            if not style_df.empty:
                await asyncio.to_thread(
                    save_dataframe,
                    style_df,
                    table="style_tdx",
                    db=self.market,
                    primary_key=["market", "symbol", "style", "date"],
                )
            logger.info(f"{self.__class__.__name__}: 保存概念 {len(concept_df)} 条，风格 {len(style_df)} 条")
        except Exception as e:
            logger.error(f"插入概念和风格成份数据失败: {e}")
