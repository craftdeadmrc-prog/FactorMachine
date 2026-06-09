import pandas as pd
import logging
import re

logger = logging.getLogger(__name__)


def calculate_fq(df: pd.DataFrame, df_factor: pd.DataFrame, adj: str) -> pd.DataFrame:
    """
    计算复权数据:
    - qfq: 纯乘法（price * qfq_factor）
    - hfq: 纯乘法（price * hfq_factor）

    关键点：
    1) 先将两侧日期归一到日级别，避免时间戳粒度差异导致事件日错配；
    2) 同日 merge 后按复权类型填充因子，覆盖“早于最早因子日期”的场景。
    """
    if df.empty or df_factor.empty or adj == "none":
        return df

    try:
        factor_col = f"{adj}_factor"
        factor_date_col = "fq_date"

        df = df.copy()
        df_factor = df_factor.copy()
        df[factor_date_col] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df_factor[factor_date_col] = pd.to_datetime(df_factor["date"], errors="coerce").dt.normalize()

        df = df.dropna(subset=[factor_date_col]).sort_values("date").reset_index(drop=True)
        df_factor = df_factor.dropna(subset=[factor_date_col, factor_col])
        df_factor[factor_col] = pd.to_numeric(df_factor[factor_col], errors="coerce")
        df_factor = (
            df_factor.dropna(subset=[factor_col])
            .sort_values(factor_date_col)
            .drop_duplicates(factor_date_col, keep="last")
            .reset_index(drop=True)
        )
        if df.empty or df_factor.empty:
            return df.drop(columns=[factor_date_col], errors="ignore")

        merged = df.merge(df_factor[[factor_date_col, factor_col]], on=factor_date_col, how="left")
        if adj == "qfq":
            merged[factor_col] = merged[factor_col].bfill().ffill()
        else:
            merged[factor_col] = merged[factor_col].ffill().bfill()

        price_columns = [
            name
            for name in merged.columns
            if name in {"open", "high", "low", "close"} or re.match(r"^(a|b)\d+_p$", str(name))
        ]
        for name in price_columns:
            merged[name] = pd.to_numeric(merged[name], errors="coerce") * merged[factor_col]

        return merged.drop(columns=[factor_date_col, factor_col])

    except Exception as e:
        logger.error(f"Error calculating FQ ({adj}): {e}")
        return df
