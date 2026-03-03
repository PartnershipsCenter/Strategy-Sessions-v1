"""ICP storage — thin wrapper around core.db for backward compatibility."""

from core.db import DB

_db: DB | None = None


async def _get_db(db_path: str) -> DB:
    global _db
    if _db is None or _db.db_path != db_path:
        _db = DB(db_path)
        await _db.init()
    return _db


async def save_icp(db_path: str, user_id: int, icp_text: str) -> None:
    db = await _get_db(db_path)
    await db.save_icp(str(user_id), icp_text)


async def get_icp(db_path: str, user_id: int) -> str | None:
    db = await _get_db(db_path)
    return await db.get_icp(str(user_id))
