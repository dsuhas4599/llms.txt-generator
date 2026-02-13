import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, field_validator

import db

logger = logging.getLogger(__name__)

SCHEDULE_INTERVALS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def _next_crawl_at(schedule: str | None) -> str:
    delta = SCHEDULE_INTERVALS.get((schedule or "daily").lower(), SCHEDULE_INTERVALS["daily"])
    return (datetime.now(timezone.utc) + delta).isoformat()

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")

app = FastAPI(
    title="llms.txt Generator",
    description="Generate llms.txt files for any website",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
MAX_URL_LEN = 2048


class GenerateResponse(BaseModel):
    content: str
    site_id: int | None = None


def _crawl_and_generate(url: str, site_name: str | None, summary: str | None):
    from crawler import CrawlOptions, crawl_site
    from generator import GeneratorOptions, generate_llms_txt

    logger.info("Starting crawl and generate for url=%s", url)
    opts = CrawlOptions(max_pages=10, crawl_delay=0.3, timeout=15)
    try:
        pages = crawl_site(url, options=opts)
    except Exception as e:
        logger.exception("Crawl failed for url=%s", url)
        raise HTTPException(status_code=502, detail=f"Crawl failed: {str(e)}")
    if not pages:
        logger.warning("No pages crawled from url=%s", url)
        raise HTTPException(
            status_code=422,
            detail="No pages could be crawled from this URL. Check the URL and try again.",
        )
    logger.info("Crawl done: %d pages for url=%s", len(pages), url)
    gen_opts = GeneratorOptions(base_url=url, site_name=site_name, summary=summary)
    content = generate_llms_txt(pages, gen_opts)
    logger.info("Generate done: %d chars for url=%s", len(content), url)
    return pages, content


def _crawl_site_and_save(site_id: int) -> tuple[bool, str]:
    site = db.site_get_by_id(site_id)
    if not site:
        return False, "Site not found"
    url = site["root_url"]
    try:
        pages, content = _crawl_and_generate(url, site.get("name"), None)
    except HTTPException as e:
        return False, str(e.detail)
    except Exception as e:
        logger.exception("Crawl failed for site_id=%d", site_id)
        return False, str(e)
    raw_pages = [{"url": getattr(p, "url", ""), "title": getattr(p, "title", ""), "description": getattr(p, "description", "")} for p in pages]
    crawl_result_id = db.crawl_result_save(site_id, len(raw_pages), raw_pages)
    db.llms_txt_save(site_id, crawl_result_id, content)
    next_at = _next_crawl_at(site.get("monitor_schedule"))
    db.site_update_next_crawl_at(site_id, next_at)
    logger.info("Cron crawl done for site_id=%d, next_crawl_at=%s", site_id, next_at)
    return True, "OK"


@app.on_event("startup")
def startup():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    db.init_db()


@app.get("/api/health")
def health():
    """Health check. Returns service status, environment, and current UTC timestamp.
    Use for liveness probes and monitoring."""
    return {
        "ok": True,
        "service": "llms-txt-generator",
        "env": os.getenv("ENV", "development"),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


class SiteCreateRequest(BaseModel):
    url: str
    name: str | None = None
    monitor_schedule: str | None = "daily"

    @field_validator("url")
    @classmethod
    def url_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > MAX_URL_LEN or not URL_PATTERN.match(v):
            raise ValueError("Invalid or missing URL")
        return v


@app.post("/api/sites")
def sites_create(background_tasks: BackgroundTasks, body: SiteCreateRequest):
    """Create a new monitored site. Validates URL, creates the site record, and queues an
    initial crawl in the background. Returns immediately with the created site.
    Raises 409 if the URL already exists. Crawl runs async; use GET /api/sites to see
    when last_generated_at appears."""
    try:
        existing = db.site_get_by_url(body.url)
        if existing:
            raise HTTPException(status_code=409, detail="Site with this URL already exists")
        site = db.site_create(
            root_url=body.url,
            name=body.name,
            monitor_schedule=body.monitor_schedule or "daily",
        )
        if not site or "id" not in site:
            raise HTTPException(status_code=502, detail="Database error: failed to create site")
        background_tasks.add_task(_crawl_site_and_save, site["id"])
        return {"id": site["id"], "root_url": site["root_url"], "name": site["name"], "created_at": site["created_at"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database error: {str(e)}")


@app.get("/api/sites")
def sites_list():
    """List all monitored sites. Each site includes last_crawl_at and last_generated_at
    from the most recent crawl. Ordered by updated_at descending."""
    return db.site_get_all()


@app.get("/api/sites/{site_id}/llms.txt", response_class=PlainTextResponse)
def site_llms_txt(site_id: int = PathParam(..., ge=1)):
    """Return the latest llms.txt content for a site as plain text.
    Raises 404 if the site does not exist or no llms.txt has been generated yet."""
    site = db.site_get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    latest = db.llms_txt_get_latest(site_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No llms.txt generated yet. Run a crawl first.")
    return latest["content"]


@app.post("/api/sites/{site_id}/crawl", response_model=GenerateResponse)
def site_crawl(site_id: int = PathParam(..., ge=1)):
    """Manually trigger a crawl for a site (Refresh button). Crawls the site, generates
    llms.txt, saves to DB, and updates next_crawl_at. Returns the generated content.
    Blocks until the crawl completes. Raises 404 if site not found, 502 on crawl failure."""
    logger.info("Crawl requested for site_id=%d", site_id)
    site = db.site_get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    url = site["root_url"]
    pages, content = _crawl_and_generate(url, site.get("name"), None)
    raw_pages = [{"url": getattr(p, "url", ""), "title": getattr(p, "title", ""), "description": getattr(p, "description", "")} for p in pages]
    crawl_result_id = db.crawl_result_save(site_id, len(raw_pages), raw_pages)
    db.llms_txt_save(site_id, crawl_result_id, content)
    next_at = _next_crawl_at(site.get("monitor_schedule"))
    db.site_update_next_crawl_at(site_id, next_at)
    logger.info("Saved crawl for site_id=%d: %d pages, next_crawl_at=%s", site_id, len(pages), next_at)
    return GenerateResponse(content=content)


@app.post("/api/cron/crawl-due")
def cron_crawl_due(
    background_tasks: BackgroundTasks,
    x_cron_secret: str | None = Header(None, alias="X-Cron-Secret"),
):
    """Cron endpoint for scheduled re-crawls. Requires X-Cron-Secret header matching CRON_SECRET.
    Fetches all sites due for crawl (next_crawl_at is null or in the past), queues each as a
    background task, and returns immediately with queued count. Call from cron-job.org or similar."""
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected or not x_cron_secret or x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")
    due = db.sites_get_due_for_crawl()
    if not due:
        return {"queued": 0}
    for site in due:
        background_tasks.add_task(_crawl_site_and_save, site["id"])
    return {"queued": len(due)}


_frontend_dist = _backend_dir.parent / "frontend" / "dist"

if _frontend_dist.exists():
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve the built React SPA. Returns static files when they exist; otherwise returns
        index.html for client-side routing. API routes under /api/ are handled by FastAPI."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENV", "development") == "development",
    )
