import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEDULE_INTERVALS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def _next_crawl_at(schedule: str | None) -> str:
    delta = SCHEDULE_INTERVALS.get((schedule or "daily").lower(), SCHEDULE_INTERVALS["daily"])
    return (datetime.now(timezone.utc) + delta).isoformat()

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Path as PathParam, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, field_validator

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")

import db

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
MAX_SITE_NAME_LEN = 200
MAX_SUMMARY_LEN = 2000


class GenerateRequest(BaseModel):
    url: str
    site_name: str | None = None
    summary: str | None = None
    save: bool = False

    @field_validator("url")
    @classmethod
    def url_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        if len(v) > MAX_URL_LEN:
            raise ValueError(f"URL must be at most {MAX_URL_LEN} characters")
        if not URL_PATTERN.match(v):
            raise ValueError("URL must start with http:// or https:// and be valid")
        return v

    @field_validator("site_name")
    @classmethod
    def site_name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip() or None
        if v and len(v) > MAX_SITE_NAME_LEN:
            raise ValueError(f"site_name must be at most {MAX_SITE_NAME_LEN} characters")
        return v

    @field_validator("summary")
    @classmethod
    def summary_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip() or None
        if v and len(v) > MAX_SUMMARY_LEN:
            raise ValueError(f"summary must be at most {MAX_SUMMARY_LEN} characters")
        return v


class GenerateResponse(BaseModel):
    content: str
    site_id: int | None = None


def _crawl_and_generate(url: str, site_name: str | None, summary: str | None):
    from crawler import CrawlOptions, crawl_site
    from generator import GeneratorOptions, generate_llms_txt

    logger.info("Starting crawl and generate for url=%s", url)
    opts = CrawlOptions(max_pages=100, crawl_delay=0.3, timeout=15)
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


def _generate_llms_txt(url: str, site_name: str | None, summary: str | None) -> str:
    _, content = _crawl_and_generate(url, site_name, summary)
    return content


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
    return {
        "ok": True,
        "service": "llms-txt-generator",
        "env": os.getenv("ENV", "development"),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.post("/api/generate", response_model=GenerateResponse)
def generate_post(body: GenerateRequest):
    pages, content = _crawl_and_generate(body.url, body.site_name, body.summary)
    site_id = None
    if body.save:
        logger.info("Saving to site: url=%s", body.url)
        site = db.site_get_by_url(body.url)
        if not site:
            site = db.site_create(root_url=body.url, name=body.site_name, monitor_schedule="daily")
        site_id = site["id"]
        raw_pages = [{"url": getattr(p, "url", ""), "title": getattr(p, "title", ""), "description": getattr(p, "description", "")} for p in pages]
        crawl_result_id = db.crawl_result_save(site_id, len(raw_pages), raw_pages)
        db.llms_txt_save(site_id, crawl_result_id, content)
        next_at = _next_crawl_at(site.get("monitor_schedule"))
        db.site_update_next_crawl_at(site_id, next_at)
        logger.info("Saved to site_id=%d, crawl_result_id=%d, next_crawl_at=%s", site_id, crawl_result_id, next_at)
    return GenerateResponse(content=content, site_id=site_id)


@app.get("/api/generate", response_model=GenerateResponse)
def generate_get(
    url: str = Query(..., description="Website URL to crawl and generate llms.txt for"),
    site_name: str | None = Query(None, max_length=MAX_SITE_NAME_LEN),
    summary: str | None = Query(None, max_length=MAX_SUMMARY_LEN),
):
    url = url.strip()
    if not url or len(url) > MAX_URL_LEN or not URL_PATTERN.match(url):
        raise HTTPException(status_code=422, detail="Invalid or missing url query parameter")
    content = _generate_llms_txt(url, site_name, summary)
    return GenerateResponse(content=content)


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
def sites_create(body: SiteCreateRequest):
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
        return {"id": site["id"], "root_url": site["root_url"], "name": site["name"], "created_at": site["created_at"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database error: {str(e)}")


@app.get("/api/sites")
def sites_list():
    return db.site_get_all()


@app.get("/api/sites/{site_id}")
def site_get(site_id: int = PathParam(..., ge=1)):
    site = db.site_get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    latest = db.llms_txt_get_latest(site_id)
    out = dict(site)
    if latest:
        out["latest_content_preview"] = (latest["content"] or "")[:200]
    return out


@app.get("/api/sites/{site_id}/llms.txt", response_class=PlainTextResponse)
def site_llms_txt(site_id: int = PathParam(..., ge=1)):
    site = db.site_get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    latest = db.llms_txt_get_latest(site_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No llms.txt generated yet. Run a crawl first.")
    return latest["content"]


@app.post("/api/sites/{site_id}/crawl", response_model=GenerateResponse)
def site_crawl(site_id: int = PathParam(..., ge=1)):
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
def cron_crawl_due(x_cron_secret: str | None = Header(None, alias="X-Cron-Secret")):
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected or not x_cron_secret or x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")
    due = db.sites_get_due_for_crawl()
    if not due:
        return {"crawled": 0, "message": "No sites due for crawl"}
    results = []
    for site in due:
        ok, msg = _crawl_site_and_save(site["id"])
        results.append({"site_id": site["id"], "root_url": site["root_url"], "ok": ok, "message": msg})
    crawled = sum(1 for r in results if r["ok"])
    logger.info("Cron crawl-due: %d/%d sites crawled", crawled, len(due))
    return {"crawled": crawled, "total": len(due), "results": results}


_frontend_dist = _backend_dir.parent / "frontend" / "dist"

if _frontend_dist.exists():
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
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
