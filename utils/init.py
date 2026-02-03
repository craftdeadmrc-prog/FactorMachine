"""
量化分析工具包
"""
# 首先导入并设置字体（在导入其他可能使用matplotlib的模块之前）
try:
    from .visualization.font_setup import setup_chinese_font
    setup_chinese_font()
except:
    pass

from numerical.clearner import *
from .normalize import *
from .stats import *
from .visualization import *
from .analysis import *

# 创建必要的目录
import os
directories = ['numerical', 'normalize', 'stats', 'analysis', 'visualization']
for directory in directories:
    dir_path = os.path.join(os.path.dirname(__file__), directory)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)