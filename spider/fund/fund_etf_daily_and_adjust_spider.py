import asyncio
import logging
import threading
import numpy as np
import pandas as pd
import akshare as ak
from typing import List, Dict, Optional

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.config import MAX_CONCURRENCY, TDX_CLIENT
from core.proxy import proxy_pool
from core.scheduler import task
from opentdx.const import MARKET, PERIOD

logger = logging.getLogger(__name__)


@task(description="获取ETF日线行情（TDX）及前后复权因子")
class EtfDailyAndAdjustSpider(BaseSpider):
    resource = "fund_eastmoney"
    table = "kline_1d"

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "datetime": "date",
            "vol": "volume",
        }
        df = df.rename(columns=rename_map)
        df = df.drop(columns=["float_shares", "turnover"], errors="ignore")

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"] = symbol
        df["market"] = market
        df = df[["symbol", "date", "open", "high", "low", "close", "volume", "amount", "market"]]
        df = df.dropna(subset=["date", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def _has_large_kline_change(self, df: pd.DataFrame) -> bool:
        base = df[["date", "close"]].dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if len(base) < 2:
            return False
        close = pd.to_numeric(base["close"], errors="coerce")
        pre_close = close.shift(1)
        change_ratio = ((close - pre_close) / pre_close).abs()
        change_ratio = change_ratio[(pre_close > 0) & np.isfinite(change_ratio)]
        return bool((change_ratio > 0.5).any())

    def _filter_abnormal_zero_volume_kline(self, df: pd.DataFrame) -> pd.DataFrame:
        open_price = pd.to_numeric(df["open"], errors="coerce")
        volume = pd.to_numeric(df["volume"], errors="coerce")
        abnormal_mask = (open_price > 10) & (volume == 0)
        if not abnormal_mask.any():
            return df
        return df.loc[~abnormal_mask].reset_index(drop=True)

    def _rename_split_detail_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["拆分折算日", "拆分折算"])

        split_df = df.copy()
        ratio_parts = split_df["拆分折算比例"].astype(str).str.extract(r"^\s*([0-9.]+)\s*:\s*([0-9.]+)\s*$")
        split_df["split_base"] = pd.to_numeric(ratio_parts[0], errors="coerce")
        split_df["split_target"] = pd.to_numeric(ratio_parts[1], errors="coerce")
        split_df["拆分折算日"] = pd.to_datetime(split_df["拆分折算日"], errors="coerce")
        split_df["拆分折算"] = split_df["split_target"] / split_df["split_base"]
        split_df = split_df.replace([np.inf, -np.inf], np.nan)
        split_df = split_df.dropna(subset=["拆分折算日", "拆分折算"])
        split_df = split_df[(split_df["split_base"] > 0) & (split_df["拆分折算"] > 0)]
        split_df = split_df.groupby("拆分折算日", as_index=False)["拆分折算"].prod()
        return split_df[["拆分折算日", "拆分折算"]]

    def _build_adjust_factor(self, df: pd.DataFrame, symbol: str, market: str, div_df: pd.DataFrame, split_df: pd.DataFrame) -> pd.DataFrame:
        base = df[["date", "close"]].dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if base.empty:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])

        if div_df is None or div_df.empty:
            div_df = pd.DataFrame(columns=["date", "cash_div"])
        else:
            div_df = div_df.copy()
            div_df["date"] = pd.to_datetime(div_df["日期"], errors="coerce")
            div_df["cum_div"] = pd.to_numeric(div_df["累计分红"], errors="coerce")
            div_df = div_df.dropna(subset=["date", "cum_div"]).sort_values("date").reset_index(drop=True)
            div_df["cash_div"] = div_df["cum_div"].diff()
            if len(div_df) > 0:
                div_df.loc[div_df.index[0], "cash_div"] = div_df.loc[div_df.index[0], "cum_div"]
            div_df["cash_div"] = div_df["cash_div"].clip(lower=0).fillna(0.0)
            div_df = div_df[["date", "cash_div"]]

        if split_df is None or split_df.empty:
            split_df = pd.DataFrame(columns=["date", "split_ratio"])
        else:
            split_df = split_df.copy()
            split_df["date"] = pd.to_datetime(split_df["拆分折算日"], errors="coerce")
            split_df["split_ratio"] = pd.to_numeric(split_df["拆分折算"], errors="coerce")
            split_df = split_df.dropna(subset=["date", "split_ratio"])
            split_df = split_df.groupby("date", as_index=False)["split_ratio"].prod()

        events = pd.merge(div_df, split_df, on="date", how="outer").rename(columns={"date": "event_date"})
        if events.empty:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])
        events["cash_div"] = pd.to_numeric(events.get("cash_div", 0.0), errors="coerce").fillna(0.0)
        events["split_ratio"] = pd.to_numeric(events.get("split_ratio", 1.0), errors="coerce").fillna(1.0)
        events = events.sort_values("event_date")

        trade_dates = base["date"].to_numpy()
        idxs = np.searchsorted(trade_dates, events["event_date"].to_numpy(), side="left")
        events = events.loc[idxs < len(base)].copy()
        events["idx"] = idxs[idxs < len(base)]
        events = events[events["idx"] > 0]
        if events.empty:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])
        events["trade_date"] = events["idx"].map(lambda i: base.iloc[int(i)]["date"])
        events = events.groupby(["trade_date", "idx"], as_index=False).agg(
            event_date=("event_date", "min"),
            cash_div=("cash_div", "sum"),
            split_ratio=("split_ratio", "prod"),
        ).sort_values("idx").reset_index(drop=True)

        close = base["close"].to_numpy(dtype=float)
        n = len(base)
        picked_idx = []
        for _, e in events.iterrows():
            i0 = int(e["idx"])
            d = float(e["cash_div"])
            r = float(e["split_ratio"])
            best_i = i0
            best_gap = np.inf
            for i in [i0, min(i0 + 1, n - 1)]:
                if i <= 0 or i >= n:
                    continue
                pre = float(close[i - 1])
                cur = float(close[i])
                if not np.isfinite(pre) or not np.isfinite(cur) or pre <= 1e-12:
                    continue
                gap = min(abs(cur - (pre - d) / r), abs(cur - (pre - d) * r))
                if gap < best_gap:
                    best_gap = gap
                    best_i = i
            picked_idx.append(best_i)
        events["idx"] = picked_idx
        events["trade_date"] = events["idx"].map(lambda i: base.iloc[int(i)]["date"])
        events = events.groupby(["trade_date", "idx"], as_index=False).agg(
            event_date=("event_date", "min"),
            cash_div=("cash_div", "sum"),
            split_ratio=("split_ratio", "prod"),
        ).sort_values("idx").reset_index(drop=True)

        right_factor = np.ones(n, dtype=float)
        for _, e in events.iterrows():
            idx = int(e["idx"])
            if idx <= 0 or idx >= n:
                continue
            pre_close = float(close[idx - 1])
            cur_close = float(close[idx])
            if not np.isfinite(pre_close) or pre_close <= 1e-12 or not np.isfinite(cur_close):
                continue
            cash_div = float(e["cash_div"])
            split_ratio = float(e["split_ratio"])
            pred_a = (pre_close - cash_div) / split_ratio
            pred_b = (pre_close - cash_div) * split_ratio
            if abs(cur_close - pred_b) < abs(cur_close - pred_a):
                split_ratio = 1.0 / split_ratio if split_ratio != 0 else 1.0
            rf = ((pre_close - cash_div) / split_ratio) / pre_close
            if np.isfinite(rf) and rf > 0:
                right_factor[idx] = rf

        qfq_factor = np.ones(n, dtype=float)
        running_q = 1.0
        for i in range(n - 1, -1, -1):
            qfq_factor[i] = running_q
            if np.isfinite(right_factor[i]) and right_factor[i] > 1e-15:
                running_q *= right_factor[i]

        hfq_factor = np.ones(n, dtype=float)
        running_h = 1.0
        for i in range(1, n):
            if np.isfinite(right_factor[i]) and right_factor[i] > 1e-15:
                running_h = running_h / right_factor[i]
            hfq_factor[i] = running_h

        factor_df = pd.DataFrame({
            "symbol": symbol,
            "date": base["date"],
            "qfq_factor": qfq_factor,
            "hfq_factor": hfq_factor,
            "market": market,
        })
        return factor_df.sort_values(["symbol", "date"]).reset_index(drop=True)

    def check(self):
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        start_dates = [pd.Timestamp(task["start_date"]) for task in self.tasks if task.get("start_date") is not None]
        end_dates = [pd.Timestamp(task.get("end_date", task["start_date"])) for task in self.tasks if task.get("start_date") is not None]
        split_map = {}
        if start_dates:
            for year in range(min(start_dates).year, max(end_dates).year + 1):
                try:
                    split_map[year] = await asyncio.to_thread(proxy_pool, ak.fund_cf_em, year=str(year))
                except Exception as e:
                    logger.error(f"获取ETF {year} 年拆分数据失败: {e}")

        async def process_one_task(task):
            market = task['market']
            symbol = task['symbol']
            code = f"{market}{symbol}"
            try:
                raw = TDX_CLIENT.q_client().get_symbol_bars(MARKET.SH if market == "sh" else MARKET.SZ, symbol, PERIOD.DAILY, count=41200)
                div_df = await asyncio.to_thread(proxy_pool, ak.fund_etf_dividend_sina, symbol=code)
            except Exception as e:
                logger.error(f"获取ETF {code} 日频数据失败: {e}")
                return None, None
            raw = pd.DataFrame(raw)

            if raw.empty:
                logger.warning(f"ETF {code} 返回空数据")
                return None, None

            kline_df = self._rename_columns(raw, symbol, market)
            kline_df = kline_df[kline_df['date']>task['start_date']]
            split_df = pd.concat(split_map.values(), ignore_index=True) if split_map else pd.DataFrame()
            if not split_df.empty:
                split_df = split_df[split_df["基金代码"].astype(str).str.zfill(6) == symbol].copy()
            has_large_kline_change = self._has_large_kline_change(kline_df)
            if has_large_kline_change:
                rows_before_filter = len(kline_df)
                kline_df = self._filter_abnormal_zero_volume_kline(kline_df)
                rows_after_filter = len(kline_df)
                if rows_after_filter == 0:
                    logger.warning(f"ETF {code} K线过滤异常零成交量数据后为空")
                    return None, None
                if rows_after_filter < rows_before_filter:
                    logger.info(f"ETF {code} 过滤异常零成交量K线 {rows_before_filter - rows_after_filter} 条")
                has_large_kline_change = self._has_large_kline_change(kline_df)
            if split_df.empty and has_large_kline_change:
                try:
                    split_detail_df = await asyncio.to_thread(
                        proxy_pool,
                        ak.fund_open_fund_info_em,
                        symbol=symbol,
                        indicator="拆分详情",
                    )
                    split_df = self._rename_split_detail_columns(split_detail_df)
                    if split_df.empty:
                        logger.warning(f"ETF {code} K线涨跌超过50%，但拆分详情为空")
                except Exception as e:
                    logger.error(f"获取ETF {code} 拆分详情失败: {e}")
            factor_df = self._build_adjust_factor(kline_df, symbol, market, div_df, split_df)
            return kline_df, factor_df

        batch_size = MAX_CONCURRENCY
        for i in range(0, total, batch_size):
            batch_tasks = self.tasks[i:i + batch_size]
            tasks = [asyncio.create_task(process_one_task(one_task)) for one_task in batch_tasks]
            results = await asyncio.gather(*tasks)
            kline_dfs = [k for k, _ in results if k is not None and not k.empty]
            factor_dfs = [f for _, f in results if f is not None and not f.empty]
            if kline_dfs:
                kline_batch_df = pd.concat(kline_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        kline_batch_df,
                        table=self.table,
                        db=self.market,
                        primary_key=["symbol", "date"]
                    )
                except Exception as e:
                    logger.error(f"批量插入ETF日线数据失败: {e}")

            if factor_dfs:
                factor_batch_df = pd.concat(factor_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        factor_batch_df,
                        table="adjust_factor",
                        db=self.market,
                        primary_key=["symbol", "date"]
                    )
                except Exception as e:
                    logger.error(f"批量插入ETF复权因子失败: {e}")
            kline_cnt = len(kline_batch_df) if kline_dfs else 0
            factor_cnt = len(factor_batch_df) if factor_dfs else 0
            logger.info(
                f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] "
                f"批量保存ETF日线及复权因子数据，共 {kline_cnt + factor_cnt} 条"
            )

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
