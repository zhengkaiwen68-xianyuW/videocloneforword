"""
默认人格种子数据加载器

在全新数据库上运行，导入预设人格（如"聪圣"）。
用法:
    python seed/load_personas.py

也可以通过 main.py 的 lifespan 自动检测并加载。
"""

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent


async def load_default_personas(persona_repo) -> int:
    """
    从 seed/*.json 加载默认人格到数据库。

    Args:
        persona_repo: PersonaRepository 实例

    Returns:
        导入的人格数量
    """
    loaded = 0
    for json_file in sorted(SEED_DIR.glob("*_persona.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            persona_id = data.get("id")
            if not persona_id:
                logger.warning(f"Skipping {json_file.name}: missing 'id'")
                continue

            # 检查是否已存在
            existing = await persona_repo.get_by_id(persona_id)
            if existing:
                logger.info(f"Persona '{data.get('name', persona_id)}' already exists, skipping")
                continue

            # 写入数据库
            await persona_repo.db.execute(
                """INSERT INTO personas
                (id, name, verbal_tics, grammar_prefs, logic_architecture,
                 temporal_patterns, raw_json, source_asr_texts,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (
                    persona_id,
                    data.get("name", ""),
                    json.dumps(data.get("verbal_tics", []), ensure_ascii=False),
                    json.dumps(data.get("grammar_prefs", []), ensure_ascii=False),
                    json.dumps(data.get("logic_architecture", {}), ensure_ascii=False),
                    json.dumps(data.get("temporal_patterns", {}), ensure_ascii=False),
                    json.dumps(data.get("raw_json", {}), ensure_ascii=False),
                    json.dumps(data.get("source_asr_texts", []), ensure_ascii=False),
                ),
            )
            await persona_repo.db.commit()
            logger.info(f"Loaded default persona: {data.get('name', persona_id)} ({json_file.name})")
            loaded += 1

        except Exception as e:
            logger.error(f"Failed to load seed {json_file.name}: {e}")

    return loaded


# ===== CLI 入口 =====
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 将项目根目录加入 sys.path
    project_root = SEED_DIR.parent
    sys.path.insert(0, str(project_root))

    from persona_engine.storage.persona_repo import PersonaRepository
    from persona_engine.storage.database import database

    async def main():
        await database.initialize()
        repo = PersonaRepository()
        count = await load_default_personas(repo)
        print(f"Done. Loaded {count} default persona(s).")
        await database.close()

    asyncio.run(main())
