from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.config import config
from app.api.routes import router as api_router

# 创建FastAPI应用
app = FastAPI(
    title=config.PROJECT_NAME,
    version=config.VERSION,
    openapi_url=f"{config.API_V1_STR}/openapi.json"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix=config.API_V1_STR)

# 根路径
@app.get("/")
async def root():
    return {
        "code": 20000,
        "message": "成功",
        "data": {
            "project": config.PROJECT_NAME,
            "version": config.VERSION,
            "api_prefix": config.API_V1_STR
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)