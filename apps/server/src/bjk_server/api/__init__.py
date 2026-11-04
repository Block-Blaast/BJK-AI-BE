from fastapi import APIRouter

# Base URL /api/v1 (API 명세서 1-1). 기능별 라우터는 여기에 붙인다.
api_router = APIRouter(prefix="/api/v1")
