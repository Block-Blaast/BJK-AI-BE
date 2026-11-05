from fastapi import APIRouter

from bjk_server.api import auth, chat, events, health, invites, parts, settings, users

# Base URL /api/v1 (API 명세서 1-1). 기능별 라우터는 여기에 붙인다.
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(invites.router)
api_router.include_router(users.router)
api_router.include_router(parts.router)
api_router.include_router(chat.router)
api_router.include_router(events.router)
api_router.include_router(settings.router)
api_router.include_router(health.router)
