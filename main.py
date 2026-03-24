"""
主程序入口：初始化组件，启动 Web 线程和定时器。
"""
import asyncio
import threading
import logging

from core.init import init
from core.scheduler import Scheduler
from core.timer import Timer
import web

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # 初始化数据库连接
    init()
    logger.info("初始化完成")

    # 获取当前事件循环（主循环）
    loop = asyncio.get_running_loop()
    web.set_main_loop(loop)

    # 创建全局调度器（可配置并发数）
    scheduler = Scheduler(max_concurrency=3)
    # 注入到 web 模块
    web.set_scheduler(scheduler)

    # 启动任务消费者（处理 web 提交的任务）
    asyncio.create_task(web.task_consumer())

    # 启动定时器
    timer = Timer(scheduler)
    # 添加示例定时任务：每天凌晨3点执行 crypto 市场爬虫（覆盖更新）
    # timer.add_cron_job("CryptoBinanceSpot1mKlinesSpider", "crypto", hour=3, minute=0)
    # 可继续添加其他市场的定时任务
    # timer.add_cron_job("FundDailySpider", "fund", hour=2, minute=0)
    # timer.add_cron_job("AshareDailySpider", "ashare", hour=1, minute=0)
    timer.start()

    # 启动 Web 面板（在独立线程中运行 Flask）
    web_thread = threading.Thread(target=web.run_web_server, args=('0.0.0.0', 5000), daemon=True)
    web_thread.start()
    logger.info("Web 面板已启动，访问 http://localhost:5000")

    # 保持主循环运行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        timer.shutdown()
        # 等待所有任务完成（可选）
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())