import aiosqlite
import logging
import os

logger = logging.getLogger(__name__)

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS user_icp (
    user_id INTEGER PRIMARY KEY,
    icp_text TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def _ensure_db(db_path: str) -> None:
    """Create the database directory and table if they don't exist."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_INIT_SQL)
        await db.commit()


async def save_icp(db_path: str, user_id: int, icp_text: str) -> None:
    """Save or update a user's ICP."""
    await _ensure_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO user_icp (user_id, icp_text) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET icp_text = ?, updated_at = CURRENT_TIMESTAMP",
            (user_id, icp_text, icp_text),
        )
        await db.commit()
    logger.info("Saved ICP for user %d", user_id)


async def get_icp(db_path: str, user_id: int) -> str | None:
    """Retrieve a user's ICP, or None if not set."""
    await _ensure_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT icp_text FROM user_icp WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None
