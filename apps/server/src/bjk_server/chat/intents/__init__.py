"""채팅 의도별 처리기 등록. 새 의도는 처리기 파일을 만들고 아래 표에 한 줄을 추가한다."""

from bjk_server.chat.intents import query, record
from bjk_server.chat.intents.base import IntentContext, IntentHandler, IntentResult

HANDLERS: dict[str, IntentHandler] = {
    "OUT": record.handle,
    "IN": record.handle,
    "QUERY": query.handle,
}

__all__ = ["HANDLERS", "IntentContext", "IntentHandler", "IntentResult"]
