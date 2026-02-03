# spider/base_spider.py
import abc
import pandas as pd
from typing import List, Tuple, Dict, Optional
import akshare as ak
from core.storage import save_dataframe, load_dataframe


class BaseSpider(abc.ABC):
    resource = None      # 数据源标识，如 "eastmoney"
    table_name = None    # 存储到的表名
    
    # 市场代码获取函数映射
    _MARKET_FETCHERS = {
        "ashare": "_fetch_ashare_codes",
        "fund": "_fetch_fund_codes",
    }

    @abc.abstractmethod
    async def run(self, start_date: str = None, end_date: str = None):
        """
        具体爬虫接口
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        """
        pass
    
    @abc.abstractmethod
    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        pass        
    
    @classmethod
    def _fetch_ashare_codes(cls) -> List[Tuple[str, str]]:
        """
        获取A股代码列表，返回[(market, code), ...]
        """
        codes = []
        
        # 沪市主板A股
        try:
            sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
            if sh_df is not None and not sh_df.empty:
                codes.extend([("sh", code ) 
                            for code in sh_df["证券代码"].tolist()])
        except:
            pass
            
        # 深市主板A股  
        try:
            sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
            if sz_df is not None and not sz_df.empty:
                codes.extend([("sz", code ) 
                            for code in sz_df["A股代码"].tolist()])
        except:
            pass
            
        return codes
    
    @classmethod
    def _fetch_fund_codes(cls) -> List[Tuple[str, str]]:
        """
        获取基金代码列表，返回[(market, code), ...]
        """
        codes = []
        symbols = ['ETF基金','LOF基金','封闭式基金']        
        try:
            for symbol in symbols:
                df = ak.fund_etf_category_sina(symbol=symbol)
                if df is not None and not df.empty:
                    for raw_code in df["代码"].tolist():
                        codes.append((raw_code[:2], raw_code[2:])) 
        except:
            pass
        return codes
    
    @classmethod
    def get_one_market(cls,market: str)-> List[str]:
            df = load_dataframe("codes_"+market)
            if df.empty:
                fetcher_name = cls._MARKET_FETCHERS[market]
                fetcher = getattr(cls, fetcher_name)
                codes =  fetcher()
                df = pd.DataFrame({market: codes})
                save_dataframe(df, "codes_"+market)
            else:
                codes = df[market]
            return codes
            

    @classmethod
    def get_codes(
        cls, 
        markets: List[str],
    ) -> Dict[str, List[Tuple[str, str]]]:
        """
        获取指定市场的代码列表
        参数:
            markets: 市场列表，如 ["ashare", "fund"]            
        返回:
            Dict[str, List[Tuple[str, str]]]: 
                key为市场名，value为[(market_prefix, code), ...]列表
        """
        # 尝试从文件读取
        result = {}
                
        # 如果需要更新，获取数据并保存
        for market in markets:  
            df = load_dataframe("codes_"+market)
            if df.empty:
                codes = cls.get_one_market(cls.get_one_market(market))
                df[market] = codes
            result[market] = df[market].tolist()
        return result
