import asyncio
import logging

import pandas as pd
import yfinance as yf

from ..base_spider import BaseSpider
from core.storage import save_dataframe
from core.config import MAX_CONCURRENCY, TDX_CLIENT
from core.scheduler import task
from opentdx.const import EX_MARKET, PERIOD

logger = logging.getLogger(__name__)


@task(description="获取美股日线及分红行情")
class UStockDailySpider(BaseSpider):
    resource = "ustock_tdx"
    table = "kline_1d"

    def _rename_columns(self, df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
        rename_map = {
            "datetime": "date",
            "Date": "date",
            "vol": "volume"
        }
        df = df.rename(columns=rename_map)

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["symbol"] = symbol
        df["market"] = market

        keep_cols = [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "market",
        ]
        exist_cols = [c for c in keep_cols if c in df.columns]
        df = df[exist_cols]
        df = df.dropna(subset=["date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def _build_adjust_factor(self, df: pd.DataFrame, symbol: str, market: str, dividends: pd.Series, splits: pd.Series) -> pd.DataFrame:
        base = df[["date", "close"]].copy()
        base = base.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if base.empty:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])

        close_map = base.set_index("date")["close"]
        all_dates = close_map.index

        div = pd.Series(dtype=float) if dividends is None else pd.to_numeric(dividends, errors="coerce").fillna(0.0)
        spl = pd.Series(dtype=float) if splits is None else pd.to_numeric(splits, errors="coerce").fillna(0.0)
        if not div.empty:
            div.index = pd.to_datetime(div.index).tz_localize(None).normalize()
            div = div.groupby(div.index).sum()
        if not spl.empty:
            spl.index = pd.to_datetime(spl.index).tz_localize(None).normalize()
            spl = spl.groupby(spl.index).prod()

        raw_event_dates = sorted(set(div.index.tolist()) | set(spl.index.tolist()))
        if not raw_event_dates:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])

        event_factor = {}
        event_date_map = {}
        for raw_d in raw_event_dates:
            eff_candidates = all_dates[all_dates >= raw_d]
            if len(eff_candidates) == 0:
                continue
            eff_d = eff_candidates[0]

            loc = all_dates.get_loc(eff_d)
            if isinstance(loc, slice):
                loc = loc.start
            if isinstance(loc, (list, tuple)):
                loc = loc[0]
            if loc <= 0:
                continue

            prev_d = all_dates[loc - 1]
            prev_close = close_map.loc[prev_d]
            if pd.isna(prev_close) or prev_close <= 0:
                continue

            split_ratio = float(spl.get(raw_d, 1.0))
            if split_ratio <= 0:
                split_ratio = 1.0
            div_cash = float(div.get(raw_d, 0.0))

            right_factor = ((prev_close - div_cash) / prev_close) / split_ratio
            if pd.notna(right_factor) and right_factor > 0:
                event_factor[eff_d] = event_factor.get(eff_d, 1.0) * right_factor
                if raw_d != eff_d:
                    event_date_map[raw_d] = eff_d

        if not event_factor:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])

        abs_factor = pd.Series(1.0, index=all_dates, dtype=float)
        event_factor_s = pd.Series(event_factor).sort_index()
        for d, rf in event_factor_s.items():
            abs_factor.loc[abs_factor.index < d] *= rf

        latest_factor = abs_factor.iloc[-1]
        first_factor = abs_factor.iloc[0]
        if latest_factor <= 0 or first_factor <= 0:
            return pd.DataFrame(columns=["symbol", "date", "qfq_factor", "hfq_factor", "market"])

        qfq_all = abs_factor / latest_factor
        hfq_all = abs_factor / first_factor

        # 生成与 fq_transfer.calculate_fq(qfq 使用 bfill) 兼容的“阶梯锚点”：
        # 当因子在 d 日发生变化（d 与前一交易日不同）时，同时保留
        # - 前一交易日(prev_d)的旧因子
        # - d 日的新因子
        # 这样 bfill 在区间内不会被下一事件因子提前覆盖。
        q = qfq_all.reset_index(drop=False)
        q.columns = ["date", "qfq_factor"]
        q["hfq_factor"] = hfq_all.reset_index(drop=True).values
        q = q.sort_values("date").reset_index(drop=True)

        anchor_idx = set()
        if not q.empty:
            anchor_idx.add(0)
            anchor_idx.add(len(q) - 1)
        for i in range(1, len(q)):
            prev_v = q.at[i - 1, "qfq_factor"]
            cur_v = q.at[i, "qfq_factor"]
            if pd.isna(prev_v) or pd.isna(cur_v):
                continue
            if abs(float(cur_v) - float(prev_v)) > 1e-15:
                anchor_idx.add(i - 1)
                anchor_idx.add(i)

        anchor_idx = sorted(anchor_idx)
        factor_df = q.loc[anchor_idx, ["date", "qfq_factor", "hfq_factor"]].copy()
        factor_df.insert(0, "symbol", symbol)
        factor_df["market"] = market
        factor_df = factor_df.dropna(subset=["qfq_factor", "hfq_factor"])
        factor_df = factor_df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return factor_df

    def _restore_yf_raw_ohlc(self, yf_hist: pd.DataFrame, splits: pd.Series) -> pd.DataFrame:
        ydf = yf_hist.copy()
        rename_map = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        ydf = ydf.rename(columns=rename_map)
        ydf["date"] = pd.to_datetime(ydf["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
        for c in ["open", "high", "low", "close"]:
            ydf[c] = pd.to_numeric(ydf[c], errors="coerce")
        ydf["volume"] = pd.to_numeric(ydf["volume"], errors="coerce").astype("float64")

        # 使用 tk.splits 事件序列恢复不复权价格:
        # 对每个拆分事件找到生效交易日(>=split_date的首个交易日)，并将生效日前历史乘回拆分倍数
        split_series = pd.Series(dtype=float) if splits is None else pd.to_numeric(splits, errors="coerce").dropna()
        if not split_series.empty and not ydf.empty:
            split_series.index = pd.to_datetime(split_series.index, errors="coerce").tz_localize(None).normalize()
            split_series = split_series.groupby(split_series.index).prod().sort_index()
            y_dates = ydf["date"].dropna().sort_values().reset_index(drop=True)
            for split_date, ratio in split_series.items():
                if not pd.notna(ratio):
                    continue
                eff_candidates = y_dates[y_dates >= split_date]
                if eff_candidates.empty:
                    continue
                eff_date = eff_candidates.iloc[0]
                mask = ydf["date"] < eff_date
                if mask.any():
                    r = float(ratio)
                    ydf.loc[mask, ["open", "high", "low", "close"]] = ydf.loc[mask, ["open", "high", "low", "close"]] * r
                    ydf.loc[mask, "volume"] = ydf.loc[mask, "volume"] / r
        return ydf[["date", "open", "high", "low", "close", "volume"]].dropna().sort_values("date").reset_index(drop=True)

    def _should_fallback_to_yf(self, df: pd.DataFrame, splits: pd.Series) -> bool:
        if df.empty:
            return True

        base = df.sort_values("date").reset_index(drop=True)
        # 美股异常判定：最早有效日价格小于4美元，视为可疑（TDX 可能误复权）
        first_open = pd.to_numeric(base["open"], errors="coerce").dropna()
        if not first_open.empty and float(first_open.iloc[0]) < 4.0:
            return True

        min_split_ratio = None
        split_series = pd.Series(dtype=float) if splits is None else pd.to_numeric(splits, errors="coerce").dropna()
        if not split_series.empty:
            split_series.index = pd.to_datetime(split_series.index, errors="coerce").tz_localize(None).normalize()
            split_series = split_series.groupby(split_series.index).prod().sort_index()
            min_split_ratio = float(split_series.min())

            dates = base["date"].dropna().sort_values().reset_index(drop=True)
            for split_date, ratio in split_series.items():
                eff_candidates = dates[dates >= split_date]
                if eff_candidates.empty:
                    return True
                eff_date = eff_candidates.iloc[0]
                pos = base.index[base["date"] == eff_date].tolist()
                if not pos or pos[0] <= 0:
                    return True
                p = pos[0]
                prev_close = pd.to_numeric(base.at[p - 1, "close"], errors="coerce")
                eff_open = pd.to_numeric(base.at[p, "open"], errors="coerce")
                if pd.isna(prev_close) or pd.isna(eff_open) or eff_open <= 0:
                    return True
                obs = prev_close / eff_open
                rel_err = abs(obs - float(ratio)) / float(ratio)
                if rel_err > 0.20:
                    return True

        if min_split_ratio is not None:
            prev_close = pd.to_numeric(base["close"].shift(1), errors="coerce")
            cur_open = pd.to_numeric(base["open"], errors="coerce")
            jump = (cur_open / prev_close).abs()
            abnormal = jump > (min_split_ratio * 1.05)
            if abnormal.fillna(False).any():
                return True

        return False

    def check(self):
        super().check()

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks)
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 个任务")

        async def process_one_task(task):
            symbol = task["symbol"]
            market = task["market"]

            def _fetch_actions_yf():
                tk = yf.Ticker(symbol.replace(".", "-"))
                return tk.dividends, tk.splits
            
            def _fetch_yf_hist(start_date=None):
                tk = yf.Ticker(symbol.replace(".", "-"))
                if start_date is not None:
                    return tk.history(start=start_date.strftime("%Y-%m-%d"), auto_adjust=False).reset_index()
                return tk.history(period="max", auto_adjust=False).reset_index()

            try:
                raw = TDX_CLIENT.eq_client().get_symbol_bars(EX_MARKET.US_STOCK, symbol, PERIOD.DAILY, count=41200)
                dividends, splits = await asyncio.to_thread(_fetch_actions_yf)
            except Exception as e:
                logger.error(f"获取美股 {symbol} 数据失败: {e}")
                return None, None
            raw = pd.DataFrame(raw)
            if raw.empty:
                logger.warning(f"美股 {symbol} 日线数据为空")
                return None, None
            try:
                renamed = self._rename_columns(raw, symbol, market)
            except Exception as e:
                logger.error(f"美股 {symbol} 日线数据清洗失败: {e}")
                return None, None

            # 统一按 TDX 的 amount>0 截取有效区间（早期 amount 可能为0）
            amt_mask = renamed["amount"] > 0
            if amt_mask.any():
                first_idx = amt_mask[amt_mask].index[0]
                renamed = renamed.loc[first_idx:].reset_index(drop=True)
            elif not self._should_fallback_to_yf(renamed, splits):
                logger.warning(f"美股 {symbol} amount 全部<=0，跳过")
                return None, None

            need_fallback = self._should_fallback_to_yf(renamed, splits)
            tdx_dates = renamed["date"].dropna().drop_duplicates()
            tdx_first_date = tdx_dates.min() if not tdx_dates.empty else None
            try:
                yf_hist = await asyncio.to_thread(_fetch_yf_hist, None if need_fallback else tdx_first_date)
            except Exception as e:
                if need_fallback:
                    logger.error(f"{symbol} yfinance回退替换失败: {e}")
                    return None, None
                logger.error(f"{symbol} yfinance缺失日期补齐失败: {e}")
                yf_hist = pd.DataFrame()

            if not yf_hist.empty:
                try:
                    yf_raw = self._restore_yf_raw_ohlc(yf_hist, splits)
                    if need_fallback:
                        yf_for_merge = yf_raw
                    else:
                        yf_missing_mask = (yf_raw["date"] > tdx_first_date) & ~yf_raw["date"].isin(tdx_dates)
                        yf_for_merge = yf_raw.loc[yf_missing_mask].copy()
                    if not yf_for_merge.empty:
                        merged = renamed.merge(yf_for_merge, on="date", how="outer", suffixes=("", "_yf"))
                        merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
                        if merged.empty:
                            return None, None
                        for col in ["open", "high", "low", "close", "volume"]:
                            ycol = f"{col}_yf"
                            if need_fallback:
                                merged[col] = merged[ycol].combine_first(merged[col])
                            else:
                                merged[col] = merged[col].combine_first(merged[ycol])

                        amount_mask = merged["amount"].isna() & merged[["open", "high", "low", "close", "volume"]].notna().all(axis=1)
                        if not need_fallback:
                            amount_mask &= (merged["date"] > tdx_first_date) & ~merged["date"].isin(tdx_dates)
                        price_sum = merged.loc[amount_mask, ["open", "high", "low", "close"]].sum(axis=1)
                        merged.loc[amount_mask, "amount"] = price_sum / 4 * merged.loc[amount_mask, "volume"]
                        fill_rows = int(amount_mask.sum())

                        merged["symbol"] = merged["symbol"].fillna(symbol)
                        merged["market"] = merged["market"].fillna(market)
                        renamed = merged[renamed.columns].reset_index(drop=True)
                        if need_fallback:
                            logger.info(f"{symbol} yfinance对齐替换OHLCV完成, rows={len(renamed)}")
                        else:
                            logger.info(f"{symbol} yfinance补齐TDX缺失日期完成, rows={len(renamed)}, fill_rows={fill_rows}")
                    elif need_fallback:
                        return None, None
                except Exception as e:
                    if need_fallback:
                        logger.error(f"{symbol} yfinance回退替换失败: {e}")
                        return None, None
                    logger.error(f"{symbol} yfinance缺失日期补齐失败: {e}")
            elif need_fallback:
                return None, None
            renamed = renamed[renamed["date"] > task['start_date']].reset_index(drop=True)

            kline_cols = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "market"]
            kline_df = renamed[kline_cols].dropna(subset=["date"]).reset_index(drop=True)

            factor_df = self._build_adjust_factor(renamed, symbol, market, dividends, splits)
            return kline_df, factor_df

        batch_size = MAX_CONCURRENCY
        for i in range(0, total, batch_size):
            batch_tasks = self.tasks[i:i + batch_size]
            tasks = [asyncio.create_task(process_one_task(task)) for task in batch_tasks]
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
                        primary_key=["symbol", "date"],
                    )
                except Exception as e:
                    logger.error(f"批量插入美股日线数据失败: {e}")

            if factor_dfs:
                factor_batch_df = pd.concat(factor_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        factor_batch_df,
                        table="adjust_factor",
                        db=self.market,
                        primary_key=["symbol", "date"],
                    )
                except Exception as e:
                    logger.error(f"批量插入美股复权因子失败: {e}")

            kline_cnt = len(kline_batch_df) if kline_dfs else 0
            factor_cnt = len(factor_batch_df) if factor_dfs else 0
            logger.info(
                f"{self.__class__.__name__} [{min(i + batch_size, total)}/{total}] "
                f"批量保存美股日线及复权因子，共 {kline_cnt + factor_cnt} 条"
            )
            await asyncio.sleep(0.1*MAX_CONCURRENCY)

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 个任务")
