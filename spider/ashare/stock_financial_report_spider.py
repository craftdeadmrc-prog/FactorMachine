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
    table_names = ["balance", "income", "cash_flow"]  # 三张表的名称

    # 报表类型中文名 -> 表名映射
    symbol_map = {
        "资产负债表": "balance",
        "利润表": "income",
        "现金流量表": "cash_flow"
    }

    _COLUMN_MAP = {
        "资产负债表": {
            "报告日": "date",
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
            "报告日": "date",
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
            "报告日": "date",
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

        # 日期转换
        df["date"] = pd.to_datetime(df["date"])

        # 添加标识字段
        df["symbol"] = symbol
        df["market"] = market

        # 为所有目标列补充缺失列（填充 NA）
        target_cols = set(rename_map.values())
        for col in target_cols:
            if col not in df.columns:
                df[col] = pd.NA

        # 排序
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def check(self):
        """
        特殊 check 逻辑：
        1. 判断每个 symbol 的三张表中是否存在至少一张表数据为空。
        2. 如果表不存在，也视为需要爬取。
        若存在上述情况，则保留该 symbol 任务；否则从 self.tasks 中移除。
        """
        if not self.tasks:
            return

        keep_tasks = []
        for task in self.tasks:
            symbol = task['symbol']
            all_tables_have_data = True
            for table_name in self.table_names:
                # 先检查表是否存在
                try:
                    # 直接查询并捕获异常
                    sql = f"SELECT 1 FROM {table_name} WHERE symbol = '{symbol}' LIMIT 1"
                    df = load_dataframe(sql, market=self.market)
                    if df.empty:
                        # 表存在但无该 symbol 的数据
                        all_tables_have_data = False
                        break
                    # 表存在且有数据，继续下一张表
                except Exception as e:
                    # 表不存在或查询失败（如权限不足），视为需要爬取
                    logger.info(f"表 {table_name} 可能不存在或查询失败: {e}")
                    all_tables_have_data = False
                    break

            if not all_tables_have_data:
                keep_tasks.append(task)
                logger.info(f"{symbol} 至少一张财务报表为空或表不存在，需要爬取")
            else:
                logger.info(f"{symbol} 三张财务报表均已存在，跳过")

        self.tasks = keep_tasks
        logger.info(f"check 后剩余 {len(self.tasks)} 个需要爬取的任务")


    async def run(self, progress=None, task_id=None):
        """
        扫描 tasks 中的股票，对每只股票爬取三种财务报表并分别存入对应表。
        """
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        total = len(self.tasks) * len(self.symbol_map)  # 任务数 * 报表类型数
        if progress and task_id is not None:
            progress.update(task_id, total=total)

        completed = 0

        for task in self.tasks:
            symbol = task['symbol']
            market = task['market']
            stock = f"{market}{symbol}"  # 例如 sh600000

            for report_type_cn, table_name in self.symbol_map.items():
                completed += 1
                if progress and task_id is not None:
                    progress.update(
                        task_id,
                        completed=completed,
                        description=f"{self.__class__.__name__} [{completed}/{total}]"
                    )

                # 使用代理池爬取
                try:
                    df = await asyncio.to_thread(
                        proxy_pool,
                        ak.stock_financial_report_sina,
                        stock=stock,
                        symbol=report_type_cn,
                    )
                except Exception as error:
                    logger.error(f"获取股票 {symbol} {report_type_cn} 数据失败: {error}")
                    continue

                if df.empty:
                    logger.warning(f"股票 {symbol} {report_type_cn} 返回空数据")
                    continue

                # 清洗数据
                df = self._rename_columns(df, symbol, market, report_type_cn)

                # 插入数据库
                try:
                    save_dataframe(
                        df,
                        table_name=table_name,
                        market="ashare",
                        primary_key=["symbol", "date"]
                    )
                    logger.info(f"股票 {symbol} {report_type_cn} 数据已保存，共 {len(df)} 条")
                except Exception as e:
                    logger.error(f"插入股票 {symbol} {report_type_cn} 数据失败: {e}")

                # await asyncio.sleep(random.randint(1, 3))

        # 爬取完成后，检查并清理全空列
        self._clean_empty_columns()

        logger.info(f"{self.__class__.__name__}: 财务数据抓取完成，共处理 {len(self.tasks)} 只股票")

    def _clean_empty_columns(self):
        """
        对三张表分别检查是否存在整列全为空的列，若有则打印列名（供修正映射表）。
        注意：不实际删除列，仅输出报告。
        """
        for table_name in self.table_names:
            # 获取表的所有列名：通过查询一条记录来获取列结构
            try:
                # 查询一行数据，获取列名
                sample_sql = f"SELECT * FROM {table_name} LIMIT 1"
                sample_df = load_dataframe(sample_sql, market=self.market)
                if sample_df.empty:
                    # 表为空，无法检查全空列，跳过
                    logger.info(f"表 {table_name} 为空，跳过全空列检查")
                    continue
                columns = sample_df.columns.tolist()
            except Exception as e:
                logger.error(f"获取表 {table_name} 的列信息失败: {e}")
                continue

            # 检查每个非主键列是否整列为空
            columns_to_report = []
            for col in columns:
                # 跳过主键列
                if col in ['symbol', 'date', 'market']:
                    continue
                # 查询该列非空记录数
                check_sql = f"SELECT COUNT(*) FROM {table_name} WHERE {col} IS NOT NULL"
                try:
                    count_df = load_dataframe(check_sql, market=self.market)
                    non_null_count = count_df.iloc[0, 0] if not count_df.empty else 0
                    if non_null_count == 0:
                        columns_to_report.append(col)
                except Exception as e:
                    logger.error(f"检查表 {table_name} 列 {col} 的空值情况失败: {e}")

            if columns_to_report:
                # 只打印，不实际删除列
                # print(f"表 {table_name} 中以下列全为空，请检查映射表是否需要修正：{columns_to_report}")
                logger.info(f"表 {table_name} 全空列：{columns_to_report}")
            else:
                logger.info(f"表 {table_name} 无全空列")