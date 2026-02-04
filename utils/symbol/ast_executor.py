# FactorMachine/utils/symbol/ast_executor.py

import ast
import pandas as pd
import os
from pathlib import Path
import importlib.util
import inspect
import concurrent.futures  # 新增：用于多线程并发


def load_operators(operators_dir: str) -> dict:
    """
    动态加载算子目录下所有可调用对象：
    - 递归扫描 operators_dir 目录下的 .py 文件
    - 排除 __init__.py 和以下划线开头的文件
    - 将模块中所有非下划线开头且 callable 的对象视为算子
    """
    operators = {}
    base = Path(operators_dir)

    if not base.exists():
        return operators

    for root, _, files in os.walk(base):
        for file in files:
            if not file.endswith(".py") or file.startswith("__"):
                continue

            module_path = Path(root) / file
            module_name = module_path.stem

            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
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

    注意：
    - 不再支持基础二元运算符（+ - * / ** 等）
    - 所有基础运算需通过算子（如 add/sub/mul/div/pow）实现
    """

    def __init__(self, operators: dict) -> None:
        self.operators = operators

    def execute(self, expression: str, df: pd.DataFrame):
        """
        将字符串表达式解析为 AST，并在给定 df 上执行
        """
        if not expression:
            return None

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return None

        return self._eval(tree.body, df)

    def _eval(self, node: ast.AST, df: pd.DataFrame):
        # 常量
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Num):  # 兼容旧版本 AST
            return node.n

        # 名字：优先当列名，否则当算子名
        if isinstance(node, ast.Name):
            if node.id in df.columns:
                return df[node.id]
            if node.id in self.operators:
                return self.operators[node.id]
            raise NameError(f"未识别的标识符: {node.id}")

        # 函数调用
        if isinstance(node, ast.Call):
            # 获取算子函数
            func = self._eval(node.func, df)
            # 先把各参数在当前 df 上求值
            args = [self._eval(arg, df) for arg in node.args]
            kwargs = {kw.arg: self._eval(kw.value, df) for kw in node.keywords}

            # ========= 截面算子识别 =========
            # 通过算子对应文件路径中是否包含 "cross_section" 来识别
            is_cross_section = False
            try:
                file_path = inspect.getfile(func)
                if "cross_section" in file_path:
                    is_cross_section = True
            except (TypeError, OSError):
                is_cross_section = False

            # ========= 确定分组键 =========
            # 仅截面算子需要分组：
            #   - 若最后一个位置参数是字符串常量，则该字符串为分组列名；
            #   - 否则默认按 'code' 分组（前提是 df 一定包含 'code' 列）
            group_key = None
            if is_cross_section:
                if node.args and isinstance(node.args[-1], ast.Constant) and isinstance(
                    node.args[-1].value, str
                ):
                    group_key = node.args[-1].value
                else:
                    group_key = "code"

            # ========= 按分组拆分运算（多线程） =========
            # 分组键存在 -> 根据 group_key 对 df 分组，并将每组数据分批传给同一个算子
            if group_key is not None:
                # 如果最后一个 AST 位置参数是字符串常量，则它只是“分组列名”，
                # 不应作为算子业务参数传入，这里从 args 中剔除。
                if (
                    node.args
                    and isinstance(node.args[-1], ast.Constant)
                    and isinstance(node.args[-1].value, str)
                ):
                    real_args = args[:-1]
                else:
                    real_args = args

                # 使用线程池并发计算每个分组
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    # 提交所有任务并保存分组索引映射
                    tasks = []
                    for _, group_df in df.groupby(group_key):
                        tasks.append(
                            (group_df.index, executor.submit(func, *real_args, **kwargs))
                        )

                    result = None
                    # 按顺序处理各分组的结果（写回在主线程，避免并发写冲突）
                    for group_idx, future in tasks:
                        group_res = future.result()

                        # 第一次调用时，根据返回类型初始化整体结果容器
                        if result is None:
                            if isinstance(group_res, pd.Series):
                                result = pd.Series(index=df.index, dtype=group_res.dtype)
                            elif isinstance(group_res, pd.DataFrame):
                                result = pd.DataFrame(
                                    index=df.index, columns=group_res.columns
                                )
                            else:
                                # 标量或其它类型，用 Series 容器承接
                                result = pd.Series(index=df.index, dtype=type(group_res))

                        # 将当前组结果写回到整体结果中，按 group_df 的索引对齐
                        if isinstance(result, pd.Series):
                            result.loc[group_idx] = group_res
                        elif isinstance(result, pd.DataFrame):
                            result.loc[group_idx] = group_res
                        else:
                            result.loc[group_idx] = group_res

                return result

            # ========= 非截面算子：保持原逻辑 =========
            return func(*args, **kwargs)

        # 一元运算（仅支持负号）
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, df)
            if isinstance(node.op, ast.USub):
                return -operand
            raise TypeError(f"不支持的一元操作: {type(node.op).__name__}")

        # 其他形式（包括 BinOp）统统不支持
        raise TypeError(f"不支持的节点类型: {type(node).__name__}")