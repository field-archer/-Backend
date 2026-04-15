import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from config.config import config
from app.api.auth_routes import router as auth_router
from app.api.fire_dashboard_routes import router as fire_dashboard_router
from app.api.fire_ledger_routes import router as fire_ledger_router
from app.api.fire_markers_routes import router as fire_markers_router
from app.api.routes import router as analyze_router
from app.core.errors import ApiError
from app.database import Base, engine
from app.models import FireMarker, FireMarkerEvent, User  # noqa: F401

os.makedirs(config.UPLOAD_DIR, exist_ok=True)


def _ensure_mysql_schema() -> None:
    """
    Lightweight schema sync for MySQL without Alembic.

    SQLAlchemy's create_all() won't ALTER existing tables, but this project evolves fast and
    is often run against an already-created local DB. We patch missing columns/tables on startup.
    """
    insp = inspect(engine)

    if not insp.has_table("fire_markers"):
        return

    existing_cols = {c["name"] for c in insp.get_columns("fire_markers")}
    ddl: list[str] = []

    if "status" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers "
            "ADD COLUMN status ENUM('pending','handling','extinguished') "
            "NOT NULL DEFAULT 'pending'"
        )
    if "level" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers "
            "ADD COLUMN level ENUM('low','medium','high') "
            "NOT NULL DEFAULT 'low'"
        )
    if "cause" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers "
            "ADD COLUMN cause ENUM('human','lightning','farming','unknown') "
            "NOT NULL DEFAULT 'unknown'"
        )
    if "region" not in existing_cols:
        ddl.append("ALTER TABLE fire_markers ADD COLUMN region VARCHAR(64) NULL")
    if "reporter_user_id" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers ADD COLUMN reporter_user_id VARCHAR(36) NULL"
        )
    if "reporter_username" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers ADD COLUMN reporter_username VARCHAR(64) NULL"
        )
    if "updated_at" not in existing_cols:
        ddl.append(
            "ALTER TABLE fire_markers "
            "ADD COLUMN updated_at DATETIME "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP"
        )

    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_mysql_schema()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=config.PROJECT_NAME,
    version=config.VERSION,
    openapi_url=f"{config.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    if not errors:
        msg = "参数错误"
    else:
        e0 = errors[0]
        loc_parts = [str(x) for x in e0.get("loc", []) if x not in ("body", "query", "path")]
        loc = ".".join(loc_parts)
        raw = e0.get("msg", "参数错误")
        msg = f"{loc}: {raw}" if loc else raw
    return JSONResponse(
        status_code=400,
        content={"code": 40000, "message": msg, "data": None},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")

app.include_router(analyze_router, prefix=config.API_V1_STR)
app.include_router(auth_router, prefix=config.API_V1_STR)
app.include_router(fire_markers_router, prefix=config.API_V1_STR)
app.include_router(fire_dashboard_router, prefix=config.API_V1_STR)
app.include_router(fire_ledger_router, prefix=config.API_V1_STR)


@app.get("/")
async def root():
    return {
        "code": 20000,
        "message": "成功",
        "data": {
            "project": config.PROJECT_NAME,
            "version": config.VERSION,
            "api_prefix": config.API_V1_STR,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
