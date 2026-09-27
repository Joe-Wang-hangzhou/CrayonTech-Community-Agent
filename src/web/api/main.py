"""FastAPI Web API 服务，挂载静态页面并提供群聊按日总结接口。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from starlette.staticfiles import StaticFiles

from src.services.summary import generate_and_save_summary
from src.storage.database import close_engine, init_engine

# 加载项目根目录下的 .env 环境变量
env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理全局数据库引擎生命周期。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 环境变量未设置")
    init_engine(database_url)
    try:
        yield
    finally:
        await close_engine()


app = FastAPI(title="CrayonTechCommunity API", lifespan=lifespan)


@app.get("/api/summary")
async def get_summary(
    group_id: int = Query(..., description="QQ 群号"),
    date: str = Query(..., description="查询日期，格式为 YYYY-MM-DD"),
) -> dict[str, str]:
    """获取指定群在指定日期的聊天总结。"""
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的日期格式 '{date}'，请使用 YYYY-MM-DD",
        )

    summary = await generate_and_save_summary(group_id=group_id, date_obj=date_obj)
    if not summary:
        raise HTTPException(status_code=404, detail="当天没有已采集的文本消息")

    return {"summary": summary}


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
