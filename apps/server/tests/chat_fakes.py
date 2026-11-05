"""채팅 테스트용 가짜 해석기. 메시지 전송 픽스처(chat)는 conftest에 있다."""

from datetime import UTC, datetime

from bjk_server.chat.interpreter import Interpretation, InterpreterUnavailable

URL = "/api/v1/chat/messages"
NOW = datetime(2026, 11, 4, 1, 0, 0, tzinfo=UTC)

PARSED = {
    "3호기 베어링 두 개 씀": Interpretation("OUT", "베어링", 2, "3호기"),
    "베어링 작은 거 2개 씀": Interpretation("OUT", "베어링 작은 거", 2),
    "베어링 작은 거 5개 씀": Interpretation("OUT", "베어링 작은 거", 5),
    "베어링 작은 거 6개 씀": Interpretation("OUT", "베어링 작은 거", 6),
    "V벨트 3개 들어옴": Interpretation("IN", "V벨트", 3),
    "기어 하나 씀": Interpretation("OUT", "기어", 1),
    "6205 몇 개 있어?": Interpretation("QUERY", "6205"),
    "안녕": Interpretation("OTHER"),
}


class FakeInterpreter:
    def interpret(self, text: str) -> Interpretation:
        if text == "타임아웃":
            raise InterpreterUnavailable("timeout")
        return PARSED[text]


PARSED.update(
    {
        "베아링 2개 씀": Interpretation("OUT", "베아링", 2),
        "6205 1개 씀": Interpretation("OUT", "6205", 1),
        "M8*30 볼트 5개 씀": Interpretation("OUT", "M8*30 볼트", 5),
        "M8x20 볼트 5개 씀": Interpretation("OUT", "M8x20 볼트", 5),
    }
)
