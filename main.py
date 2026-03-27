import uvicorn
import os
import sys

# 确保能正确导入 core 和 web 模块
# 无论从哪个目录启动脚本，都将项目根目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if __name__ == "__main__":
    # ----------------------
    # 配置项
    # ----------------------
    HOST = "0.0.0.0"  # 监听所有网络接口
    PORT = 8000       # 端口号
    RELOAD = True     # 开发模式下开启热重载（生产环境建议设为 False）

    print("-" * 50)
    print(f"FactorMachine Web Panel Starting...")
    print(f"Access URL: http://{HOST}:{PORT}")
    print(f"Project Root: {PROJECT_ROOT}")
    print("-" * 50)

    # 启动 ASGI 服务器
    # 这里指定 app 为 "web.app:app"，这样 uvicorn 会找到 web/app.py 中的 app 实例
    uvicorn.run(
        "web.app:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
        log_level="info"
    )