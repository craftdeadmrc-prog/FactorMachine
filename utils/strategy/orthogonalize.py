# utils/strategy/orthogonalize.py
# 多因子正交化工具模块（内部使用）

import numpy as np
import pandas as pd


class MultiFactorOrthogonalizer:
    """
    多因子正交化工具类

    输入为因子矩阵 DataFrame，行对应样本，列对应因子。
    支持两种正交化方法：
    - 回归残差法（regression）
    - Gram-Schmidt 法（gram_schmidt）
    """

    def __init__(
        self,
        keep_first: bool = True,
        center: bool = True,
        method: str = "regression"
    ):
        self.keep_first = keep_first
        self.center = center
        self.method = method
        self.fitted = False

    def fit_transform(
        self,
        x: pd.DataFrame,
        by: pd.Series | None = None,
        keep_first: bool | None = None,
        center: bool | None = None,
        method: str | None = None
    ) -> pd.DataFrame:
        """
        对输入因子矩阵进行正交化处理

        参数:
            x: 因子矩阵，列为因子名
            by: 可选分组标签（如行业），与 x.index 对齐
            keep_first: 是否保留第一列因子为基准
            center: 是否在正交化前做列均值中心化
            method: 'regression' 或 'gram_schmidt'
        """
        if not isinstance(x, pd.DataFrame):
            raise TypeError("x 必须为 pandas.DataFrame")

        if x.shape[1] <= 1:
            use_center = self.center if center is None else center
            if use_center:
                return x - x.mean()
            return x.copy()

        use_center = self.center if center is None else center
        use_keep_first = self.keep_first if keep_first is None else keep_first
        use_method = self.method if method is None else method

        if by is not None:
            return self._orthogonalize_by_group(
                x,
                by,
                use_keep_first,
                use_center,
                use_method
            )

        return self._orthogonalize_block(
            x,
            use_keep_first,
            use_center,
            use_method
        )

    def _orthogonalize_block(
        self,
        x: pd.DataFrame,
        keep_first: bool,
        center: bool,
        method: str
    ) -> pd.DataFrame:
        df = x.copy()
        columns = list(df.columns)

        if center:
            df = df - df.mean()

        result = pd.DataFrame(index=df.index, columns=columns, dtype=float)

        first_name = columns[0]
        first_values = df[first_name].values

        if keep_first:
            result[first_name] = first_values
        else:
            std_first = df[first_name].std()
            if std_first != 0:
                result[first_name] = first_values / std_first
            else:
                result[first_name] = first_values

        for i in range(1, len(columns)):
            name = columns[i]
            y = df[name].values.astype(float)

            if keep_first:
                used_columns = columns[:i]
            else:
                used_columns = columns[: i + 1]

            x_matrix = result[used_columns].values.astype(float)

            if method == "gram_schmidt":
                v = y.copy()
                for j in range(len(used_columns)):
                    u = result[used_columns[j]].values
                    denom = float(np.dot(u, u))
                    if denom != 0.0:
                        coef = float(np.dot(v, u)) / denom
                        v = v - coef * u
                result[name] = v
            else:
                ones = np.ones((len(y), 1), dtype=float)
                design = np.concatenate([ones, x_matrix], axis=1)
                beta, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
                fitted = design @ beta
                residual = y - fitted
                result[name] = residual

        self.fitted = True
        return result

    def _orthogonalize_by_group(
        self,
        x: pd.DataFrame,
        by: pd.Series,
        keep_first: bool,
        center: bool,
        method: str
    ) -> pd.DataFrame:
        if not isinstance(by, pd.Series):
            raise TypeError("by 必须为 pandas.Series")
        if not by.index.equals(x.index):
            raise ValueError("by 的索引必须与 x 完全一致")

        result = pd.DataFrame(index=x.index, columns=x.columns, dtype=float)

        groups = by.groupby(by)
        for _, indices in groups.groups.items():
            block = x.loc[indices]
            block_orth = self._orthogonalize_block(
                block,
                keep_first,
                center,
                method
            )
            result.loc[indices] = block_orth.values

        return result


def orthogonalize(
    x: pd.DataFrame,
    by: pd.Series | None = None,
    keep_first: bool = True,
    center: bool = True,
    method: str = "regression"
) -> pd.DataFrame:
    """
    便捷函数：直接对因子矩阵做正交化
    """
    orthogonalizer = MultiFactorOrthogonalizer(
        keep_first=keep_first,
        center=center,
        method=method
    )
    return orthogonalizer.fit_transform(x, by=by)


def orthogonalize_factors(
    factor_dict: dict,
    keep_first: bool = True,
    center: bool = True,
    method: str = "regression"
) -> dict:
    """
    对 {因子名: Series} 形式的因子集合做正交化
    """
    df = pd.DataFrame(factor_dict)
    df_orth = orthogonalize(
        df,
        by=None,
        keep_first=keep_first,
        center=center,
        method=method
    )
    return {name: df_orth[name] for name in df_orth.columns}