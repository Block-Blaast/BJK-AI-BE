"""엑셀 이관 규격 추출·카테고리 제안 (F-SETUP-02, SET-01) server → ai 계약.

ai는 줄마다 부품 이름에서 규격을 뽑고 카테고리를 제안한다. 카테고리는 요청에 담긴 등록 카테고리
안에서만 고른다. 실패하면 server는 정규식 규격만 쓰고 카테고리는 비워 관리자가 직접 고르게 한다.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bjk_contracts.common import AiMeta, LlmUsage

# `parts.spec`의 규격 키. server 매칭(F-MATCH-01)의 규격 필터와 같은 키를 쓴다.
SPEC_KEYS: dict[str, str] = {
    "bearing_no": "베어링 형번 (예: 6205)",
    "shield": "베어링 실드 형식 (예: ZZ, 2RS)",
    "thread": "나사 지름 (예: M8)",
    "length_mm": "볼트·나사 길이 mm (예: 20)",
    "type": "벨트 형 (예: A)",
    "length": "벨트 길이 호칭 (예: 42)",
    "size": "오링 등 호칭 크기 (예: P20)",
    "volume_l": "용량 L (예: 20)",
}
IMPORT_MAX_ROWS = 200
IMPORT_NAME_MAX_LEN = 200


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class CategoryOption(_Frozen):
    id: str
    name: str = Field(min_length=1)


class ImportRow(_Frozen):
    """엑셀 한 줄. `spec_text`는 규격 열이 있으면 그 값(권장 열, F-SETUP-01)."""

    row: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=IMPORT_NAME_MAX_LEN)
    spec_text: str | None = Field(default=None, max_length=IMPORT_NAME_MAX_LEN)


class ImportSuggestRequest(_Frozen):
    company_id: UUID
    categories: list[CategoryOption] = Field(min_length=1)
    rows: list[ImportRow] = Field(min_length=1, max_length=IMPORT_MAX_ROWS)

    @model_validator(mode="after")
    def _rows_unique(self) -> "ImportSuggestRequest":
        if len({r.row for r in self.rows}) != len(self.rows):
            raise ValueError("row 번호는 겹치지 않아야 한다")
        return self


class RowSuggestion(_Frozen):
    """한 줄의 제안. `spec` 키는 `SPEC_KEYS` 안, 값은 공백·하이픈을 뺀 대문자.

    `category_id`가 없으면 제안하지 못한 것이고, `confidence`가 낮은 줄을 화면 위로 올린다.
    """

    row: int
    spec: dict[str, str] = Field(default_factory=dict)
    category_id: str | None = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _known_spec_keys(self) -> "RowSuggestion":
        unknown = set(self.spec) - set(SPEC_KEYS)
        if unknown:
            raise ValueError(f"모르는 규격 키: {sorted(unknown)}")
        return self


class ImportSuggestResponse(_Frozen):
    """요청의 모든 줄에 대한 제안(줄 순서대로).

    실패하면 `suggestions`는 None이고 `ai.fallback`이 True.
    """

    suggestions: list[RowSuggestion] | None
    ai: AiMeta
    usage: LlmUsage | None = None

    @model_validator(mode="after")
    def _suggestions_match_fallback(self) -> "ImportSuggestResponse":
        if self.ai.fallback != (self.suggestions is None):
            raise ValueError("대체 경로면 suggestions가 비고, 정상 응답이면 있어야 한다")
        return self
