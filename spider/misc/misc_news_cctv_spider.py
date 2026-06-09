import asyncio
import logging
import pandas as pd
import akshare as ak

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


@task(description="获取央视新闻新闻数据")
class MiscNewsCCTVSpider(BaseSpider):
    resource = "misc"
    table = "news_cctv"

    def _rename_columns(self, df: pd.DataFrame, date: str) -> pd.DataFrame:
        pass

    def check(self):
        task = self.tasks[0]  # Misc类别只有一个任务
        start_date = task.get("start_date")
        end_date = task.get("end_date")
        
        # 确保start_date不早于2016-03-30（数据最早可用日期）
        min_available_date = pd.Timestamp("2016-03-30")
        start_date = min_available_date if start_date <= min_available_date else start_date
        self.tasks[0]["start_date"] = start_date
        
        # 如果start_date > end_date，说明无需抓取
        if start_date > end_date:
            logger.info(f"start_date {start_date.date()} 晚于 end_date {end_date.date()}，无需抓取")
            self.tasks = []
            return
        
        # 生成完整日期范围
        full_date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        self.tasks[0]["dates_to_fetch"] = full_date_range
        if full_date_range.empty:
            logger.info("日期范围为空，无需抓取")
            self.tasks = []
            return
        
        # 查询数据库中该范围内已存在的日期
        sql = self.loadTable("distinct date", self.table)
        df_exist = load_dataframe(sql, self.market)
        # 数据库date是时间戳，转换为date对象进行比较
        existing_dates = set(pd.to_datetime(df_exist['date']).dt.date)
        # 过滤掉已存在的日期
        dates_to_fetch = [
            d for d in full_date_range 
            if d.date() not in existing_dates
        ]
        if not dates_to_fetch:
            logger.info(f"日期范围 {start_date.date()} 至 {end_date.date()} 的数据已全部存在，无需更新")
            self.tasks = []
            return
        # 将需要抓取的日期列表存入task，供run方法使用
        self.tasks[0]["dates_to_fetch"] = dates_to_fetch
        logger.info(f"过滤掉 {len(full_date_range) - len(dates_to_fetch)} 天已存在数据，剩余 {len(dates_to_fetch)} 天待抓取")

    async def run(self):
        task = self.tasks[0]

        total = 0
        # 优先使用check方法计算好的待抓取日期列表
        date_range = task["dates_to_fetch"]
        start_date = date_range[0]
        end_date = date_range[-1]    
        total = len(date_range)
        
        if total == 0:
            logger.info("No dates to fetch.")
            return
            
        logger.info(f"{self.__class__.__name__}: 开始处理 {total} 天数据，范围: {start_date.date()} 至 {end_date.date()}")

        # 异步并发执行单个日期抓取
        async def fetch_date(date: pd.Timestamp):
            date_str = date.strftime("%Y%m%d")
            try:
                index = 0
                while True:
                    df = await asyncio.to_thread(
                        proxy_pool,
                        ak.news_cctv,
                        date=date_str
                    )
                    if not df.empty or index>=5:
                        break
                    index+=1
                    await asyncio.sleep(1)
                if df.empty:
                    logger.warning(f"央视新闻 {date_str} 无数据或返回为空")
                    return None
                df["date"] = pd.to_datetime(date_str)
                df["symbol"] = "misc"
                return df
            except Exception as e:
                logger.error(f"获取央视新闻 {date_str} 数据失败: {e}")
                return None

        # 分批并发执行，每批任务结束后统一写入一批
        batch_size = 10
        for i in range(0, total, batch_size):
            batch = date_range[i:i+batch_size]
            batch_dfs = []
            combined_df = []
            tasks = [fetch_date(date) for date in batch]
            batch_results = await asyncio.gather(*tasks)
            
            for result in batch_results:
                if isinstance(result, pd.DataFrame) and not result.empty:
                    batch_dfs.append(result)
            
            # 每批处理完后统一写入
            if batch_dfs:
                combined_df = pd.concat(batch_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        combined_df,
                        table=self.table,
                        db=self.market,
                        primary_key=["content","date"]
                    )
                except Exception as e:
                    logger.error(f"插入央视新闻数据失败: {e}")
            processed = min(i + batch_size, total)
            logger.info(f"{self.__class__.__name__} 已处理 {processed}/{total} 天")
            await asyncio.sleep(10)

        logger.info(f"{self.__class__.__name__}: 数据抓取完成，已处理 {total} 天")
