"""
端到端测试

测试完整的业务流程：
1. 启动后端服务
2. 创建人格
3. 添加 RAG 语料
4. 检索相似语料
5. 技法分析
6. 重写工作流
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx

# 测试配置
BASE_URL = "http://localhost:8080/v1"
TIMEOUT = 30


class E2ETestRunner:
    """端到端测试运行器"""

    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
        self.persona_id = None
        self.passed = 0
        self.failed = 0
        self.errors = []

    async def cleanup(self):
        """清理测试数据"""
        if self.persona_id:
            try:
                await self.client.delete(f"/personas/{self.persona_id}")
            except Exception:
                pass
        await self.client.aclose()

    def log(self, message: str, status: str = "INFO"):
        """打印日志"""
        symbols = {"INFO": "[INFO]", "PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}
        symbol = symbols.get(status, "[INFO]")
        print(f"  {symbol} {message}")

    async def test_health_check(self):
        """测试健康检查"""
        print("\n1. 健康检查")
        try:
            resp = await self.client.get("/health")
            if resp.status_code == 200:
                self.log("后端服务运行正常", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"健康检查失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"无法连接后端服务: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("健康检查", str(e)))
            return False

    async def test_create_persona(self):
        """测试创建人格"""
        print("\n2. 创建人格")
        try:
            resp = await self.client.post("/personas", json={
                "name": "E2E测试人格",
                "description": "端到端测试创建的人格",
                "source_texts": ["这是一段测试文本，用于创建人格。"]
            })
            if resp.status_code == 200:
                data = resp.json()
                self.persona_id = data.get("id") or data.get("persona_id")
                self.log(f"人格创建成功: ID={self.persona_id}", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"创建失败: {resp.status_code} {resp.text}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"创建异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("创建人格", str(e)))
            return False

    async def test_list_personas(self):
        """测试获取人格列表"""
        print("\n3. 获取人格列表")
        try:
            resp = await self.client.get("/personas")
            if resp.status_code == 200:
                data = resp.json()
                personas = data.get("personas", [])
                self.log(f"获取成功，共 {len(personas)} 个人格", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"获取失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"获取异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("获取人格列表", str(e)))
            return False

    async def test_add_rag_corpus(self):
        """测试添加 RAG 语料"""
        print("\n4. 添加 RAG 语料")
        if not self.persona_id:
            self.log("跳过：无人格 ID", "WARN")
            return False

        test_texts = [
            "今天我们来聊聊Excel，这个工具你真的会用吗？很多人以为自己会用Excel，其实根本不会。",
            "Excel里面有几个功能，学会了直接让你效率翻倍。第一个就是数据透视表，很多人听都没听过。",
            "你知道为什么有些人月薪3000，有些人月薪30000吗？差距就在这些小技巧上。",
        ]

        try:
            resp = await self.client.post(f"/personas/{self.persona_id}/rag/corpus", json={
                "texts": test_texts,
                "video_ids": ["test_video_1", "test_video_2", "test_video_3"]
            })
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"语料添加成功: {data.get('added_count')} 条", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"添加失败: {resp.status_code} {resp.text}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"添加异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("添加RAG语料", str(e)))
            return False

    async def test_rag_stats(self):
        """测试获取 RAG 统计"""
        print("\n5. 获取 RAG 统计")
        if not self.persona_id:
            self.log("跳过：无人格 ID", "WARN")
            return False

        try:
            resp = await self.client.get(f"/personas/{self.persona_id}/rag/stats")
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"统计: 文档数={data.get('document_count')}, 总字符={data.get('total_chars')}", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"获取失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"获取异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("RAG统计", str(e)))
            return False

    async def test_rag_search(self):
        """测试 RAG 检索"""
        print("\n6. RAG 相似语料检索")
        try:
            resp = await self.client.post("/rag/search", json={
                "query": "Excel技巧效率提升",
                "persona_id": self.persona_id or "",
                "top_k": 3
            })
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                self.log(f"检索成功: 找到 {len(results)} 条相似语料", "PASS")
                for i, r in enumerate(results[:2]):
                    similarity = 1 - r.get("distance", 0)
                    self.log(f"  示例 {i+1}: 相似度 {similarity:.2%}")
                self.passed += 1
                return True
            else:
                self.log(f"检索失败: {resp.status_code} {resp.text}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"检索异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("RAG检索", str(e)))
            return False

    async def test_list_hooks(self):
        """测试获取钩子列表"""
        print("\n7. 获取钩子列表")
        try:
            resp = await self.client.get("/hooks")
            if resp.status_code == 200:
                data = resp.json()
                hooks = data.get("hooks", [])
                self.log(f"获取成功: 共 {len(hooks)} 个钩子", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"获取失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"获取异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("获取钩子", str(e)))
            return False

    async def test_tasks_list(self):
        """测试获取任务列表"""
        print("\n8. 获取任务列表")
        try:
            resp = await self.client.get("/tasks")
            if resp.status_code == 200:
                data = resp.json()
                tasks = data.get("tasks", [])
                self.log(f"获取成功: 共 {len(tasks)} 个任务", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"获取失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"获取异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("获取任务", str(e)))
            return False

    async def test_delete_persona(self):
        """测试删除人格"""
        print("\n9. 删除人格")
        if not self.persona_id:
            self.log("跳过：无人格 ID", "WARN")
            return False

        try:
            resp = await self.client.delete(f"/personas/{self.persona_id}")
            if resp.status_code == 200:
                self.log("人格删除成功", "PASS")
                self.passed += 1
                return True
            else:
                self.log(f"删除失败: {resp.status_code}", "FAIL")
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"删除异常: {e}", "FAIL")
            self.failed += 1
            self.errors.append(("删除人格", str(e)))
            return False

    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("端到端测试开始")
        print("=" * 60)

        start_time = time.time()

        # 顺序执行测试
        tests = [
            self.test_health_check,
            self.test_create_persona,
            self.test_list_personas,
            self.test_add_rag_corpus,
            self.test_rag_stats,
            self.test_rag_search,
            self.test_list_hooks,
            self.test_tasks_list,
            self.test_delete_persona,
        ]

        for test in tests:
            try:
                await test()
            except Exception as e:
                self.log(f"测试异常: {e}", "FAIL")
                self.failed += 1
                self.errors.append((test.__name__, str(e)))

        elapsed = time.time() - start_time

        # 打印总结
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"  通过: {self.passed}")
        print(f"  失败: {self.failed}")
        print(f"  耗时: {elapsed:.2f}s")

        if self.errors:
            print("\n  错误详情:")
            for name, err in self.errors:
                print(f"    - {name}: {err}")

        print("=" * 60)

        return self.failed == 0


async def main():
    """主函数"""
    runner = E2ETestRunner()
    try:
        success = await runner.run_all()
        sys.exit(0 if success else 1)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
