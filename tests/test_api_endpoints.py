"""
API 端点测试

使用 httpx.AsyncClient 测试技法相关 API 端点：
- POST /v1/personas/{id}/analyze-techniques
- GET  /v1/personas/{id}/techniques
- GET  /v1/hooks
- GET  /v1/hooks/{id}
- DELETE /v1/hooks/{id}
- GET  /v1/personas/{id}/hook-stats
- GET  /v1/health
- GET  /v1/debug/concurrency
"""

import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from main import get_app


# ── Fixtures ──

@pytest.fixture
def app():
    """创建 FastAPI 应用实例"""
    return get_app()


@pytest.fixture
async def client(app):
    """创建异步 HTTP 客户端"""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ── Health & Debug ──

class TestHealthEndpoints:
    """健康检查和调试端点"""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """GET /v1/health"""
        response = await client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_root(self, client):
        """GET /"""
        response = await client.get("/")
        # 可能返回 HTML 或 404
        assert response.status_code in (200, 404)


# ── Hook Endpoints ──

class TestHookEndpoints:
    """钩子 API 端点测试"""

    @pytest.mark.asyncio
    async def test_list_hooks_empty(self, client):
        """GET /v1/hooks - 空列表"""
        with patch("persona_engine.api.routes_technique.technique_repo") as mock_repo:
            mock_repo.search_hooks = AsyncMock(return_value=[])
            response = await client.get("/v1/hooks")

        assert response.status_code == 200
        data = response.json()
        assert "hooks" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_hooks_with_persona_filter(self, client):
        """GET /v1/hooks?persona_id=xxx - 按人格筛选"""
        from persona_engine.core.types import HookAnalysis, HookType

        mock_hook = HookAnalysis(
            hook_text="测试钩子",
            hook_type=HookType.REVERSE_LOGIC,
            psychological_mechanism="测试",
            structural_formula="测试",
            why_it_works="测试",
            reconstruction_template="测试",
            source_video_url="",
            persona_id="p1",
        )

        with patch("persona_engine.api.routes_technique.technique_repo") as mock_repo:
            mock_repo.get_hooks_by_persona = AsyncMock(return_value=[mock_hook])
            response = await client.get("/v1/hooks?persona_id=p1")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 0

    @pytest.mark.asyncio
    async def test_get_hook_not_found(self, client):
        """GET /v1/hooks/{id} - 不存在"""
        with patch("persona_engine.api.routes_technique.technique_repo") as mock_repo:
            mock_repo.get_hook_by_id = AsyncMock(return_value=None)
            response = await client.get("/v1/hooks/nonexistent")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_hook_not_found(self, client):
        """DELETE /v1/hooks/{id} - 不存在"""
        with patch("persona_engine.api.routes_technique.technique_repo") as mock_repo:
            mock_repo.delete_hook = AsyncMock(return_value=False)
            response = await client.delete("/v1/hooks/nonexistent")

        assert response.status_code == 404


# ── Persona Technique Endpoints ──

class TestPersonaTechniqueEndpoints:
    """人格技法端点测试"""

    @pytest.mark.asyncio
    async def test_get_persona_techniques(self, client):
        """GET /v1/personas/{id}/techniques"""
        with patch("persona_engine.api.routes_technique.knowledge_base") as mock_kb:
            mock_kb.get_persona_techniques_summary = AsyncMock(return_value={
                "topic_techniques": None,
                "hook_stats": {"total": 0, "type_distribution": {}, "most_used_type": None},
                "structure_count": 0,
            })
            response = await client.get("/v1/personas/test_id/techniques")

        assert response.status_code == 200
        data = response.json()
        assert "topic_techniques" in data
        assert "hook_stats" in data
        assert "structure_count" in data

    @pytest.mark.asyncio
    async def test_get_hook_stats(self, client):
        """GET /v1/personas/{id}/hook-stats"""
        with patch("persona_engine.api.routes_technique.knowledge_base") as mock_kb:
            mock_kb.get_hook_stats = AsyncMock(return_value={
                "total": 5,
                "type_distribution": {"reverse_logic": 3, "pain_point": 2},
                "most_used_type": "reverse_logic",
            })
            response = await client.get("/v1/personas/test_id/hook-stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["most_used_type"] == "reverse_logic"

    @pytest.mark.asyncio
    async def test_analyze_techniques_persona_not_found(self, client):
        """POST /v1/personas/{id}/analyze-techniques - 人格不存在"""
        with patch("persona_engine.api.routes_technique.persona_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(side_effect=Exception("Not found"))
            response = await client.post("/v1/personas/nonexistent/analyze-techniques")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_analyze_techniques_no_asr_texts(self, client):
        """POST /v1/personas/{id}/analyze-techniques - 无 ASR 文本"""
        mock_persona = MagicMock()
        mock_persona.source_asr_texts = []

        with patch("persona_engine.api.routes_technique.persona_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value=mock_persona)
            response = await client.post("/v1/personas/test_id/analyze-techniques")

        assert response.status_code == 400
