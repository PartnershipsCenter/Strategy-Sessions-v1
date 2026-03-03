"""SQLite knowledge base for conferences, exhibitors, and scoring runs."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    total_exhibitors INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS exhibitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conference_id INTEGER NOT NULL,
    company_name TEXT NOT NULL,
    detail_page_url TEXT,
    website_url TEXT,
    linkedin_url TEXT,
    contact_url TEXT,
    description TEXT DEFAULT '',
    booth_location TEXT DEFAULT '',
    categories TEXT DEFAULT '[]',
    logo_url TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enriched_at TIMESTAMP,
    enrichment_data TEXT DEFAULT '{}',
    FOREIGN KEY (conference_id) REFERENCES conferences(id),
    UNIQUE(conference_id, company_name)
);

CREATE TABLE IF NOT EXISTS scoring_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conference_id INTEGER NOT NULL,
    icp_text TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    total_scored INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (conference_id) REFERENCES conferences(id)
);

CREATE TABLE IF NOT EXISTS scored_exhibitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scoring_run_id INTEGER NOT NULL,
    exhibitor_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    reasoning TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    russian_speaking_leaders TEXT DEFAULT '',
    FOREIGN KEY (scoring_run_id) REFERENCES scoring_runs(id),
    FOREIGN KEY (exhibitor_id) REFERENCES exhibitors(id),
    UNIQUE(scoring_run_id, exhibitor_id)
);

CREATE TABLE IF NOT EXISTS user_icp (
    user_id TEXT PRIMARY KEY,
    icp_text TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class ExhibitorRow:
    """An exhibitor as stored in the database."""
    id: int = 0
    conference_id: int = 0
    company_name: str = ""
    detail_page_url: str = ""
    website_url: str = ""
    linkedin_url: str = ""
    contact_url: str = ""
    description: str = ""
    booth_location: str = ""
    categories: list[str] = field(default_factory=list)
    logo_url: str = ""
    scraped_at: str = ""
    enriched_at: str = ""
    enrichment_data: dict = field(default_factory=dict)


@dataclass
class ScoredExhibitorRow:
    """A scored exhibitor result."""
    exhibitor_id: int = 0
    company_name: str = ""
    score: int = 0
    reasoning: str = ""
    summary: str = ""
    russian_speaking_leaders: str = ""
    website_url: str = ""
    linkedin_url: str = ""
    contact_url: str = ""
    detail_page_url: str = ""
    description: str = ""
    categories: list[str] = field(default_factory=list)
    booth_location: str = ""


class DB:
    """Async SQLite knowledge base."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self) -> None:
        """Create tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        logger.info("Database initialized at %s", self.db_path)

    # ── Conferences ──────────────────────────────────────────────

    async def upsert_conference(self, name: str, url: str) -> int:
        """Create or get a conference, return its ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO conferences (name, url) VALUES (?, ?)
                   ON CONFLICT(url) DO UPDATE SET name = excluded.name
                   RETURNING id""",
                (name, url),
            )
            row = await cursor.fetchone()
            await db.commit()
            return row[0]

    async def update_conference_count(
        self, conference_id: int, count: int
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE conferences SET total_exhibitors = ? WHERE id = ?",
                (count, conference_id),
            )
            await db.commit()

    async def get_conference_by_url(self, url: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM conferences WHERE url = ?", (url,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_conferences(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM conferences ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Exhibitors ───────────────────────────────────────────────

    async def upsert_exhibitor(
        self,
        conference_id: int,
        company_name: str,
        detail_page_url: str = "",
        booth_location: str = "",
        categories: list[str] | None = None,
    ) -> int:
        """Insert or update an exhibitor from the list scrape. Returns exhibitor ID."""
        cats_json = json.dumps(categories or [])
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO exhibitors (conference_id, company_name, detail_page_url,
                   booth_location, categories)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(conference_id, company_name) DO UPDATE SET
                   detail_page_url = COALESCE(NULLIF(excluded.detail_page_url, ''), detail_page_url),
                   booth_location = COALESCE(NULLIF(excluded.booth_location, ''), booth_location),
                   categories = CASE WHEN excluded.categories != '[]' THEN excluded.categories
                                     ELSE categories END
                """,
                (conference_id, company_name, detail_page_url, booth_location, cats_json),
            )
            await db.commit()
            # Get the ID
            cur2 = await db.execute(
                "SELECT id FROM exhibitors WHERE conference_id = ? AND company_name = ?",
                (conference_id, company_name),
            )
            row = await cur2.fetchone()
            return row[0]

    async def update_exhibitor_details(
        self,
        exhibitor_id: int,
        website_url: str = "",
        linkedin_url: str = "",
        contact_url: str = "",
        description: str = "",
        logo_url: str = "",
        categories: list[str] | None = None,
        booth_location: str = "",
    ) -> None:
        """Update exhibitor with data from their detail page."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            if website_url:
                updates.append("website_url = ?")
                params.append(website_url)
            if linkedin_url:
                updates.append("linkedin_url = ?")
                params.append(linkedin_url)
            if contact_url:
                updates.append("contact_url = ?")
                params.append(contact_url)
            if description:
                updates.append("description = ?")
                params.append(description)
            if logo_url:
                updates.append("logo_url = ?")
                params.append(logo_url)
            if categories:
                updates.append("categories = ?")
                params.append(json.dumps(categories))
            if booth_location:
                updates.append("booth_location = ?")
                params.append(booth_location)

            if not updates:
                return

            params.append(exhibitor_id)
            sql = f"UPDATE exhibitors SET {', '.join(updates)} WHERE id = ?"
            await db.execute(sql, params)
            await db.commit()

    async def update_exhibitor_enrichment(
        self, exhibitor_id: int, enrichment_data: dict
    ) -> None:
        """Store Tavily enrichment results."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE exhibitors
                   SET enrichment_data = ?, enriched_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (json.dumps(enrichment_data), exhibitor_id),
            )
            await db.commit()

    async def get_exhibitors(
        self, conference_id: int, only_unenriched: bool = False
    ) -> list[ExhibitorRow]:
        """Get exhibitors for a conference."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT * FROM exhibitors WHERE conference_id = ?"
            if only_unenriched:
                sql += " AND enriched_at IS NULL"
            sql += " ORDER BY company_name"
            cursor = await db.execute(sql, (conference_id,))
            rows = await cursor.fetchall()

        result = []
        for r in rows:
            result.append(
                ExhibitorRow(
                    id=r["id"],
                    conference_id=r["conference_id"],
                    company_name=r["company_name"],
                    detail_page_url=r["detail_page_url"] or "",
                    website_url=r["website_url"] or "",
                    linkedin_url=r["linkedin_url"] or "",
                    contact_url=r["contact_url"] or "",
                    description=r["description"] or "",
                    booth_location=r["booth_location"] or "",
                    categories=json.loads(r["categories"] or "[]"),
                    logo_url=r["logo_url"] or "",
                    scraped_at=r["scraped_at"] or "",
                    enriched_at=r["enriched_at"] or "",
                    enrichment_data=json.loads(r["enrichment_data"] or "{}"),
                )
            )
        return result

    async def get_exhibitor_count(self, conference_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM exhibitors WHERE conference_id = ?",
                (conference_id,),
            )
            row = await cursor.fetchone()
            return row[0]

    # ── Scoring Runs ─────────────────────────────────────────────

    async def create_scoring_run(
        self, conference_id: int, icp_text: str
    ) -> int:
        """Start a new scoring run, return its ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO scoring_runs (conference_id, icp_text) VALUES (?, ?)",
                (conference_id, icp_text),
            )
            await db.commit()
            return cursor.lastrowid

    async def save_scored_exhibitor(
        self,
        scoring_run_id: int,
        exhibitor_id: int,
        score: int,
        reasoning: str,
        summary: str,
        russian_speaking_leaders: str = "",
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO scored_exhibitors
                   (scoring_run_id, exhibitor_id, score, reasoning, summary, russian_speaking_leaders)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scoring_run_id, exhibitor_id) DO UPDATE SET
                   score = excluded.score, reasoning = excluded.reasoning,
                   summary = excluded.summary,
                   russian_speaking_leaders = excluded.russian_speaking_leaders""",
                (scoring_run_id, exhibitor_id, score, reasoning, summary, russian_speaking_leaders),
            )
            await db.commit()

    async def complete_scoring_run(
        self, scoring_run_id: int, total_scored: int
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE scoring_runs
                   SET status = 'completed', total_scored = ?,
                   completed_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (total_scored, scoring_run_id),
            )
            await db.commit()

    async def get_scored_results(
        self, scoring_run_id: int, limit: int = 50
    ) -> list[ScoredExhibitorRow]:
        """Get top scored exhibitors for a scoring run."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT se.exhibitor_id, e.company_name, se.score, se.reasoning,
                   se.summary, se.russian_speaking_leaders,
                   e.website_url, e.linkedin_url, e.contact_url,
                   e.detail_page_url, e.description, e.categories, e.booth_location
                   FROM scored_exhibitors se
                   JOIN exhibitors e ON se.exhibitor_id = e.id
                   WHERE se.scoring_run_id = ?
                   ORDER BY se.score DESC
                   LIMIT ?""",
                (scoring_run_id, limit),
            )
            rows = await cursor.fetchall()

        return [
            ScoredExhibitorRow(
                exhibitor_id=r["exhibitor_id"],
                company_name=r["company_name"],
                score=r["score"],
                reasoning=r["reasoning"],
                summary=r["summary"],
                russian_speaking_leaders=r["russian_speaking_leaders"] or "",
                website_url=r["website_url"] or "",
                linkedin_url=r["linkedin_url"] or "",
                contact_url=r["contact_url"] or "",
                detail_page_url=r["detail_page_url"] or "",
                description=r["description"] or "",
                categories=json.loads(r["categories"] or "[]"),
                booth_location=r["booth_location"] or "",
            )
            for r in rows
        ]

    # ── User ICP ─────────────────────────────────────────────────

    async def save_icp(self, user_id: str, icp_text: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO user_icp (user_id, icp_text) VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   icp_text = ?, updated_at = CURRENT_TIMESTAMP""",
                (user_id, icp_text, icp_text),
            )
            await db.commit()

    async def get_icp(self, user_id: str) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT icp_text FROM user_icp WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None
