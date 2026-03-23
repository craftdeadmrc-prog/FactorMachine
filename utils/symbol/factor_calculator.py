# -*- coding: utf-8 -*-
"""
因子计算器模块
- 复权因子加载与管理
- 齐次性配置自动加载（来自 utils/operators/operator_homogeneity.json）
- 基于后复权因子 hfq_factor 的动态前复权调整
"""

import os
import json
import ast
import pandas as pd
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import MAX_CONCURRENCY
from core.storage import load_dataframe, save_dataframe
from utils.symbol.ast_executor import load_operators, SafeASTExecutor


# ==================== 齐次性配置管理 ====================

def _load_operator_homogeneity() -> Dict[str, set]:
    """
    加载算子齐次性配置文件，返回格式:
    {
        "first_order": {算子1, 算子2, ...},  # 一次齐次
        "second_order": {算子3, 算子4, ...}, # 二次齐次
        "zero_order": {算子5, 算子6, ...}   # 零次齐次（无量纲）
    }
    """
    config_path = Path(__file__).parent.parent / "operators" / "operator_homogeneity.json"

    if not config_path.exists():
        # 不抛错，只警告；没有配置则视为全部 0 次/不调整
        print(f"警告: 齐次性配置文件不存在，路径为 {config_path}")
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)

        expected_keys = {"first_order", "second_order", "zero_order"}
        if not all(k in config for k in expected_keys):
            print("警告: 齐次性配置文件结构不完整，缺少 first_order / second_order / zero_order")
            return {}

        # 转为集合，加速匹配
        return {
            key: set(value) for key, value in config.items()
            if isinstance(value, list)
        }
    except Exception as e:
        print(f"加载齐次性配置文件失败: {e}")
        return {}


OPERATOR_HOMOGENEITY_CONFIG: Dict[str, set] = _load_operator_homogeneity()


# ==================== 因子计算器类 ====================

