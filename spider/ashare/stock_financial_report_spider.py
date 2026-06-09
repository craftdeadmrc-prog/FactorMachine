import asyncio
import random
import logging
import akshare as ak
import pandas as pd
from typing import List, Dict

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task
logger = logging.getLogger(__name__)

@task(description="获取A股财务报表数据（资产负债表、利润表、现金流量表）")
class StockFinancialReportSpider(BaseSpider):
    resource = "ashare_sina"
    table = "balance"

    # 报表类型中文名 -> 表名映射
    symbol_map = {
        "资产负债表": "balance",
        "利润表": "income",
        "现金流量表": "cash_flow"
    }

    _COLUMN_MAP = {
        "资产负债表": {
            "公告日期": "date",
            "货币资金": "cash_equivalents",
            "结算备付金": "settlement_provi",
            "拆出资金": "lend_capital",
            "交易性金融资产": "trading_assets",
            "买入返售金融资产": "bought_sellback_assets",
            "衍生金融资产": "derivative_financial_asset",
            "应收票据": "bill_receivable",
            "应收账款": "account_receivable",
            "应收款项融资": "receivable_fin",
            "预付款项": "advance_payment",
            "应收股利": "dividend_receivable",
            "应收利息": "interest_receivable",
            "应收保费": "insurance_receivables",
            "应收分保账款": "reinsurance_receivables",
            "应收分保合同准备金": "reinsurance_contract_reserves_receivable",
            "其他应收款": "other_receivable",
            "存货": "inventories",
            "划分为持有待售的资产": "hold_sale_asset",
            "一年内到期的非流动资产": "non_current_asset_in_one_year",
            "其他流动资产": "other_current_assets",
            "流动资产合计": "total_current_assets",
            "发放贷款及垫款": "loan_and_advance",
            "债权投资": "bond_invest",
            "其他债权投资": "other_bond_invest",
            "可供出售金融资产": "hold_for_sale_assets",
            "长期股权投资": "longterm_equity_invest",
            "投资性房地产": "investment_property",
            "长期应收款": "longterm_receivable_account",
            "其他权益工具投资": "other_equity_tools_invest",
            "其他非流动金融资产": "other_non_current_financial_assets",
            "在建工程": "constru_in_process",
            "工程物资": "construction_materials",
            "固定资产清理": "fixed_assets_liquidation",
            "生产性生物资产": "biological_assets",
            "油气资产": "oil_gas_assets",
            "合同资产": "contract_assets",
            "使用权资产": "usufruct_assets",
            "无形资产": "intangible_assets",
            "开发支出": "development_expenditure",
            "商誉": "good_will",
            "长期待摊费用": "long_deferred_expense",
            "递延所得税资产": "deferred_tax_assets",
            "其他非流动资产": "other_non_current_assets",
            "非流动资产合计": "total_non_current_assets",
            "资产总计": "total_assets",
            "短期借款": "shortterm_loan",
            "向中央银行借款": "borrowing_from_centralbank",
            "吸收存款及同业存放": "deposit_in_interbank",
            "拆入资金": "borrowing_capital",
            "交易性金融负债": "trading_liability",
            "衍生金融负债": "derivative_financial_liability",
            "应付票据": "notes_payable",
            "应付账款": "accounts_payable",
            "预收款项": "advance_peceipts",
            "合同负债": "contract_liability",
            "卖出回购金融资产款": "sold_buyback_secu_proceeds",
            "应付手续费及佣金": "commission_payable",
            "应付职工薪酬": "salaries_payable",
            "应交税费": "taxs_payable",
            "应付利息": "interest_payable",
            "应付股利": "dividend_payable",
            "其他应付款": "other_payable",
            "应付分保账款": "reinsurance_payables",
            "保险合同准备金": "insurance_contract_reserves",
            "代理买卖证券款": "proxy_secu_proceeds",
            "代理承销证券款": "receivings_from_vicariously_sold_securities",
            "预计流动负债": "estimate_liability_current",
            "划分为持有待售的负债": "hold_sale_liability",
            "一年内的递延收益": "deferred_earning_current",
            "一年内到期的非流动负债": "non_current_liability_in_one_year",
            "其他流动负债": "other_current_liability",
            "流动负债合计": "total_current_liability",
            "长期借款": "longterm_loan",
            "应付债券": "bonds_payable",
            "应付债券：优先股": "preferred_shares_noncurrent",
            "应付债券：永续债": "pepertual_liability_noncurrent",
            "租赁负债": "lease_liability",
            "长期应付职工薪酬": "longterm_salaries_payable",
            "长期应付款": "longterm_account_payable",
            "专项应付款": "specific_account_payable",
            "预计非流动负债": "estimate_liability",
            "长期递延收益": "deferred_earning",
            "递延所得税负债": "deferred_tax_liability",
            "其他非流动负债": "other_non_current_liability",
            "非流动负债合计": "total_non_current_liability",
            "负债合计": "total_liability",
            "实收资本(或股本)": "paidin_capital",
            "其他权益工具": "other_equity_tools",
            "优先股": "preferred_shares_equity",
            "永续债": "pepertual_liability_equity",
            "资本公积": "capital_reserve_fund",
            "减:库存股": "treasury_stock",
            "其他综合收益": "other_comprehensive_income",
            "专项储备": "specific_reserves",
            "盈余公积": "surplus_reserve_fund",
            "一般风险准备": "ordinary_risk_reserve_fund",
            "未分配利润": "retained_profit",
            "外币报表折算差额": "foreign_currency_report_conv_diff",
            "归属于母公司股东权益合计": "equities_parent_company_owners",
            "少数股东权益": "minority_interests",
            "所有者权益(或股东权益)合计": "total_owner_equities",
            "负债和所有者权益(或股东权益)总计": "total_sheet_owner_equities",
            "预付账款": "advance_payment",  # 银行特殊列名
            "衍生金融工具资产": "derivative_financial_asset",  # 银行特殊列名
            "递延税款借项": "deferred_tax_assets",  # 银行特殊列名
            "衍生金融工具负债": "derivative_financial_liability",  # 银行特殊列名
            "预收账款": "advance_peceipts",  # 银行特殊列名
            "股本": "paidin_capital",  # 银行特殊列名
            "其中:优先股": "preferred_shares_equity",  # 银行特殊列名
            "其中：永续债": "pepertual_liability_equity",  # 银行特殊列名
            "减:库藏股": "treasury_stock",  # 银行特殊列名
            "归属于母公司股东的权益": "equities_parent_company_owners",  # 银行特殊列名
            "负债及股东权益总计": "total_sheet_owner_equities"  # 银行特殊列名
        },
        "利润表": {
            "公告日期": "date",
            "营业总收入": "total_operating_revenue",
            "营业收入": "operating_revenue",
            "利息收入": "interest_income",
            "已赚保费": "premiums_earned",
            "手续费及佣金收入": "commission_income",
            "营业总成本": "total_operating_cost",
            "营业成本": "operating_cost",
            "手续费及佣金支出": "commission_expense",
            "退保金": "refunded_premiums",
            "赔付支出净额": "net_pay_insurance_claims",
            "提取保险合同准备金净额": "withdraw_insurance_contract_reserve",
            "保单红利支出": "policy_dividend_payout",
            "分保费用": "reinsurance_cost",
            "营业税金及附加": "operating_tax_surcharges",
            "研发费用": "rd_expenses",
            "销售费用": "sale_expense",
            "管理费用": "administration_expense",
            "财务费用": "financial_expense",
            "利息费用": "interest_cost_fin",
            "利息支出": "interest_expense",
            "投资收益": "investment_income",
            "对联营企业和合营企业的投资收益": "invest_income_associates",
            "汇兑收益": "exchange_income",
            "净敞口套期收益": "net_open_hedge_income",
            "公允价值变动收益": "fair_value_variable_income",
            "其他收益": "other_earnings",
            "资产减值损失": "asset_impairment_loss",
            "信用减值损失": "credit_impairment_loss",
            "资产处置收益": "asset_deal_income",
            "营业利润": "operating_profit",
            "营业外收入": "non_operating_revenue",
            "营业外支出": "non_operating_expense",
            "非流动资产处置损失": "disposal_loss_non_current_liability",
            "利润总额": "total_profit",
            "所得税费用": "income_tax_expense",
            "净利润": "net_profit",
            "持续经营净利润": "sust_operate_net_profit",
            "终止经营净利润": "discon_operate_net_profit",
            "归属于母公司所有者的净利润": "np_parent_company_owners",
            "少数股东损益": "minority_profit",
            "其他综合收益": "other_composite_income",
            "归属于少数股东的其他综合收益": "other_composite_income_mino_at",
            "综合收益总额": "total_composite_income",
            "归属于母公司所有者的综合收益总额": "ci_parent_company_owners",
            "归属于少数股东的综合收益总额": "ci_minority_owners",
            "基本每股收益": "basic_eps",
            "稀释每股收益": "diluted_eps",
            "对联营公司的投资收益": "invest_income_associates",  # 银行特殊列名
            "公允价值变动收益/(损失)": "fair_value_variable_income",  # 银行特殊列名
            "营业支出": "total_operating_cost",  # 银行特殊列名
            "加:营业外收入": "non_operating_revenue",  # 银行特殊列名
            "减:营业外支出": "non_operating_expense",  # 银行特殊列名
            "减:所得税": "income_tax_expense",  # 银行特殊列名
            "归属于母公司的净利润": "np_parent_company_owners",  # 银行特殊列名
            "少数股东权益": "minority_profit"  # 银行特殊列名
        },
        "现金流量表": {
            "公告日期": "date",
            "销售商品、提供劳务收到的现金": "goods_sale_and_service_render_cash",
            "客户存款和同业存放款项净增加额": "net_deposit_increase",
            "向中央银行借款净增加额": "net_borrowing_from_central_bank",
            "向其他金融机构拆入资金净增加额": "net_borrowing_from_finance_co",
            "收到原保险合同保费取得的现金": "net_original_insurance_cash",
            "收到再保险业务现金净额": "net_cash_received_from_reinsurance_business",
            "保户储金及投资款净增加额": "net_insurer_deposit_investment",
            "处置交易性金融资产净增加额": "net_deal_trading_assets",
            "收取利息、手续费及佣金的现金": "interest_and_commission_cashin",
            "拆入资金净增加额": "net_increase_in_placements",
            "回购业务资金净增加额": "net_buyback",
            "收到的税费返还": "tax_levy_refund",
            "收到的其他与经营活动有关的现金": "other_cashin_related_operate",
            "经营活动现金流入小计": "subtotal_operate_cash_inflow",
            "购买商品、接受劳务支付的现金": "goods_and_services_cash_paid",
            "客户贷款及垫款净增加额": "net_loan_and_advance_increase",
            "存放中央银行和同业款项净增加额": "net_deposit_in_cb_and_ib",
            "支付原保险合同赔付款项的现金": "original_compensation_paid",
            "支付利息、手续费及佣金的现金": "handling_charges_and_commission",
            "支付保单红利的现金": "policy_dividend_cash_paid",
            "支付给职工以及为职工支付的现金": "staff_behalf_paid",
            "支付的各项税费": "tax_payments",
            "支付的其他与经营活动有关的现金": "other_operate_cash_paid",
            "经营活动现金流出小计": "subtotal_operate_cash_outflow",
            "经营活动产生的现金流量净额": "net_operate_cash_flow",
            "收回投资所收到的现金": "invest_withdrawal_cash",
            "取得投资收益收到的现金": "invest_proceeds",
            "处置固定资产、无形资产和其他长期资产所收回的现金净额": "fix_intan_other_asset_dispo_cash",
            "处置子公司及其他营业单位收到的现金净额": "net_cash_deal_subcompany",
            "收到的其他与投资活动有关的现金": "other_cash_from_invest_act",
            "投资活动现金流入小计": "subtotal_invest_cash_inflow",
            "购建固定资产、无形资产和其他长期资产所支付的现金": "fix_intan_other_asset_acqui_cash",
            "投资所支付的现金": "invest_cash_paid",
            "质押贷款净增加额": "impawned_loan_net_increase",
            "取得子公司及其他营业单位支付的现金净额": "net_cash_from_sub_company",
            "支付的其他与投资活动有关的现金": "other_cash_to_invest_act",
            "投资活动现金流出小计": "subtotal_invest_cash_outflow",
            "投资活动产生的现金流量净额": "net_invest_cash_flow",
            "吸收投资收到的现金": "cash_from_invest",
            "子公司吸收少数股东投资收到的现金": "cash_from_mino_s_invest_sub",
            "取得借款收到的现金": "cash_from_borrowing",
            "发行债券收到的现金": "cash_from_bonds_issue",
            "收到其他与筹资活动有关的现金": "other_finance_act_cash",
            "筹资活动现金流入小计": "subtotal_finance_cash_inflow",
            "偿还债务支付的现金": "borrowing_repayment",
            "分配股利、利润或偿付利息所支付的现金": "dividend_interest_payment",
            "子公司支付给少数股东的股利、利润": "proceeds_from_sub_to_mino_s",
            "支付其他与筹资活动有关的现金": "other_finance_act_payment",
            "筹资活动现金流出小计": "subtotal_finance_cash_outflow",
            "筹资活动产生的现金流量净额": "net_finance_cash_flow",
            "汇率变动对现金及现金等价物的影响": "exchange_rate_change_effect",
            "现金及现金等价物净增加额": "cash_equivalent_increase",
            "期初现金及现金等价物余额": "cash_equivalents_at_beginning",
            "期末现金及现金等价物余额": "cash_and_equivalents_at_end",
            "吸收的卖出回购项净额": "net_buyback",  # 银行特殊列名
            "收回投资收到的现金": "invest_withdrawal_cash",  # 银行特殊列名
            "处置固定资产、无形资产及其他资产而收到的现金": "fix_intan_other_asset_dispo_cash",  # 银行特殊列名
            "处置子公司及其他单位收到的现金": "net_cash_deal_subcompany",  # 银行特殊列名
            "投资支付的现金": "invest_cash_paid",  # 银行特殊列名
            "购建固定资产、无形资产和其他长期资产支付的现金": "fix_intan_other_asset_acqui_cash",  # 银行特殊列名
            "吸收投资所收到的现金": "cash_from_invest",  # 银行特殊列名
            "偿还债务所支付的现金": "borrowing_repayment",  # 银行特殊列名
            "分配股利、利润或偿付利息支付的现金": "dividend_interest_payment"  # 银行特殊列名
        }
    }

    def __init__(self, tasks: List[Dict] = None, update: bool = False):
        super().__init__(tasks, update)

    def _rename_columns(
        self,
        df: pd.DataFrame,
        symbol: str,
        market: str,
        report_type_cn: str,
    ) -> pd.DataFrame:
        """
        清洗单张报表数据：
        1. 根据 report_type_cn 选择对应的列映射，保留映射中存在的字段并重命名。
        2. 添加 symbol、market、date 字段。
        3. 按 ["symbol", "date"] 排序。
        """
        rename_map = self._COLUMN_MAP[report_type_cn]

        # 只保留映射中实际存在的原始列
        keep_src_cols = [c for c in rename_map.keys() if c in df.columns]

        # 处理重复列问题
        columns_to_check = [
            ("其他应收款(合计)", "其他应收款"),
            ("在建工程合计", "在建工程"),
            ("长期应付款合计", "长期应付款")
        ]
        for keep_col, remove_col in columns_to_check:
            if keep_col in df.columns and remove_col in df.columns:
                keep_src_cols.remove(remove_col)
        df = df[keep_src_cols].rename(columns=rename_map)
        if df.columns.has_duplicates:
            df = df.T.groupby(level=0, sort=False).first().T
        df["date"] = pd.to_datetime(df["date"])
        for c in df.columns.tolist():
            if c != "date":
                df[c] = pd.to_numeric(df[c])
        df = df.copy()
        # 添加标识字段
        df["symbol"] = symbol
        df["market"] = market

        # 为所有目标列补充缺失列（填充 NA）
        target_cols = set(rename_map.values())
        missing_cols = [col for col in target_cols if col not in df.columns]
        if missing_cols:
            df = pd.concat(
                [df, pd.DataFrame(index=df.index, columns=missing_cols, dtype="float64")],
                axis=1,
            )

        id_cols = [col for col in ["date", "symbol", "market"] if col in df.columns]
        other_cols = sorted([col for col in df.columns if col not in id_cols])
        df = df[id_cols + other_cols]

        # 排序
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        # 先执行父类检查（可能会处理 update 标志等基础逻辑）
        super().check()
        try:
            # 计算四个月前的时间点
            # 使用 pd.DateOffset 处理月份跨度，确保逻辑准确
            new_tasks = []
            for task in self.tasks:
                four_months_ago = pd.Timestamp.now().date() - pd.DateOffset(months=4)
                if task["start_date"]<=four_months_ago:
                    new_tasks.append(task)
            self.tasks = new_tasks
            logger.info(f"过滤掉最近4个月已更新的财报数据，剩余 {len(self.tasks)} 个任务")
        except Exception as e:
            logger.error(f"检查财报数据更新状态失败: {e}")


    def _check_existing_dates(self, symbol: str, dates: List[pd.Timestamp], table: str):
        """
        检查指定股票在给定表中已存在的日期集合。
        :param symbol: 股票代码
        :param dates: 待检查的日期列表
        :param table: 表名（如 'balance'）
        :return: 已存在的日期集合（与输入 dates 中的元素类型一致）
        """
        if not dates:
            return set()
        # 将日期转换为字符串格式，便于 SQL 比较
        date_strs = [d.strftime('%Y.%m.%d') for d in dates]
        in_clause = "', '".join(date_strs)
        sql = self.loadTable("distinct date", table, f"where symbol = '{symbol}' and date IN ('{in_clause}')")
        try:
            df = load_dataframe(sql, self.market)
            if df.empty:
                return set()
            # 将返回的日期列转换回 Timestamp 类型
            existing_dates = set(pd.to_datetime(df['date']))
            return existing_dates
        except Exception as e:
            error_msg = str(e).lower()
            if "does not exist" in error_msg:
                logger.info(f"Table {table} 尚未初始化，视为无已存在数据")
                return set()
            else:
                logger.error(f"查询 {table} 已存在日期失败: {e}")
                return set()

    async def run(self):
        """
        扫描 tasks 中的股票，对每只股票爬取三种财务报表并分别存入对应表。
        优化：若资产负债表的全部报告期均已存在，则跳过利润表和现金流量表。
        """
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total_stocks = len(self.tasks)
        total_reports = total_stocks * len(self.symbol_map)  # 理论最大报表数
        logger.info(f"{self.__class__.__name__}: 开始处理 {total_stocks} 只股票，共 {total_reports} 份报表")

        idx = 0
        balance_table = self.symbol_map["资产负债表"]

        for task in self.tasks:
            symbol = task['symbol']
            market = task['market']
            stock = f"{market}{symbol}"

            fetched_reports = {}

            for report_type_cn, table in self.symbol_map.items():
                idx += 1
                logger.info(f"{self.__class__.__name__} [{idx}/{total_reports}] 正在处理 {symbol} {report_type_cn}")
                try:
                    df_report = await asyncio.to_thread(
                        proxy_pool,
                        ak.stock_financial_report_sina,
                        stock=stock,
                        symbol=report_type_cn,
                    )
                except Exception as error:
                    logger.error(f"获取股票 {symbol} {report_type_cn} 数据失败: {error}")
                    break

                if df_report.empty:
                    logger.warning(f"股票 {symbol} {report_type_cn} 返回空数据，跳过该股票三张财报保存")
                    break

                df_report = self._rename_columns(df_report, symbol, market, report_type_cn)
                fetched_reports[report_type_cn] = df_report

                if report_type_cn == "资产负债表":
                    fetched_dates = set(df_report['date'].drop_duplicates())
                    existing_dates = self._check_existing_dates(symbol, fetched_dates, balance_table)
                    if fetched_dates.issubset(existing_dates):
                        logger.info(f"股票 {symbol} 资产负债表的所有报告期 ({len(fetched_dates)} 个) 均已存在，跳过该股票三张财报保存")
                        break

            if len(fetched_reports) != len(self.symbol_map):
                logger.warning(f"股票 {symbol} 未完整获取三张财报，跳过保存")
                continue

            for report_type_cn, df_report in fetched_reports.items():
                table = self.symbol_map[report_type_cn]
                try:
                    save_dataframe(
                        df_report,
                        table=table,
                        db=self.market,
                        primary_key=["symbol", "date"]
                    )
                    logger.info(f"股票 {symbol} {report_type_cn}已保存，共 {len(df_report)} 条")
                except Exception as e:
                    logger.error(f"插入股票 {symbol} {report_type_cn}数据失败: {e}")

            # 可选：控制请求频率
            # await asyncio.sleep(random.randint(1, 3))
        logger.info(f"{self.__class__.__name__}: 财务数据抓取完成，共处理 {total_stocks} 只股票")

