# utils/symbol/ast_executor.py

import ast
import os
from pathlib import Path
import importlib.util
import inspect
from typing import Any, Dict, Optional

import pandas as pd


def load_operators(operators_dir: str) -> Dict[str, Any]:
    """
    动态加载算子目录下所有可调用对象：
    - 递归扫描 operators_dir 目录下的 .py 文件
    - 排除 __init__.py 和以下划线开头的文件
    - 将模块中所有非下划线开头且 callable 的对象视为算子
    """
    operators: Dict[str, Any] = {}
    base = Path(operators_dir)

    if not base.exists():
        return operators

    for root, _, files in os.walk(base):
        for file in files:
            if not file.endswith(".py") or file.startswith("__"):
                continue

            module_path = Path(root) / file
            module_name = module_path.stem

            spec = importlib.util.spec_from_file_location(
                module_name, str(module_path)
            )
            if not spec or not spec.loader:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name, obj in module.__dict__.items():
                if callable(obj) and not name.startswith("_"):
                    operators[name] = obj

    return operators


class SafeASTExecutor:
    """
    精简安全 AST 执行器：
    支持节点：
      - Constant / Num
      - Name
      - Call
      - UnaryOp (仅负号)

    约定：
    - 不支持基础二元运算符（+ - * / ** 等），基础运算需通过算子实现；
    - 整个执行过程全局只维护“一个当前结果 Series”（或等价容器），
      不在 df 上拼接多列；
    - 所有中间/最终结果都与传入 df.index 对齐；
    - 截面分组写回时，如果长度/索引不对齐，则用 0 填充空缺。
    """

    def __init__(self, operators: Dict[str, Any]) -> None:
        self.operators = operators

    # ======================== 对外主接口 ========================

    def execute(self, expression: str, df: pd.DataFrame) -> Any:
        """
        将字符串表达式解析为 AST，并在给定 df 上执行。
        返回值可以是标量、Series 或 DataFrame，但若为 Series / DataFrame，
        其索引会被对齐到 df.index。
        """
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return None
        return self._eval(tree.body, df)

    # ======================== AST 递归求值 ========================

    def _eval(self, node: ast.AST, df: pd.DataFrame) -> Any:
        """
        在给定 df 上递归执行 AST 节点。
        整个求值过程中：
        - df 视作只读环境，不向其中追加列；
        - 中间 Series/DF 结果与 df.index 对齐；
        - 始终只维护一个“当前结果容器”，不会在 df 上不断扩宽。
        """

        # ---------- 常量 ----------
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Num):  # 兼容旧版本 AST
            return node.n

        # ---------- 名字 ----------
        if isinstance(node, ast.Name):
            # 优先视为 df 列
            if node.id in df.columns:
                return df[node.id]
            # 再看是否是算子
            if node.id in self.operators:
                return self.operators[node.id]
            raise NameError(f"未识别的标识符: {node.id}")
        # ---------- 函数调用 ----------
        if isinstance(node, ast.Call):
            return self._eval_call(node, df)

        # ---------- 其他节点不支持 ----------
        raise TypeError(f"不支持的节点类型: {type(node).__name__}")

    # ======================== Call 处理 ========================

    def _eval_call(self, node: ast.Call, df: pd.DataFrame) -> Any:
        """
        处理函数调用：
        - 解析算子 func；
        - 递归求值所有参数；
        - 若识别为截面算子，则按 df 分组循环调用，并写入统一结果容器；
        - 若识别为时序算子，则按 code 分组循环调用；
        - 否则直接调用后将结果与 df.index 对齐。
        """
        func = self._eval(node.func, df)

        # 递归求参数值
        args = [self._eval(arg, df) for arg in node.args]
        kwargs = {kw.arg: self._eval(kw.value, df) for kw in node.keywords}

        # 判断是否为截面算子 / 时序算子（依赖文件路径）
        is_cross_section = self._is_cross_section_operator(func)
        is_time_series = self._is_time_series_operator(func)
        if is_cross_section:
            result = self._eval_cross_section_call(node, func, args, kwargs, df)
        if is_time_series:
            result = self._eval_time_series_call(node, func, args, kwargs, df)
        else:
            # 普通算子：直接调用并将结果与 df.index 对齐
            result = func(*args, **kwargs)
            result = self._align_result_to_df(
                result, df, default_name=getattr(func, "__name__", None)
            )
        return result

    # ======================== 算子类型识别 ========================

    @staticmethod
    def _is_cross_section_operator(func: Any) -> bool:
        """
        通过算子对应文件路径中是否包含 "cross_section" 来识别是否为截面算子。
        """
        try:
            file_path = inspect.getfile(func)
            return "cross_section" in file_path
        except (TypeError, OSError):
            return False

    @staticmethod
    def _is_time_series_operator(func: Any) -> bool:
        """
        通过算子对应文件路径中是否包含 "time_series" 来识别是否为时序算子。
        """
        try:
            file_path = inspect.getfile(func)
            return "time_series" in file_path
        except (TypeError, OSError):
            return False

    # ======================== 截面算子处理 ========================

    def _eval_cross_section_call(
        self,
        node: ast.Call,
        func: Any,
        args: list,
        kwargs: dict,
        df: pd.DataFrame,
    ) -> Any:
        """
        截面算子调用逻辑：
        - 总是按 "date" 进行主要分组；
        - 若最后一个位置参数是字符串常量，则视为二次分组列名；
        - 先按 date 分组，再在每个 date 子集上按该列进行二次分组（若有）；
        - 计算结果按原逻辑写回到与 df.index 对齐的全局 Series 中。
        """
        # 处理是否存在“最后一个参数是字符串”的情况（作为二次分组键）
        secondary_group_key = None
        real_args = args
        if (
            node.args
            and isinstance(node.args[-1], ast.Constant)
            and isinstance(node.args[-1].value, str)
        ):
            secondary_group_key = node.args[-1].value
            real_args = args[:-1]

        result: Optional[pd.Series] = None
        main_groups = df.groupby("date")

        for _, main_group_df in main_groups:
            if secondary_group_key:
                if secondary_group_key not in main_group_df.columns:
                    raise KeyError(
                        f"二次分组键列 {secondary_group_key} 不存在于 df 中"
                    )
                sub_groups = main_group_df.groupby(secondary_group_key)
                for _, sub_group_df in sub_groups:
                    group_index = sub_group_df.index
                    group_args = self._prepare_group_args(real_args, group_index)
                    group_res = func(*group_args, **kwargs)
                    result = self._handle_group_result(
                        result, group_res, group_index, df
                    )
            else:
                group_index = main_group_df.index
                group_args = self._prepare_group_args(real_args, group_index)
                group_res = func(*group_args, **kwargs)
                result = self._handle_group_result(
                    result, group_res, group_index, df
                )
        return result

    # ======================== 时序算子处理 ========================

    def _eval_time_series_call(
        self,
        node: ast.Call,
        func: Any,
        args: list,
        kwargs: dict,
        df: pd.DataFrame,
    ) -> Any:
        """
        时序算子调用逻辑：
        - 按 "code" 进行分组，防止跨股票代码的数据溢出；
        - 对每个 code 的子数据集单独运算，并写回全局结果。
        """
        result: Optional[pd.Series] = None
        groups = df.groupby("code")

        for _, code_df in groups:
            group_index = code_df.index
            group_args = self._prepare_group_args(args, group_index)
            group_res = func(*group_args, **kwargs)
            result = self._handle_group_result(
                result, group_res, group_index, df
            )
        return result

    # ======================== 工具方法 ========================

    def _prepare_group_args(self, args, group_index: pd.Index):
        """
        为分组后的数据准备参数：对 Series 类型按当前组索引切片，
        其他参数原样传递。
        """
        group_args = []
        for arg in args:
            if isinstance(arg, pd.Series):
                group_args.append(arg.loc[group_index])
            else:
                group_args.append(arg)
        return group_args

    def _handle_group_result(
        self,
        global_result: Optional[pd.Series],
        group_res: Any,
        group_index: pd.Index,
        df: pd.DataFrame,
    ) -> pd.Series:
        """
        处理分组结果，若 global_result 尚未初始化则先初始化，
        然后将当前组结果写入对应位置。
        """
        if global_result is None:
            global_result = self._init_global_result(
                group_res, df, default_name=getattr(group_res, "name", None)
            )
        return self._write_group_result(global_result, group_res, group_index)

    @staticmethod
    def _init_global_result(
        group_res: Any,
        df: pd.DataFrame,
        default_name: Optional[str] = None,
    ) -> pd.Series:
        """
        根据某一次 group_res 的类型，初始化全局结果容器：
        - 若为 Series：构造一个与 df.index 对齐、同 dtype 的空 Series；
        - 其他类型：构造一个与 df.index 对齐、dtype 合理的空 Series；
        所有位置初始均为 0。
        """
        if isinstance(group_res, pd.Series):
            s = pd.Series(
                0,
                index=df.index,
                dtype=group_res.dtype,
                name=group_res.name or default_name,
            )
            return s

        # 标量/其他类型：dtype 使用 object，值初始为 0
        s = pd.Series(
            0,
            index=df.index,
            dtype="object",
            name=default_name,
        )
        return s

    @staticmethod
    def _write_group_result(
        global_result: pd.Series,
        group_res: Any,
        group_index: pd.Index,
    ) -> pd.Series:
        """
        将单个分组的计算结果 group_res 写入全局结果 global_result 的
        group_index 部分。

        规则：
        - group_res 非 Series：视为标量，直接广播到该组所有行；
        - group_res 为 Series：
          * 若索引与 group_index 完全一致：直接按索引赋值；
          * 若长度小于组长度：先整组填 0，再按顺序填充前 len(group_res) 行；
          * 若长度大于组长度：截断为前 len(group_index) 项。
        """
        # 标量：广播
        if not isinstance(group_res, pd.Series):
            global_result.loc[group_index] = group_res
            return global_result

        # Series：按索引或长度处理
        if group_res.index.equals(group_index):
            global_result.loc[group_index] = group_res
            return global_result

        # 索引不一致时，用长度规则 + 0 处理
        n_res = len(group_res)
        n_grp = len(group_index)

        # 先把这一组位置整体填为 0，再写实际值，保证“空缺为 0”
        global_result.loc[group_index] = 0

        if n_res == 0:
            # 该组没有任何有效值，整体保持 0
            return global_result

        if n_res >= n_grp:
            # 结果更长或刚好，截断前 n_grp 项
            values = group_res.iloc[:n_grp].values
            global_result.loc[group_index] = values
        else:
            # 结果更短：仅覆盖前 n_res 行，后面保持 NA
            values = group_res.values
            global_result.loc[group_index[:n_res]] = values

        return global_result

    @staticmethod
    def _align_result_to_df(
        result: Any,
        df: pd.DataFrame,
        default_name: Optional[str] = None,
    ) -> Any:
        """
        将普通算子返回的结果与 df.index 对齐：

        - 若为 Series：
          * 索引相同：直接返回（若无 name 用 default_name）；
          * 索引不同：构造新的 Series，index=df.index，先全为 0，
            再在交集位置填入原值；
        - 若为 DataFrame：
          * 只做索引对齐：reindex 到 df.index，列不动；
        - 若为标量/其他类型：
          * 原样返回，由上层决定是否广播。
        """
        if isinstance(result, pd.Series):
            if result.index.equals(df.index):
                if result.name is None and default_name is not None:
                    result.name = default_name
                return result

            aligned = pd.Series(
                0,
                index=df.index,
                dtype=result.dtype,
                name=result.name or default_name,
            )
            common_index = result.index.intersection(df.index)
            if not common_index.empty:
                aligned.loc[common_index] = result.loc[common_index]
            return aligned

        if isinstance(result, pd.DataFrame):
            if result.index.equals(df.index):
                return result
            return result.reindex(df.index)

        # 标量或其他对象：不强制广播，原样返回
        return result