class FactorCalculator:
    """因子加载与执行调度器"""

    def __init__(self, market_type: str) -> None:
        """
        参数:
        - market_type: "ashare" / "fund" / "crypto"
        """
        # 因子定义目录
        self.factors_dir = os.path.join("factors")

        # 市场类型，如 "ashare"
        self.market_type = market_type

        # 因子结果目录: factor_results/
        self.factor_results_dir = os.path.join("factor_results")
        os.makedirs(self.factor_results_dir, exist_ok=True)

        # 动态加载算子 & AST 执行器
        self.operators = load_operators(os.path.join("utils", "operators"))
        self.executor = SafeASTExecutor(self.operators)

        # 因子定义元信息（从 JSON 中读）
        self.factor_deps: Dict[str, dict] = self._build_factor_dependencies()

        # 工作 DataFrame（市场数据 + hfq_factor）
        self.working_df: pd.DataFrame = pd.DataFrame()
        self._market_columns: Set[str] = set()

        # 先加载原始市场数据（不复权）
        self.load_parquet()

        # 一次性加载并合并后复权因子 hfq_factor
        self._load_hfq_factor()

        # 过滤掉与市场列同名的因子，避免冲突
        self._filter_market_named_factors()

        # 依赖图与批次信息（需时再构建）
        self._batches: Optional[List[List[str]]] = None
        self._forward_dep: Optional[Dict[str, Set[str]]] = None

    # ------------------------------------------------------------------
    # 因子索引与元信息
    # ------------------------------------------------------------------
    def _build_factor_dependencies(self) -> Dict[str, dict]:
        """
        读取每个 JSON 因子文件，构建因子元信息：
        - name: description.变量名 或 文件名
        - category: 来自路径一级目录
        - description/info: 说明与公式
        """
        deps: Dict[str, dict] = {}
        base = Path(self.factors_dir)

        for root, _, files in os.walk(base):
            for file in files:
                if not file.endswith(".json"):
                    continue

                p = Path(root) / file
                try:
                    with p.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                name = data.get("description", {}).get("变量名", p.stem)
                if not name:
                    continue

                rel = p.relative_to(base)
                category = rel.parts[0] if len(rel.parts) > 1 else ""

                deps[name] = {
                    "category": category,
                    "description": data.get("description", {}),
                    "info": data.get("info", {}),
                }

        return deps

    # ------------------------------------------------------------------
    # 依赖分析（基于 AST）
    # ------------------------------------------------------------------
    def _filter_market_named_factors(self) -> None:
        """
        过滤掉与市场数据列同名的因子定义。
        防止出现: 因子名 == 市场数据列名 导致的循环/冲突。
        """
        if not hasattr(self, "_market_columns"):
            self._market_columns = set(self.working_df.columns)

        factor_names = set(self.factor_deps.keys())
        conflict_names = factor_names & self._market_columns
        if not conflict_names:
            return

        self.factor_deps = {
            name: info
            for name, info in self.factor_deps.items()
            if name not in conflict_names
        }

    def _factor_dependencies(self, name: str) -> Set[str]:
        """
        计算单个因子的直接依赖集合（变量名）：
        - 通过 AST 遍历 Name 节点
        - 去掉算子名，只保留“列名或因子名”
        """
        info = self.factor_deps.get(name, {})
        expr = info.get("info", {}).get("计算公式", "") or info.get("expression", "")
        if not expr:
            return set()

        try:
            tree = ast.parse(expr, mode="eval")
            variables = {
                node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name)
            }
            # 去掉当前注册的算子名，只保留列/因子标识
            return variables - set(self.operators.keys())
        except Exception:
            return set()

    def analyze_dependencies(self) -> Tuple[Dict[str, Set[str]], List[List[str]]]:
        """
        构建因子依赖图并计算拓扑批次：
        - forward_dep: factor -> {它依赖的“前置因子名”}
        - batches: [[batch1 中的因子], [batch2 中的因子], ...]
        """
        factor_names = set(self.factor_deps.keys())
        forward_dep: Dict[str, Set[str]] = {}
        for name in factor_names:
            all_deps = self._factor_dependencies(name)
            forward_dep[name] = all_deps & factor_names

        existing_factors: Set[str] = set()
        if os.path.isdir(self.factor_results_dir):
            for file_name in os.listdir(self.factor_results_dir):
                if not file_name.endswith(".parquet"):
                    continue
                # 注意：这里简单用文件前缀做 existing 判断，
                # 实际项目中需严格与 {market_type}_{factor_name} 对应。
                factor_prefix = file_name.split(".")[0]
                parts = factor_prefix.split("_", 1)
                if len(parts) == 2:
                    _, factor_name = parts
                    if factor_name in forward_dep:
                        existing_factors.add(factor_name)

        in_degree: Dict[str, int] = {
            node: len(deps) for node, deps in forward_dep.items()
        }
        ready: List[str] = [
            n for n, deg in in_degree.items()
            if deg == 0 and n not in existing_factors
        ]
        batches: List[List[str]] = []
        done: Set[str] = existing_factors.copy()

        while ready:
            current_batch: List[str] = [node for node in ready if node not in done]
            if not current_batch:
                break

            batches.append(current_batch)
            done.update(current_batch)
            current_set = set(current_batch)
            for node, deps in forward_dep.items():
                if deps & current_set:
                    in_degree[node] -= len(deps & current_set)

            ready = [
                n for n, deg in in_degree.items()
                if deg == 0 and n not in done
            ]

        remaining = set(self.factor_deps.keys()) - done
        if remaining:
            raise ValueError(f"无法生成完整的依赖拓扑，剩余因子: {remaining}")

        self._batches = batches
        self._forward_dep = forward_dep
        return forward_dep, batches

    def _get_all_dependencies(self, names: Set[str]) -> Set[str]:
        """
        获取一组因子的所有前置依赖因子（递归展开）
        """
        if self._forward_dep is None:
            self.analyze_dependencies()

        result: Set[str] = set()
        stack: List[str] = list(names)

        while stack:
            name = stack.pop()
            for dep in self._forward_dep.get(name, set()):
                if dep not in result:
                    result.add(dep)
                    stack.append(dep)

        return result

    # ------------------------------------------------------------------
    # 数据加载与结果存取
    # ------------------------------------------------------------------
    def load_parquet(self) -> None:
        """加载市场数据（不复权）"""
        self.working_df = load_dataframe(self.market_type)
        if self.working_df is None or self.working_df.empty:
            raise ValueError(f"市场数据 {self.market_type} 加载失败或为空")
        self._market_columns = set(self.working_df.columns)

    def _load_hfq_factor(self) -> None:
        """
        加载后复权因子 hfq_factor：
        - 因子文件命名：{market_type}_hfq_factor
        - 结构至少包含：code, date, hfq_factor
        - 一次性 merge 到 working_df 上，后续所有因子共享这列
        """
        hfq_factor_df = self.load_factor("hfq_factor")
        if hfq_factor_df is None or hfq_factor_df.empty:
            # 如果市场数据本身已经带 hfq_factor，就不强制要求因子文件存在
            if "hfq_factor" not in self._market_columns:
                raise ValueError("后复权因子列 hfq_factor 不存在，请先生成 ashare_hfq_factor 因子文件")
            return

        # 只使用必要列
        cols = [c for c in hfq_factor_df.columns if c in ("code", "date", "hfq_factor")]
        if not {"code", "date", "hfq_factor"} <= set(cols):
            raise ValueError("ashare_hfq_factor 因子文件缺少必要列：code, date, hfq_factor")

        hfq_factor_df = hfq_factor_df["code", "date", "hfq_factor"]
        self.working_df = pd.merge(
            self.working_df,
            hfq_factor_df,
            on=["code", "date"],
            how="left",
        )
        self._market_columns.add("hfq_factor")

    def load_factor(self, name: str) -> pd.DataFrame:
        """加载因子数据（基础因子 / 中间结果因子）"""
        return load_dataframe(f"{self.market_type}_{name}", self.factor_results_dir)

    def save_factor(self, name: str, series: pd.Series) -> str:
        """保存单个因子结果为 parquet + config"""
        table_name = f"{self.market_type}_{name}"
        save_dataframe(series.to_frame(name), table_name, self.factor_results_dir)
        return os.path.join(self.factor_results_dir, f"{table_name}.parquet")

    def _execute_factor(self, name: str, df: pd.DataFrame) -> pd.Series:
        """执行单个因子"""
        info = self.factor_deps.get(name, {})
        expr = info.get("info", {}).get("计算公式", "") or info.get("expression", "")
        if not expr:
            raise ValueError(f"因子 {name} 未找到计算公式")

        result = self.executor.execute(expr, df)
        if result is None:
            raise ValueError(f"因子 {name} 计算结果为空")

        if not isinstance(result, pd.Series):
            result = pd.Series(result, index=df.index)
        if not result.name:
            result.name = name
        return result

    # ------------------------------------------------------------------
    # 齐次性 + 动态前复权调整
    # ------------------------------------------------------------------
    def _adjust_by_homogeneity(self, name: str, series: pd.Series, df: pd.DataFrame) -> pd.Series:
        """
        基于齐次性做动态前复权调整：
        factor_dyn(t) = factor_hfq(t) * (hfq_factor[0] / hfq_factor[t])^k

        - 仅当存在 hfq_factor 且 k > 0（一次/二次齐次）时才调整；
        - k = 0 或 未知（视为零次齐次）时不做任何变换。
        """
        if "hfq_factor" not in df.columns:
            return series

        k = self._infer_homogeneity(name)
        if k <= 0:
            return series

        if not series.index.equals(df.index):
            series = series.reindex(df.index)

        # 这里取样本内最早的 hfq_factor 作为基准因子
        base_factor = df["hfq_factor"].iloc[0]
        adjust_coef = (base_factor / df["hfq_factor"]) ** k

        return series * adjust_coef

    def _infer_homogeneity(self, name: str) -> int:
        """
        推断因子的整体齐次次数 k：
        - 通过解析该因子公式的 AST；
        - 对表达式中的每个函数调用，查询 OPERATOR_HOMOGENEITY_CONFIG；
        - 递归综合出最大的 k 值。
        约定：
        -1: 非齐次 / 不可自动处理 -> 视为 0（本实现中直接返回 0）
         0: 零次齐次（如基于收益率、比率、rank等）
         1: 一次齐次（线性价格型）
         2: 二次齐次（方差/波动率）
        """
        info = self.factor_deps.get(name, {})
        expr = info.get("info", {}).get("计算公式", "") or info.get("expression", "")
        if not expr:
            return 0

        try:
            tree = ast.parse(expr, mode="eval")
            return self._analyze_homogeneity(tree.body)
        except Exception:
            return 0

    def _analyze_homogeneity(self, node: ast.AST) -> int:
        """递归分析 AST 确定表达式对价格的齐次阶数 k"""
        if isinstance(node, ast.Name):
            # 变量名本身不设定阶数，交由算子层决定
            return 0

        if isinstance(node, ast.Call):
            func_name = self._get_func_name(node.func)
            if not func_name:
                return 0

            # 先看算子配置
            if func_name in OPERATOR_HOMOGENEITY_CONFIG.get("first_order", set()):
                return 1
            if func_name in OPERATOR_HOMOGENEITY_CONFIG.get("second_order", set()):
                return 2
            if func_name in OPERATOR_HOMOGENEITY_CONFIG.get("zero_order", set()):
                return 0

            # 未配置的算子：向下递归，看参数
            max_k = 0
            for arg in node.args:
                arg_k = self._analyze_homogeneity(arg)
                max_k = max(max_k, arg_k)
            for kw in node.keywords:
                kw_k = self._analyze_homogeneity(kw.value)
                max_k = max(max_k, kw_k)
            return max_k

        if isinstance(node, ast.Attribute):
            # 例如 df.col，不在这里设定阶数
            return 0

        # 常量、运算符等，视为 0 次齐次
        return 0

    def _get_func_name(self, node: ast.AST) -> Optional[str]:
        """从 AST 节点中获取函数名"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _compute_and_save_factor(self, name: str, df_batch: pd.DataFrame) -> pd.Series:
        """计算并保存单个因子结果"""
        series = self._execute_factor(name, df_batch)
        series = self._adjust_by_homogeneity(name, series, df_batch)
        self.save_factor(name, series)
        return series

    # ------------------------------------------------------------------
    # 主执行接口
    # ------------------------------------------------------------------
    def run_factors(
        self,
        custom_factors: Optional[List[str]] = None,
        parallel: bool = True,
        max_workers: Optional[int] = None,
    ) -> None:
        """
        执行因子计算

        参数:
        - custom_factors: 自定义需要计算的因子列表，None 表示全部
        - parallel / max_workers: 是否多线程 + 最大线程数，受 MAX_CONCURRENCY 限制
        """
        # 目标因子（含其所有前置因子）
        if custom_factors:
            target_factors = set(custom_factors)
            deps = self._get_all_dependencies(target_factors)
            target_factors |= deps
        else:
            target_factors = set(self.factor_deps.keys())

        # 根据所有目标因子的依赖裁剪市场列
        self._remove_unused_market_columns(target_factors)

        # 构建依赖拓扑
        _, batches = self.analyze_dependencies()
        filtered_batches: List[List[str]] = []
        for batch in batches:
            if any(f in target_factors for f in batch):
                filtered_batches.append([f for f in batch if f in target_factors])

        # 按批次执行
        for batch_idx, batch in enumerate(filtered_batches, 1):
            batch_deps: Set[str] = set()
            for name in batch:
                batch_deps |= self._factor_dependencies(name)
            working_df_cols = self.working_df.columns.tolist()
            for dep in batch_deps:
                if dep not in working_df_cols:
                    dep_df = self.load_factor(dep)
                    if dep_df is not None and not dep_df.empty:
                        # dep 因子文件按 {market_type}_{dep}.parquet 存，只有一列因子值
                        # 此处简化为直接对齐 index
                        self.working_df[dep] = dep_df.iloc[:, 0].values

            if parallel and MAX_CONCURRENCY > 1:
                max_workers = min(max_workers or MAX_CONCURRENCY, len(batch))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {}
                    for name in batch:
                        all_columns = self._factor_dependencies(name) | {"code", "date"}
                        df_batch = self.working_df[list(all_columns)]
                        futures[executor.submit(self._compute_and_save_factor, name, df_batch)] = name

                    for future in as_completed(futures):
                        future.result()
            else:
                for name in batch:
                    all_columns = self._factor_dependencies(name) | {"code", "date"}
                    df_batch = self.working_df[list(all_columns)]
                    self._compute_and_save_factor(name, df_batch)

    def _remove_unused_market_columns(self, target_factors: Set[str]) -> None:
        """
        根据目标因子的所有依赖，移除不需要的市场列。
        """
        direct_dependencies: Set[str] = set()
        for name in target_factors:
            direct_dependencies.update(self._factor_dependencies(name))

        all_upstream_dependencies: Set[str] = set()
        if target_factors:
            upstream_factors = self._get_all_dependencies(target_factors)
            for up_name in upstream_factors:
                all_upstream_dependencies.update(self._factor_dependencies(up_name))

        all_required_vars = direct_dependencies | all_upstream_dependencies
        required_market_columns = all_required_vars & self._market_columns

        # hfq_factor 作为“市场层附加列”，若存在则必须保留
        if "hfq_factor" in self._market_columns:
            required_market_columns.add("hfq_factor")

        # 始终保留 code / date
        required_columns = required_market_columns | {"code", "date"}

        columns_to_drop = self._market_columns - required_columns
        if columns_to_drop:
            self.working_df = self.working_df.drop(columns=columns_to_drop)