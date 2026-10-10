from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from app.errors import APIError, register_exception_handlers
from app.research import router as research_router
from app.search import router as search_router


app = FastAPI(
    title="ORBIT Search",
)

register_exception_handlers(app)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(search_router)
app.include_router(research_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Research workspace frontend
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent / "static"

ASSET_TYPES = {
    "styles.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}


@app.get("/", response_class=HTMLResponse)
def frontend_index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/static/{asset}")
def frontend_asset(asset: str):
    media_type = ASSET_TYPES.get(asset)

    if media_type is None:
        raise APIError(
            404,
            "not_found",
            f"Unknown asset: {asset}",
        )

    return Response(
        (STATIC_DIR / asset).read_text(encoding="utf-8"),
        media_type=media_type,
    )
