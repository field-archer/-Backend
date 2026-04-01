import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config.config import config
from app.api.auth_routes import router as auth_router
from app.api.fire_markers_routes import router as fire_markers_router
from app.api.routes import router as analyze_router
from app.core.errors import ApiError
from app.database import Base, engine
from app.models import FireMarker, User  # noqa: F401

os.makedirs(config.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
