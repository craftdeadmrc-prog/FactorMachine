# spider/ashare/ashare_stock_financial_report_spider.py
import asyncio
import random
import warnings

import akshare as ak
import pandas as pd

from ..base_spider import BaseSpider


class StockFinancialReportSpider(BaseSpider):
    resource = "sina"
    table_name = "ashare_stock_financial_report"

    _COLUMN_MAP = {
        "资产负债表": {
            "报告日": "date",
            "货币资金": "cash_and_equivalents",
            "应收账款": "accounts_receivable",
            "预付款项": "prepayments",
            "其他应收款(合计)": "other_receivables_total",
            "存货": "inventory",
            "流动资产合计": "total_current_assets",
            "长期股权投资": "long_term_equity_investment",
            "在建工程合计": "total_construction_in_progress",
            "固定资产及清理合计": "total_fixed_assets_and_disposal",
            "无形资产": "intangible_assets",
            "长期待摊费用": "long_term_prepaid_expenses",
            "递延所得税资产": "deferred_income_tax_assets",
            "其他非流动资产": "other_non_current_assets",
            "非流动资产合计": "total_non_current_assets",
            "资产总计": "total_assets",

            "短期借款": "short_term_borrowings",
            "应付票据及应付账款": "notes_and_accounts_payable",
            "应付账款": "accounts_payable",
            "预收款项": "advance_receipts",
            "合同负债": "contract_liabilities",
            "应付职工薪酬": "employee_benefits_payable",
            "应交税费": "taxes_payable",
            "一年内到期的非流动负债": "non_current_liabilities_due_within_one_year",
            "其他流动负债": "other_current_liabilities",
            "流动负债合计": "total_current_liabilities",

            "长期借款": "long_term_borrowings",
            "应付债券": "bonds_payable",
            "长期应付款合计": "long_term_payables_total",
            "长期递延收益": "long_term_deferred_income",
            "递延所得税负债": "deferred_income_tax_liabilities",
            "其他非流动负债": "other_non_current_liabilities",
            "非流动负债合计": "total_non_current_liabilities",
            "负债合计": "total_liabilities",

            "实收资本(或股本)": "share_capital",
            "资本公积": "capital_reserve",
            "盈余公积": "surplus_reserve",
            "未分配利润": "undistributed_profits",
            "其他综合收益": "other_comprehensive_income",
            "外币报表折算差额": "foreign_currency_translation_difference",
            "归属于母公司股东权益合计": "total_equity_attributable_to_parent",
            "少数股东权益": "minority_shareholders_equity",
            "所有者权益(或股东权益)合计": "total_equity",
            "负债和所有者权益(或股东权益)总计": "total_liabilities_and_equity",
        },

        "利润表": {
            "报告日": "date",
            "营业总收入": "total_operating_revenue",
            "营业收入": "operating_revenue",
            "营业总成本": "total_operating_cost",
            "营业成本": "operating_cost",

            "营业税金及附加": "business_tax_and_surcharge",
            "研发费用": "research_and_development_expense",
            "销售费用": "selling_expense",
            "管理费用": "administrative_expense",
            "财务费用": "financial_expense",
            "利息费用": "interest_expense",

            "投资收益": "investment_income",
            "对联营企业和合营企业的投资收益":
                "investment_income_from_associates_and_joint_ventures",
            "公允价值变动收益": "gain_from_fair_value_changes",
            "补贴收入": "subsidy_income",
            "其他收益": "other_income",
            "资产减值损失": "asset_impairment_loss",
            "信用减值损失": "credit_impairment_loss",
            "其他业务利润": "other_operating_profit",
            "资产处置收益": "asset_disposal_income",
            "营业外收入": "non_operating_income",
            "非流动资产处置利得": "gain_on_disposal_of_non_current_assets",
            "营业外支出": "non_operating_expense",
            "非流动资产处置损失": "loss_on_disposal_of_non_current_assets",

            "营业利润": "operating_profit",
            "利润总额": "total_profit",
            "所得税费用": "income_tax_expense",
            "净利润": "net_profit",
            "持续经营净利润": "net_profit_from_continuing_operations",
            "归属于母公司所有者的净利润": "net_profit_attrib_parent",
            "少数股东损益": "minority_shareholders_profit_or_loss",

            "基本每股收益": "basic_earnings_per_share",
            "稀释每股收益": "diluted_earnings_per_share",
        },

        "现金流量表": {
            "报告日": "date",

            "销售商品、提供劳务收到的现金": "cash_from_sales_services",
            "收到的税费返还": "tax_refunds_received",
            "收到的其他与经营活动有关的现金": "cash_from_other_operating",
            "经营活动现金流入小计": "operating_cash_inflow_subtotal",

            "购买商品、接受劳务支付的现金": "cash_paid_for_goods_services",
            "支付给职工以及为职工支付的现金": "cash_paid_to_employees",
            "支付的各项税费": "cash_paid_for_taxes",
            "支付的其他与经营活动有关的现金": "cash_paid_for_other_operating",
            "经营活动现金流出小计": "operating_cash_outflow_subtotal",
            "经营活动产生的现金流量净额": "net_operating_cash_flow",

            "收回投资所收到的现金":
                "cash_received_from_disposal_of_investments",
            "取得投资收益收到的现金":
                "cash_received_from_investment_income",
            "处置固定资产、无形资产和其他长期资产所收回的现金净额":
                "cash_from_disposal_fixed_intangible_longterm",
            "处置子公司及其他营业单位收到的现金净额":
                "net_cash_received_from_disposal_of_subsidiaries",
            "收到的其他与投资活动有关的现金":
                "cash_received_from_other_investing_activities",
            "投资活动现金流入小计": "investing_cash_inflow_subtotal",

            "购建固定资产、无形资产和其他长期资产所支付的现金":
                "cash_paid_for_acquisition_fixed_intangible_longterm",
            "投资所支付的现金": "cash_paid_for_investments",
            "取得子公司及其他营业单位支付的现金净额":
                "net_cash_paid_for_acquisition_of_subsidiaries",
            "支付的其他与投资活动有关的现金":
                "cash_paid_for_other_investing_activities",
            "投资活动现金流出小计": "investing_cash_outflow_subtotal",
            "投资活动产生的现金流量净额": "net_investing_cash_flow",

            "吸收投资收到的现金": "cash_received_from_investors",
            "子公司吸收少数股东投资收到的现金":
                "cash_received_from_minority_shareholders_investments",
            "取得借款收到的现金": "cash_received_from_borrowings",
            "收到其他与筹资活动有关的现金":
                "cash_received_from_other_financing_activities",
            "筹资活动现金流入小计": "financing_cash_inflow_subtotal",

            "偿还债务支付的现金": "cash_paid_for_debt_repayment",
            "分配股利、利润或偿付利息所支付的现金":
                "cash_paid_for_dividends_profit_interest",
            "子公司支付给少数股东的股利、利润":
                "dividends_paid_to_minority_shareholders_by_subsidiaries",
            "支付其他与筹资活动有关的现金":
                "cash_paid_for_other_financing_activities",
            "筹资活动现金流出小计": "financing_cash_outflow_subtotal",
            "筹资活动产生的现金流量净额": "net_financing_cash_flow",

            "汇率变动对现金及现金等价物的影响":
                "fx_effect_on_cash_and_equivalents",
            "现金及现金等价物净增加额":
                "net_increase_in_cash_and_equivalents",
            "期初现金及现金等价物余额":
                "opening_cash_and_equivalents",
            "期末现金及现金等价物余额":
                "closing_cash_and_equivalents",
        },
    }

    symbol_map = {
        "资产负债表":"balance_sheet",
        "利润表":"income_statement",
        "现金流量表":"cash_flow_statement"
    }

    def _rename_columns(
        self,
        df: pd.DataFrame,
        code: str,
        market: str,
        symbol: str,
    ) -> pd.DataFrame:
        """
        单次获取后的 df 清洗：
        1. 仅保留你指定的字段并重命名
        2. 显式丢弃“公告日期”
           - 舍弃原因：财报数据以“报告日”作为归属日期，
             回测/因子一般按报告期+滞后规则使用，公告日不作为主键；
             若未来需要公告日因子，可以单独从原接口补抓。
        3. 将 date 转为 datetime
        4. 增加 code、market、report_type 字段
        5. 为保证“有意义且非 NaN”，删除任一核心字段为 NaN 的行
        """
        rename_map = self._COLUMN_MAP[symbol]

        # 只保留需要的原始字段
        keep_src_cols = [c for c in rename_map.keys() if c in df.columns]

        df = df[keep_src_cols].rename(columns=rename_map)
        # 统一日期类型
        df["date"] = pd.to_datetime(df["date"])

        # 增加标识字段
        df["code"] = code
        df["market"] = market
        df["report_type"] = [symbol]  # 用于区分资产负债表 / 利润表 / 现金流量表

        # 排序与模板保持一致
        df = df.sort_values(["code", "date", "report_type"]).reset_index(drop=True)
        return df

    async def run(
        self,
        start_date: str = None,
        end_date: str = None,
        progress=None,
        task_id=None,
    ) -> pd.DataFrame:
        """
        与 StockValueEmSpider 保持同样签名与整体结构。

        区别：
        - 在 run 内部，对每个 (market, code) 循环三种 symbol：
          ["资产负债表", "利润表", "现金流量表"]
        - 每次调用 ak.stock_financial_report_sina 后，立即调用 _rename_columns
          做字段筛选与清洗
        - 最后将三类报表数据 concat 在一起返回
        """
        codes = self.get_one_market("ashare")

        all_dfs = []
        symbols = ["资产负债表", "利润表", "现金流量表"]
        total = len(codes) * len(symbols)

        # 初始化进度条
        if progress and task_id is not None:
            progress.update(task_id, total=total)

        completed = 0

        for market, code in codes:
            for symbol in symbols:
                completed += 1

                # 更新进度条
                if progress and task_id is not None:
                    progress.update(
                        task_id,
                        completed=completed,
                        description=f"{self.__class__.__name__} [{completed}/{total}]",
                    )
                await asyncio.sleep(random.randint(0, 1))
                try:
                    stock = f"{market}{code}"
                    df = ak.stock_financial_report_sina(
                        stock=stock,
                        symbol=symbol,
                    )
                except Exception as error:
                    warnings.warn(
                        f"{self.__class__.__name__}: 获取股票 {code} {symbol} 数据失败: {error}"
                    )
                    continue

                df = self._rename_columns(df, code, market, symbol)


                all_dfs.append(df)
            await asyncio.sleep(random.randint(0, 1))

        return pd.concat(all_dfs, ignore_index=True)