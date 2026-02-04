# FactorMachine/utils/symbol/loader.py

import os
import json
import ast
import pandas as pd
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
import concurrent.futures

from core.config import DATA_PATH, MAX_CONCURRENCY
from core.storage import load_dataframe, save_dataframe
from utils.symbol.ast_executor import load_operators, SafeASTExecutor


class FactorLoader:
    """因子加载与执行调度器"""

    def __init__(self, market_type: str,
                 factors_dir: str = "factors",
                 force_update: bool = False) -> None:
        """
        参数：
        - market_type: "ashare" / "fund" / "crypto"
        - factors_dir: 相对项目根目录的因子 JSON 根目录
        - force_update: 是否强制重新计算并覆盖已有结果
        """
        # 因子定义目录
        self.factors_dir = os.path.join(factors_dir)

        # 原始行情数据文件: DATA_PATH/{market_type}.parquet
        self.market_type = market_type
        self.parquet_path = os.path.join(DATA_PATH, f"{self.market_type}.parquet")

        # 因子结果目录: FactorMachine/factor_results/
        self.factor_results_dir = os.path.join("factor_results")
        os.makedirs(self.factor_results_dir, exist_ok=True)

        # 动态加载算子 & AST 执行器
        self.operators_dir = os.path.join("utils", "operators")
        self.operators = load_operators(self.operators_dir)
        self.executor = SafeASTExecutor(self.operators)

        # 因子索引 & 依赖表
        self.factor_index: Dict[str, List[str]] = self._build_factor_index()
        self.factor_deps: Dict[str, dict] = self._build_factor_dependencies()

        # 运行时缓存
        self.factor_cache: Dict[str, pd.Series] = {}
        self.parquet_df: Optional[pd.DataFrame] = None  # 只存原始数据
        self.working_df: Optional[pd.DataFrame] = None  # 原始数据 + 已计算因子
        self.force_update = force_update

        # 依赖图与批次信息（惰性计算）
        self._dependency_graph: Optional[Dict[str, Set[str]]] = None
        self._batches: Optional[List[List[str]]] = None
        self._forward_dep: Optional[Dict[str, Set[str]]] = None

        # 市场数据已有列（用于在依赖与所需列分析中自动跳过）
        self._market_columns: Set[str] = set()

    # ------------------------------------------------------------------
    # 因子索引与依赖分析
    # ------------------------------------------------------------------

    def _build_factor_index(self) -> Dict[str, List[str]]:
        """
        扫描 factors_dir 下所有 .json，按一级目录名构建索引
        """
        index: Dict[str, List[str]] = {}
        base = Path(self.factors_dir)

        if not base.exists():
            return index

        for root, _, files in os.walk(base):
            for file in files:
                if not file.endswith(".json"):
                    continue
                p = Path(root) / file
                rel = p.relative_to(base)
                category = rel.parts[0] if len(rel.parts) > 1 else ""
                index.setdefault(category, []).append(str(p))
        return index

    def _build_factor_dependencies(self) -> Dict[str, dict]:
        """
        读取每个 JSON 因子文件，构建因子元信息：
        - name: description.变量名 或 文件名
        - category: 来自路径一级目录
        - description/info: 说明与公式
        """
        deps: Dict[str, dict] = {}
        base = Path(self.factors_dir)

        if not base.exists():
            return deps

        for root, _, files in os.walk(base):
            for file in files:
                if not file.endswith(".json"):
                    continue

                p = Path(root) / file
                try:
                    with p.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    print(f"因子文件解析失败: {p}")

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

    def _factor_columns(self, name: str) -> Set[str]:
        """
        计算单个因子实际需要的列集合（不含 code/date）：
        = JSON.dependencies ∪ AST(计算公式) 中的变量名 - 算子名 - 市场数据已有列
        """
        info = self.factor_deps.get(name, {})
        columns = set([])

        expr = info.get("info", {}).get("计算公式", "")
        if not expr:
            expr = info.get("expression", "")

        if expr:
            try:
                tree = ast.parse(expr, mode="eval")
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        columns.add(node.id)
            except Exception:
                pass

        # 移除算子名
        operator_names = set(self.operators.keys())
        # 再移除市场数据表中已有的列（这些列不需要作为“需要计算的因子”参与）
        return columns - operator_names

    # ------------------------------------------------------------------
    # 依赖图构建与批次划分
    # ------------------------------------------------------------------

    def analyze_dependencies(self) -> Tuple[Dict[str, Set[str]], List[List[str]]]:
        """
        构建因子依赖图并计算批次（Kahn 拓扑）：
        - forward_dep: factor -> {它依赖的因子}
        - existing_factors: 已有结果文件视为已完成
        - 入度 in_degree 表示"该因子有多少前驱因子"
        """
        if self._dependency_graph is not None and self._batches is not None:
            return self._dependency_graph, self._batches

        # 确保已加载市场数据列，用于在依赖中跳过这些“内置因子”
        self.load_parquet()
        self._market_columns = set(self.parquet_df.columns)

        # 正向依赖：factor -> set(依赖的因子名)
        forward_dep: Dict[str, Set[str]] = {name: set() for name in self.factor_deps}

        for name, info in self.factor_deps.items():
            expr = info.get("info", {}).get("计算公式", "") or info.get("expression", "")
            if not expr:
                continue
            try:
                tree = ast.parse(expr, mode="eval")
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        # 只保留“因子名”依赖，且自动跳过市场数据表中已有的列
                        if node.id in self.factor_deps and node.id not in self._market_columns:
                            forward_dep[name].add(node.id)
            except Exception:
                pass

        # 已有结果文件 -> 视为已完成
        existing_factors: Set[str] = set()
        if os.path.isdir(self.factor_results_dir):
            for file_name in os.listdir(self.factor_results_dir):
                if not file_name.endswith(".parquet"):
                    continue
                parts = file_name.split("_")
                if len(parts) >= 2:
                    factor_name = parts[0]
                    if factor_name in forward_dep:
                        existing_factors.add(factor_name)

        # 入度统计：依赖多少前驱
        in_degree: Dict[str, int] = {node: len(deps) for node, deps in forward_dep.items()}

        batches: List[List[str]] = []
        done: Set[str] = existing_factors.copy()

        # 初始 ready：无前驱且未完成
        ready: List[str] = [n for n, deg in in_degree.items() if deg == 0 and n not in done]

        while ready:
            current_batch: List[str] = []
            for node in ready:
                if node in done:
                    continue
                if all(dep in done for dep in forward_dep[node]):
                    current_batch.append(node)

            if not current_batch:
                break

            batches.append(current_batch)

            for node in current_batch:
                done.add(node)
                # 减少所有依赖 node 的因子的入度
                for n, deps in forward_dep.items():
                    if node in deps:
                        in_degree[n] -= 1

            ready = [n for n, deg in in_degree.items() if deg == 0 and n not in done]

        remaining = set(self.factor_deps.keys()) - done
        if remaining:
            raise ValueError(f"无法生成完整的依赖拓扑，剩余因子: {remaining}")

        self._dependency_graph = forward_dep
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
        if self.parquet_df is None:
            # 按 market_type 作为表名使用 storage
            self.parquet_df = load_dataframe(self.market_type)
            if self.parquet_df is None or self.parquet_df.empty:
                raise ValueError(f"市场数据 {self.market_type} 加载失败或为空")
            self.working_df = self.parquet_df.copy()
            # 同时更新市场数据已有列集合
            self._market_columns = set(self.parquet_df.columns)
            self._load_all_existing_factors()

    def _load_all_existing_factors(self) -> None:
        """加载所有已存在的因子文件到 working_df"""
        if not os.path.isdir(self.factor_results_dir):
            return

        for file_name in os.listdir(self.factor_results_dir):
            if not file_name.endswith(".parquet"):
                continue
            parts = file_name.split("_")
            if len(parts) >= 2:
                factor_name = parts[0]
                if factor_name in self.factor_deps and factor_name not in self.working_df.columns:
                    loaded = self.load_factor(factor_name)
                    if loaded is not None:
                        # 假设顺序一致
                        self.working_df[factor_name] = loaded.values

    def load_factor(self, name: str) -> Optional[pd.Series]:
        if self.force_update:
            return None

        # 因子表名统一为 {market_type}_{factor_name}
        factor_df = load_dataframe(f"{self.market_type}_{name}")
        if factor_df is None or factor_df.empty:
            return None

        if isinstance(factor_df, pd.DataFrame):
            if factor_df.shape[1] == 1:
                series = factor_df.iloc[:, 0]
            elif name in factor_df.columns:
                series = factor_df[name]
            else:
                raise ValueError(f"因子 {name} 文件列不唯一且不包含列名 {name}")
        else:
            series = factor_df

        self.factor_cache[name] = series
        return series

    def save_factor(self, name: str, series: pd.Series) -> str:
        table_name = f"{self.market_type}_{name}"
        # 使用 storage 保存，自动压缩与类型优化
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

    def _compute_and_save_factor(self, name: str, df_batch: pd.DataFrame) -> pd.Series:
        """计算并保存因子结果（若已有且不强制更新则直接复用）"""
        cached = self.load_factor(name)
        if cached is not None:
            return cached
        print(f"  计算因子: {name}")
        series = self._execute_factor(name, df_batch)
        self.save_factor(name, series)
        print(f"  因子 {name} 计算并保存完成")
        self.factor_cache[name] = series
        return series

    # ------------------------------------------------------------------
    # 主执行接口
    # ------------------------------------------------------------------

    def run_factors(
        self,
        custom_factors: Optional[List[str]] = None,
        parallel: bool = True,
        max_workers: Optional[int] = None,
    ) -> Dict[str, pd.Series]:
        """
        执行因子计算

        参数:
        - custom_factors: 自定义需要计算的因子列表，None 表示全部
        - parallel: 是否使用多线程并行
        - max_workers: 并行线程数，None 表示自动
        """
        # 加载全局数据
        self.load_parquet()

        # 依赖拓扑与批次
        _, batches = self.analyze_dependencies()

        # 确定目标因子集合（包含所有前置依赖）
        if custom_factors:
            target_factors = set(custom_factors)
            deps = self._get_all_dependencies(target_factors)
            target_factors |= deps
        else:
            target_factors = set(self.factor_deps.keys())

        # 过滤仅保留目标因子的批次
        filtered_batches: List[List[str]] = []
        for batch in batches:
            if any(f in target_factors for f in batch):
                filtered_batches.append(batch)

        results: Dict[str, pd.Series] = {}

        # 默认线程数
        if max_workers is None:
            cpu_cnt = os.cpu_count() or 1
            max_workers = min(MAX_CONCURRENCY, cpu_cnt)

        # 处理每个批次
        for batch_idx, batch in enumerate(filtered_batches, 1):
            print(f"[批次 {batch_idx}/{len(filtered_batches)}] 因子: {batch}")

            # 该批次所需列集合（所有因子都用一份列并集）
            all_columns: Set[str] = set()
            for name in batch:
                all_columns |= self._factor_columns(name)
            all_columns |= {"code", "date"}

            # 补充 working_df 中缺失列
            existing_cols = set(self.working_df.columns)
            missing_cols = all_columns - existing_cols

            # 1) 原始列
            raw_missing = missing_cols & set(self.parquet_df.columns)
            for col in raw_missing:
                self.working_df[col] = self.parquet_df[col]

            # 2) 已有因子列：尝试从结果文件加载
            factor_missing = missing_cols & set(self.factor_deps.keys())
            for col in factor_missing:
                if col in self.working_df.columns:
                    continue
                loaded = self.load_factor(col)
                if loaded is not None:
                    self.working_df[col] = loaded.values
                # 如果仍然缺失，也不用立刻抛错：
                # - 若该因子在本轮 target_factors 且属于当前或后续批次，会通过计算得到；
                # - 若既不在 target_factors，又无文件，则不会被引用（拓扑已保证）。

            # 切片工作 DataFrame
            df_batch = self.working_df[list(all_columns)]

            # 本批真正需要计算的目标因子
            batch_targets = [name for name in batch if name in target_factors]

            if not batch_targets:
                # 没有需要算的，直接跳过（可能是全都已存在文件，或只为后续批次提供依赖）
                continue

            # 执行批次
            if parallel and len(batch_targets) > 1:
                workers = min(max_workers, len(batch_targets))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(self._compute_and_save_factor, name, df_batch): name
                        for name in batch_targets
                    }
                    for future in concurrent.futures.as_completed(futures):
                        name = futures[future]
                        try:
                            series = future.result()
                            results[name] = series
                            # 写回 working_df，供后续批次使用
                            self.working_df[name] = series.values
                        except Exception as e:
                            print(f"  因子 {name} 计算失败: {e}")
            else:
                for name in batch_targets:
                    try:
                        series = self._compute_and_save_factor(name, df_batch)
                        results[name] = series
                        if name not in self.working_df.columns:
                            self.working_df[name] = series.values
                    except Exception as e:
                        print(f"  因子 {name} 计算失败: {e}")

        return results

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def get_all_factor_names(self) -> List[str]:
        """获取所有可用的因子名"""
        return list(self.factor_deps.keys())

    def get_factor_info(self, name: str) -> Optional[dict]:
        """获取因子的元信息"""
        return self.factor_deps.get(name)

    def get_category_for_factor(self, name: str) -> Optional[str]:
        """获取因子的分类"""
        info = self.factor_deps.get(name, {})
        return info.get("category")

    def get_available_markets(self) -> List[str]:
        """获取可用的市场类型"""
        markets = []
        data_dir = DATA_PATH
        if not os.path.exists(data_dir):
            return markets
        for file in os.listdir(data_dir):
            if file.endswith(".parquet"):
                markets.append(file.replace(".parquet", ""))
        return markets