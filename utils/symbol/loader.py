import os
import json
import ast
import pandas as pd
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        # 因子结果目录: factor_results/
        self.factor_results_dir = os.path.join("factor_results")
        os.makedirs(self.factor_results_dir, exist_ok=True)

        # 动态加载算子 & AST 执行器
        self.operators = load_operators(os.path.join("utils", "operators"))
        self.executor = SafeASTExecutor(self.operators)

        # 因子索引 & 依赖表
        self.factor_index: Dict[str, List[str]] = self._build_factor_index()
        self.factor_deps: Dict[str, dict] = self._build_factor_dependencies()
        self.load_parquet()

        # 运行时缓存
        self.force_update = force_update

        # 依赖图与批次信息（惰性计算）
        self._dependency_graph: Optional[Dict[str, Set[str]]] = None
        self._batches: Optional[List[List[str]]] = None
        self._forward_dep: Optional[Dict[str, Set[str]]] = None

    # ------------------------------------------------------------------
    # 因子索引与元信息
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
                    # 不进行多余打印或中断，保持轻量
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
    # 依赖分析：AST 统一解析
    # ------------------------------------------------------------------

    def _factor_dependencies(self, name: str) -> Set[str]:
        """
        计算单个因子的依赖集合（直接需要的变量名）：
        - 完全基于 AST 解析出的 Name 节点
        - 再在后续阶段区分“上游因子名”和“市场原始列”
        """
        info = self.factor_deps.get(name, {})
        expr = info.get("info", {}).get("计算公式", "") or info.get("expression", "")
        if not expr:
            return set()

        try:
            tree = ast.parse(expr, mode="eval")
            variables = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            # 去掉算子名，其余全部保留为“依赖变量”
            return variables - set(self.operators.keys())
        except Exception:
            # 不噪音输出，返回空集由上层逻辑兜底
            return set()

    def analyze_dependencies(self) -> Tuple[Dict[str, Set[str]], List[List[str]]]:
        """
        构建因子依赖图并计算批次（Kahn 拓扑）：
        - forward_dep: factor -> {它依赖的“前置因子”}
        - 依赖关系完全基于 AST 中的变量名，再与 factor_deps 键集求交
        """
        if self._dependency_graph is not None and self._batches is not None:
            return self._dependency_graph, self._batches
        factor_names = set(self.factor_deps.keys())
        # 正向依赖：仅保留“前置因子”，不含市场原始列
        forward_dep: Dict[str, Set[str]] = {}
        for name in factor_names:
            all_deps = self._factor_dependencies(name)
            # 前置因子 = AST 变量 ∩ 已知因子名，自动排除市场列
            forward_dep[name] = all_deps & factor_names
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
        # 入度统计
        in_degree: Dict[str, int] = {node: len(deps) for node, deps in forward_dep.items()}

        # 初始 ready：入度为 0 且还没有完成的因子
        ready: List[str] = [n for n, deg in in_degree.items() if deg == 0 and n not in existing_factors]
        batches: List[List[str]] = []
        done: Set[str] = existing_factors.copy()

        while ready:
            current_batch: List[str] = [node for node in ready if node not in done]
            if not current_batch:
                break

            batches.append(current_batch)
            done.update(current_batch)
            # 将依赖了 current_batch 中任一因子的节点入度减一
            current_set = set(current_batch)
            for node, deps in forward_dep.items():
                if deps & current_set:
                    in_degree[node] -= len(deps & current_set)

            ready = [n for n, deg in in_degree.items() if deg == 0 and n not in done]

        remaining = set(self.factor_deps.keys()) - done
        if remaining:
            # 这里仍然抛出错误，保持原逻辑语义
            raise ValueError(f"无法生成完整的依赖拓扑，剩余因子: {remaining}")

        self._dependency_graph = forward_dep
        self._batches = batches
        self._forward_dep = forward_dep
        return forward_dep, batches

    def _get_all_dependencies(self, names: Set[str]) -> Set[str]:
        """
        获取一组因子的所有前置依赖因子（递归展开），基于 analyze_dependencies 的 forward_dep
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
        # 加载市场数据
        self.working_df = load_dataframe(self.market_type)
        if self.working_df is None or self.working_df.empty:
            raise ValueError(f"市场数据 {self.market_type} 加载失败或为空")
        self._market_columns = set(self.working_df.columns)
        self.factor_deps = {k: v for k, v in self.factor_deps.items() if k not in self._market_columns}
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
                        # 假设索引对齐
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

        return series

    def save_factor(self, name: str, series: pd.Series) -> str:
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

    def _compute_and_save_factor(self, name: str, df_batch: pd.DataFrame) -> pd.Series:
        """计算并保存因子结果"""
        cached = self.load_factor(name)
        if cached is not None:
            return cached
        print(f"计算因子 {name} ...")
        series = self._execute_factor(name, df_batch)
        self.save_factor(name, series)
        print(f"因子 {name} 计算完成，已保存。")
        return series

    # ------------------------------------------------------------------
    # 主执行接口（使用 AST 依赖统一筛列）
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
        - parallel / max_workers: 支持多线程，受 MAX_CONCURRENCY 限制
        """
        # 目标因子（含其所有前置因子）
        if custom_factors:
            target_factors = set(custom_factors)
            deps = self._get_all_dependencies(target_factors)
            target_factors |= deps
        else:
            target_factors = set(self.factor_deps.keys())

        # 依赖拓扑与批次
        _, batches = self.analyze_dependencies()
        # 自定义因子时，过滤掉不相关批次
        filtered_batches: List[List[str]] = []
        for batch in batches:
            if any(f in target_factors for f in batch):
                filtered_batches.append([f for f in batch if f in target_factors])

        # 逐批执行（保持原顺序语义）
        for batch_idx, batch in enumerate(filtered_batches, 1):
            print(f"[批次 {batch_idx}/{len(filtered_batches)}] 因子: {batch}")
            batch_deps: Set[str] = set()
            for name in batch:
                batch_deps |= self._factor_dependencies(name)
            for dep in batch_deps:
                if dep not in self.working_df.columns:
                    loaded = self.load_factor(dep)
                    if loaded is not None:
                        self.working_df[dep] = loaded.values

            # 使用多线程执行本批次因子
            if parallel and MAX_CONCURRENCY > 1:
                max_workers = min(max_workers or MAX_CONCURRENCY, len(batch))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 收集该批次所有因子的依赖
                    # 确保所有依赖因子列都在 working_df 中（若不存在文件则加载）
                    for name in batch:
                        all_columns = self._factor_dependencies(name) | {"code", "date"}
                        df_batch = self.working_df[list(all_columns)]
                        future_to_name = {
                            executor.submit(self._compute_and_save_factor, name, df_batch): name
                        }
                    for future in as_completed(future_to_name):
                        name = future_to_name[future]
                        series = future.result()
                        self.working_df[name] = series.values
            else:
                # 顺序执行
                for name in batch:
                    series = self._compute_and_save_factor(name, df_batch)
                    self.working_df[name] = series.values


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