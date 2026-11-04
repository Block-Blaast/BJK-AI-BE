# BJK-AI-BE

발주콕 백엔드 모노레포 (server + ai)

```
apps/
  server/      발주콕 API 서버 (FastAPI)
  ai/          LLM 게이트웨이 (FastAPI)
packages/
  contracts/   server ↔ ai 공유 스키마 (Pydantic)
```

## 시작하기

[uv](https://docs.astral.sh/uv/)와 Python 3.12 이상이 필요합니다.

```bash
make install   # 전체 workspace 의존성 설치
make test
make server    # http://localhost:8000/docs
make ai        # http://localhost:8001/docs
```

Docker로 두 서비스를 함께 띄우려면 `make up`.

## 협업

Issue·브랜치·커밋·PR 규칙은 [docs/collaboration.md](docs/collaboration.md)를 따릅니다.
