# spider/misc/misc_research_report_spider.py
import asyncio
import logging
import pandas as pd
import json

from ..base_spider import BaseSpider
from core.storage import save_dataframe, load_dataframe
from core.proxy import proxy_pool
from core.scheduler import task

logger = logging.getLogger(__name__)


# @task(description="获取东方财富研报数据")
class MiscResearchReportSpider(BaseSpider):
    resource = "misc"
    table = "research_report"
    
    # 东方财富研报列表API
    REPORT_LIST_API = "https://reportapi.eastmoney.com/report/list2"
    # 研报详情页基础URL
    REPORT_DETAIL_BASE = "https://data.eastmoney.com/report/info/{info_code}.html"
    
    # 字段映射（东方财富字段 -> 数据库字段）
    rename_map = {
        'infoCode': 'info_code',
        'title': 'title',
        'stockCode': 'symbol',
        'orgName': 'org_name',
        'orgSName': 'org_sname',
        'publishDate': 'date',
        'emRatingName': 'em_rating_name',
        'emRatingValue': 'em_rating_value',
        'ratingChange': 'rating_change',
        'market': 'market',
        'attachSize': 'attach_size',
        'attachPages': 'attach_pages',
        'predictThisYearEps': 'predict_this_year_eps',
        'predictThisYearPe': 'predict_this_year_pe',
        'predictNextYearEps': 'predict_next_year_eps',
        'predictNextYearPe': 'predict_next_year_pe',
        'predictNextTwoYearEps': 'predict_next_two_year_eps',
        'predictNextTwoYearPe': 'predict_next_two_year_pe',
        'indvInduName': 'industry',
    }

    def _build_request_params(self, start_date: str, end_date: str, page: int, page_size: int = 50) -> dict:
        """构建研报列表请求参数"""
        return {
            "beginTime": start_date,
            "endTime": end_date,
            "industryCode": "*",
            "ratingChange": None,
            "rating": None,
            "orgCode": None,
            "code": "*",
            "rcode": "",
            "pageSize": page_size,
            "p": page,
            "pageNo": page,
            "pageNum": page,
            "pageNumber": page
        }

    def _parse_report_item(self, report_data: dict) -> dict:
        """解析单条研报数据"""
        result = {}
        # 字段映射
        for target_key, source_key in self.rename_map.items():
            if source_key in report_data:
                result[target_key] = report_data[source_key]
        
        # 处理作者信息
        author_list = report_data.get('author', [])
        if not isinstance(author_list, list):
            author_list = [author_list] if author_list else []
        result['authors'] = json.dumps(author_list, ensure_ascii=False) if author_list else '[]'
        
        # 构造详情页URL
        if result.get('info_code'):
            result['url'] = self.REPORT_DETAIL_BASE.format(info_code=result['info_code'])
        
        # 标准化日期字段
        if result.get('publish_date'):
            try:
                result['publish_date'] = pd.to_datetime(result['publish_date']).strftime("%Y-%m-%d")
            except:
                pass
        
        return result

    def _fetch_report_list_sync(self, start_date: str, end_date: str, page: int, page_size: int = 50) -> list:
        """同步方式获取研报列表（供 proxy_pool 调用）"""
        import requests
        
        params = self._build_request_params(start_date, end_date, page, page_size)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/report/',
            'Origin': 'https://data.eastmoney.com'
        }
        
        try:
            response = requests.post(
                self.REPORT_LIST_API,
                data=params,
                headers=headers,
                timeout=30
            )
            if response.status_code != 200:
                logger.error(f"研报列表请求失败，状态码: {response.status_code}")
                return []
            
            data = response.json()
            if not data or 'data' not in data:
                logger.warning("研报API返回数据格式不正确")
                return []
            
            reports = []
            for item in data['data']:
                try:
                    parsed = self._parse_report_item(item)
                    if parsed.get('info_code') and parsed.get('title'):
                        reports.append(parsed)
                except Exception as e:
                    logger.error(f"解析研报数据时出错: {e}")
                    continue
            
            return reports
        except Exception as e:
            logger.error(f"获取研报列表时出错: {e}")
            return []

    async def _fetch_report_detail_sync(self, url: str) -> str:
        """同步方式获取研报详情内容（供 proxy_pool 调用）"""
        import requests
        from bs4 import BeautifulSoup
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://data.eastmoney.com/report/'
            }
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # 从script标签中提取zwinfo数据
            for script in soup.find_all('script'):
                if script.string and 'var zwinfo=' in script.string:
                    script_content = script.string.strip()
                    json_str = script_content[len('var zwinfo='):].strip().rstrip(';')
                    zwinfo = json.loads(json_str)
                    return zwinfo.get('notice_content', '')
            return ''
        except Exception as e:
            logger.error(f"解析研报详情失败 {url}: {e}")
            return None

    def check(self):
        """增量检查：过滤已存在的研报"""
        self.tasks[0]['existing_codes'] = []
        task = self.tasks[0]
        start_date = task.get("start_date")
        end_date = task.get("end_date") 
        # 查询数据库中已存在的 info_code
        try:
            start_date_sql = str(start_date).replace("-", ".")
            end_date_sql = str(end_date).replace("-", ".")
            sql = self.loadTable("distinct info_code", self.table, f"where date >= {start_date_sql} and date <= {end_date_sql}")
            df_exist = load_dataframe(sql, self.market)
            if df_exist.empty:
                logger.info(f"日期范围 {start_date} 至 {end_date} 无历史数据，将全量抓取")
                return
            
            existing_codes = set(df_exist['info_code'].astype(str))
            logger.info(f"日期范围内已存在 {len(existing_codes)} 条研报记录")
            
            # 标记需要跳过的 info_code（实际过滤在run中按条处理，避免内存过大）
            self.tasks[0]['existing_codes'] = existing_codes
            
        except Exception as e:
            logger.error(f"检查研报数据更新状态失败: {e}")

    async def run(self):
        if not self.tasks:
            logger.info("No tasks to run.")
            return

        task = self.tasks[0]
        start_date = task.get("start_date")
        end_date = task.get("end_date")
        existing_codes = task.get("existing_codes", set())
        
        if not start_date or not end_date:
            logger.error("任务缺少日期参数")
            return
        
        logger.info(f"{self.__class__.__name__}: 开始抓取研报，范围: {start_date} 至 {end_date}")
        
        # 分页参数
        page = 1
        page_size = 50
        total_fetched = 0
        total_inserted = 0
        batch_dfs = []
        
        while True:
            # 获取一页研报列表
            try:
                reports = await asyncio.to_thread(
                    proxy_pool,
                    self._fetch_report_list_sync,
                    start_date=start_date,
                    end_date=end_date,
                    page=page,
                    page_size=page_size
                )
            except Exception as e:
                logger.error(f"第 {page} 页研报列表获取失败: {e}")
                break
            
            if not reports:
                logger.info(f"第 {page} 页无数据，抓取结束")
                break
            
            # 过滤已存在的研报 & 准备详情抓取任务
            new_reports = []
            detail_tasks = []
            
            for report in reports:
                info_code = str(report.get('info_code', ''))
                if info_code in existing_codes:
                    continue
                new_reports.append(report)
                detail_tasks.append(self._fetch_report_detail_sync(report['url']))
            
            # 并发抓取详情页内容
            if detail_tasks:
                contents = await asyncio.gather(*detail_tasks)
                for report, content in zip(new_reports, contents):
                    if isinstance(content, str):
                        report['content'] = content
                    elif isinstance(content, Exception):
                        logger.warning(f"研报详情获取失败: {report.get('title')}")
                        report['content'] = ''
                    else:
                        report['content'] = ''
            
            # 转换为DataFrame并累积
            if new_reports:
                df = pd.DataFrame(new_reports)
                # 确保必要字段
                for col in ['info_code', 'title', 'publish_date']:
                    if col not in df.columns:
                        df[col] = None
                batch_dfs.append(df)
                total_fetched += len(new_reports)
            
            # 每50条写入一次数据库
            if len(batch_dfs) >= 50:
                combined_df = pd.concat(batch_dfs, ignore_index=True)
                try:
                    save_dataframe(
                        combined_df,
                        table=self.table,
                        db=self.resource,
                        primary_key=["info_code", "date"]
                    )
                    total_inserted += len(combined_df)
                    logger.info(f"已写入 {total_inserted} 条研报数据")
                except Exception as e:
                    logger.error(f"批量插入研报数据失败: {e}")
                batch_dfs = []
            
            page += 1
            # 避免请求过快
            await asyncio.sleep(1)
        
        # 写入剩余数据
        if batch_dfs:
            combined_df = pd.concat(batch_dfs, ignore_index=True)
            try:
                save_dataframe(
                    combined_df,
                    table=self.table,
                    db=self.resource,
                    primary_key=["info_code", "date"]
                )
                total_inserted += len(combined_df)
                logger.info(f"最终写入 {len(combined_df)} 条研报数据")
            except Exception as e:
                logger.error(f"插入剩余研报数据失败: {e}")
        
        logger.info(f"{self.__class__.__name__}: 抓取完成，共获取 {total_fetched} 条，新增入库 {total_inserted} 条")
