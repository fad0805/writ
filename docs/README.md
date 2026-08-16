# WRIT 서버 운영 문서

이 문서는 WRIT 서버를 직접 설치하고 운영하는 **서버 관리자(설치자)**를 위한 가이드입니다.

## 목차

| 문서 | 내용 |
|------|------|
| [설치 가이드](./installation.md) | 서버 설치부터 첫 계정 생성, 역방향 프록시 설정까지 |
| [환경 변수 참조](./configuration.md) | `.env.production`에 설정할 수 있는 모든 항목 |
| [관리자 가이드](./administration.md) | 관리자 역할과 관리 페이지 사용법 |
| [운영 및 유지보수](./maintenance.md) | 백업, 업데이트, 로그, 자동화 작업, 문제 해결 |

## WRIT 서버 구성

WRIT는 Docker Compose로 실행되며, 세 개의 컨테이너로 구성됩니다.

```
외부(사용자/연합) ──> [web :3000]  (Next.js, 공개 진입점)
                        │  /api/* 등 리버스 프록시
                        ▼
                     [api :8000]  (FastAPI, 내부망 전용)
                        │
                        ▼
                     [db :5432]   (PostgreSQL)
```

- **web** — 사용자에게 보이는 웹 UI입니다. 호스트에는 `3000`번 포트만 열려 있습니다.
- **api** — ActivityPub 연합, REST API, 백그라운드 워커를 실행합니다. 호스트에 직접 노출되지 않으며 `web`을 통해 접근합니다.
- **db** — PostgreSQL 데이터베이스입니다. 마이그레이션(alembic)은 api 컨테이너가 시작될 때 자동으로 실행됩니다.

역방향 프록시(Nginx 등)는 반드시 **web(3000)**을 바라보게 설정해야 합니다. `/.well-known/*`, `/users/*`, `/posts/*`, `/nodeinfo/*`, `/inbox` 등 연합(Federation)용 경로도 `web`이 api로 중계합니다.
