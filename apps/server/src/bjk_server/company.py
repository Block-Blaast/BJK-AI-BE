"""회사 생성 (F-AUTH-01). 회사 코드와 기본 설정·기본 카테고리를 함께 만든다."""

import secrets
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.db.models import Category, Company, CompanySettings
from bjk_server.defaults import DEFAULT_CATEGORIES, default_settings

# 기기에 입력하는 코드라 헷갈리는 글자(0·O, 1·I·L)는 뺀다.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
CODE_ATTEMPTS = 10


def new_company_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _unused_code(session: Session) -> str:
    for _ in range(CODE_ATTEMPTS):
        code = new_company_code()
        taken = session.execute(
            text("SELECT auth_company_by_code(:code)"), {"code": code}
        ).scalar_one()
        if taken is None:
            return code
    raise RuntimeError("회사 코드를 만들지 못했습니다.")


def create_company(session: Session, name: str) -> Company:
    """앱 계정 세션에서 새 회사를 만들고 현재 트랜잭션의 회사로 지정한다.

    RLS가 새 회사 ID로만 쓰기를 허용하므로 ID를 먼저 정해 회사로 지정한 뒤 넣는다.
    """
    company_id = uuid.uuid4()
    set_tenant(session, company_id)
    company = Company(id=company_id, name=name, code=_unused_code(session))
    session.add(company)
    session.flush()
    session.add(CompanySettings(company_id=company_id, **default_settings()))
    for _, cat_name, dependency, lead, price, hs in DEFAULT_CATEGORIES:
        session.add(
            Category(
                company_id=company_id,
                name=cat_name,
                import_dependency=dependency,
                lead_factors=lead,
                price_factors=price,
                hs_code=hs,
            )
        )
    session.flush()
    return company
