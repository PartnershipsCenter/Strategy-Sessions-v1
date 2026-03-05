"""FastAPI routes for the conference scanner web app."""

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from core.config import Config, load_config
from core.db import DB
from core.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory store for active pipeline runs (for SSE progress)
_active_runs: dict[str, asyncio.Queue] = {}


class ScanRequest(BaseModel):
    url: str
    icp: str
    conference_name: str = ""
    force_rescrape: bool = False


class ScanResponse(BaseModel):
    run_id: str
    message: str


# ── Static files ─────────────────────────────────────────────────

WEB_DIR = Path(__file__).parent.parent / "web"


@router.get("/", response_class=HTMLResponse)
async def index():
    """Serve the web app."""
    html_file = WEB_DIR / "index.html"
    return HTMLResponse(content=html_file.read_text())


@router.get("/style.css")
async def css():
    css_file = WEB_DIR / "style.css"
    return HTMLResponse(
        content=css_file.read_text(),
        media_type="text/css",
    )


@router.get("/app.js")
async def js():
    js_file = WEB_DIR / "app.js"
    return HTMLResponse(
        content=js_file.read_text(),
        media_type="application/javascript",
    )


# ── API endpoints ────────────────────────────────────────────────

@router.post("/api/scan", response_model=ScanResponse)
async def start_scan(req: ScanRequest):
    """Start a new conference scan. Returns a run_id for SSE progress tracking."""
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    if not req.icp.strip():
        raise HTTPException(400, "ICP is required")

    run_id = str(uuid.uuid4())[:8]
    queue: asyncio.Queue = asyncio.Queue()
    _active_runs[run_id] = queue

    # Launch pipeline in background
    asyncio.create_task(
        _run_pipeline_task(run_id, req)
    )

    return ScanResponse(run_id=run_id, message="Scan started")


@router.get("/api/scan/{run_id}/progress")
async def scan_progress(run_id: str):
    """SSE endpoint for real-time progress updates."""
    queue = _active_runs.get(run_id)
    if not queue:
        raise HTTPException(404, "Run not found")

    async def event_stream():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("stage") in ("complete", "error"):
                    break
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Timeout'})}\n\n"
        finally:
            _active_runs.pop(run_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/results/{scoring_run_id}")
async def get_results(scoring_run_id: int, limit: int = 50):
    """Get scored results for a completed run."""
    config = load_config()
    db = DB(config.db_path)
    await db.init()

    results = await db.get_scored_results(scoring_run_id, limit=limit)
    return {
        "scoring_run_id": scoring_run_id,
        "count": len(results),
        "results": [
            {
                "rank": i + 1,
                "company_name": r.company_name,
                "score": r.score,
                "reasoning": r.reasoning,
                "summary": r.summary,
                "russian_speaking_leaders": r.russian_speaking_leaders,
                "website_url": r.website_url,
                "linkedin_url": r.linkedin_url,
                "contact_url": r.contact_url,
                "detail_page_url": r.detail_page_url,
                "description": r.description,
                "categories": r.categories,
                "booth_location": r.booth_location,
            }
            for i, r in enumerate(results)
        ],
    }


@router.get("/api/conferences")
async def list_conferences():
    """List previously scraped conferences."""
    config = load_config()
    db = DB(config.db_path)
    await db.init()
    conferences = await db.list_conferences()
    return {"conferences": conferences}


@router.get("/api/export/{scoring_run_id}")
async def export_csv(scoring_run_id: int):
    """Export all scored results as CSV."""
    config = load_config()
    db = DB(config.db_path)
    await db.init()

    # Export ALL scored results (no limit)
    results = await db.get_scored_results(scoring_run_id, limit=10000)

    lines = [
        "Rank,Company,Score,Summary,Why,Website,LinkedIn,Contact,Booth,Categories,CIS Contact"
    ]
    for i, r in enumerate(results):
        cats = "; ".join(r.categories) if r.categories else ""
        fields = [
            str(i + 1),
            _csv_escape(r.company_name),
            str(r.score),
            _csv_escape(r.summary),
            _csv_escape(r.reasoning),
            _csv_escape(r.website_url),
            _csv_escape(r.linkedin_url),
            _csv_escape(r.contact_url),
            _csv_escape(r.booth_location),
            _csv_escape(cats),
            _csv_escape(r.russian_speaking_leaders or ""),
        ]
        lines.append(",".join(fields))

    csv_content = "\n".join(lines)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=exhibitors_{scoring_run_id}.csv"
        },
    )


def _csv_escape(value: str) -> str:
    """Escape a value for CSV."""
    if not value:
        return ""
    if any(c in value for c in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


# ── Background task ──────────────────────────────────────────────

async def _run_pipeline_task(run_id: str, req: ScanRequest) -> None:
    """Run the pipeline and send progress events to the SSE queue."""
    queue = _active_runs.get(run_id)
    if not queue:
        return

    config = load_config()

    async def progress_callback(
        stage: str, message: str, current: int, total: int
    ) -> None:
        await queue.put({
            "stage": stage,
            "message": message,
            "current": current,
            "total": total,
        })

    try:
        result = await run_pipeline(
            config=config,
            url=req.url.strip(),
            icp=req.icp.strip(),
            conference_name=req.conference_name.strip(),
            force_rescrape=req.force_rescrape,
            on_progress=progress_callback,
        )

        if result.error:
            await queue.put({
                "stage": "error",
                "message": result.error,
                "current": 0,
                "total": 0,
            })
        else:
            await queue.put({
                "stage": "complete",
                "message": f"Done! Top {result.total_scored} exhibitors scored.",
                "current": result.total_scored,
                "total": result.total_scored,
                "scoring_run_id": result.scoring_run_id,
                "conference_name": result.conference_name,
            })

    except Exception as e:
        logger.exception("Pipeline task failed for run %s", run_id)
        await queue.put({
            "stage": "error",
            "message": f"Unexpected error: {str(e)}",
            "current": 0,
            "total": 0,
        })
