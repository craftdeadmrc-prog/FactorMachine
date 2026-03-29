import logging
import threading
import time
import requests
from requests.exceptions import RequestException
from core.config import PROXY_FILE

logger = logging.getLogger(__name__)

_thread_local = threading.local()

def _load_proxies_from_file():
    """从文件加载代理列表，每行一个代理"""
    if not PROXY_FILE:
        return []
    try:
        with open(PROXY_FILE, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies
    except Exception as e:
        logger.error(f"加载代理文件失败: {e}")
        return []

# 全局代理列表（启动时加载）
_proxy_list = _load_proxies_from_file()

def refresh_proxies():
    """刷新代理列表（支持动态更新）"""
    global _proxy_list
    _proxy_list = _load_proxies_from_file()
    logger.info(f"代理列表已刷新，共 {len(_proxy_list)} 个代理")

def set_current_proxy(proxy):
    """设置当前线程使用的代理地址"""
    _thread_local.proxy = proxy
    logger.debug(f"线程 {threading.current_thread().name} 设置代理: {proxy}")

def get_current_proxy():
    """获取当前线程使用的代理地址"""
    return getattr(_thread_local, 'proxy', None)

def set_use_proxy(use):
    """设置当前线程是否启用代理"""
    _thread_local.use_proxy = use
    logger.debug(f"线程 {threading.current_thread().name} 代理启用标志: {use}")

def get_use_proxy():
    """获取当前线程是否启用代理"""
    return getattr(_thread_local, 'use_proxy', False)

# 保存原始方法
_original_request = requests.Session.request

def _patched_request(self, method, url, **kwargs):
    """有选择性地为请求添加代理"""
    if get_use_proxy():
        proxy = get_current_proxy()
        if proxy:
            # 确保代理格式正确（支持 http/https）
            kwargs['proxies'] = {'http': proxy, 'https': proxy}
            logger.debug(f"使用代理 {proxy} 请求 {url}")
    return _original_request(self, method, url, **kwargs)

# 应用猴子补丁（全局一次）
requests.Session.request = _patched_request

def _get_callable_name(func):
    """获取可调用对象的友好名称，优先使用 __name__，lambda 特殊处理"""
    if hasattr(func, '__name__'):
        name = func.__name__
        if name == '<lambda>':
            name = func.__qualname__
        return ".".join(func.__qualname__.split(".")[:1])
    elif hasattr(func, '__class__'):
        return func.__class__.__name__
    else:
        return str(func)

def proxy_pool(func, *args, **kwargs):
    """
    使用代理池调用函数，自动重试网络异常。
    优先尝试不使用代理（不记录 INFO 日志，失败快速进入代理循环）。
    :param func: 要调用的函数（如 ak.fund_portfolio_hold_em）
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return: 函数返回值
    """
    func_name = _get_callable_name(func)

    # 1. 优先尝试无代理直接调用（不记录 INFO 日志，失败不等待）
    try:
        set_use_proxy(False)
        result = func(*args, **kwargs)
        # 成功直接返回，不打印任何 INFO 日志
        return result
    except Exception as e:
        # 无代理失败，记录 DEBUG 级别日志后继续代理流程
        logger.debug(f"无代理调用 {func_name} 失败: {e}，将尝试使用代理")
    # 注意：无代理失败后，use_proxy 标志可能仍为 False，后续代理循环会重新设置

    proxies = _proxy_list
    if not proxies:
        logger.warning("无可用代理，直接调用原始函数（重试无代理）")
        # 如果没有代理，再次尝试无代理（因为之前可能失败，但可能是临时网络问题）
        set_use_proxy(False)
        return func(*args, **kwargs)

    # 每个线程维护自己的代理索引
    if not hasattr(_thread_local, 'index'):
        _thread_local.index = 0

    start_index = _thread_local.index
    for i in range(len(proxies)):
        idx = (start_index + i) % len(proxies)
        proxy = proxies[idx]
        set_current_proxy(proxy)
        set_use_proxy(True)
        try:
            result = func(*args, **kwargs)
            # 成功后更新索引，下次从下一个代理开始
            _thread_local.index = (idx + 1) % len(proxies)
            logger.info(f"函数 {func_name} 使用代理 {proxy} 调用成功")
            return result
        except RequestException as e:
            logger.warning(f"代理 {proxy} 请求失败: {e}")
            continue
        except Exception as e:
            logger.error(f"函数 {func_name} 发生非网络异常: {e}")
            raise
        finally:
            set_use_proxy(False)

    raise Exception("所有代理均无法连接，请检查代理列表或网络")