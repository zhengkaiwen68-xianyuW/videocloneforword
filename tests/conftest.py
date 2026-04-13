# tests/conftest.py
"""
共享测试配置和 fixtures

解决的问题：
- sys.path.insert(0, '..') 在 CI 环境中因工作目录不同而失效
- 提供全局可用的 event_loop fixture（pytest-asyncio 3.x 兼容）
"""
import sys
import os

# 将项目根目录加入 sys.path，无论从哪里运行 pytest 都正常
# 注意：conftest.py 所在目录是 tests/，所以 parent 就是项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
