# 운영 및 유지보수

## 디렉토리 구조

서버 루트의 바인드 마운트 디렉토리들입니다.

| 디렉토리 | 용도 | 소유자 |
|----------|------|--------|
| `db_data/` | PostgreSQL 데이터 | db 컨테이너가 관리 |
| `data/` | 응용 데이터 (SQLite 사용 시 DB 포함) | UID 999 |
| `uploads/` | 업로드된 미디어, 아바타, 이모지 | UID 999 |
| `static/` | 정적 파일 | UID 999 |
| `logs/` | 일별 로그 파일 | UID 999 |

## 백업

### 데이터베이스

PostgreSQL 데이터베이스를 덤프합니다.

```bash
docker compose exec db pg_dump -U <POSTGRES_USER> <POSTGRES_DB> > backup-$(date +%F).sql
```

복원:

```bash
docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < backup-2026-01-01.sql
```

> `<POSTGRES_USER>`, `<POSTGRES_DB>`는 `.env.production`의 값입니다.

### 파일

`uploads/`, `data/`, `static/`, `logs/`를 함께 백업하세요.

```bash
tar czf writ-files-$(date +%F).tar.gz uploads data static
```

미디어가 많다면 `rsync`로 증분 백업을 권장합니다.

> 자동 삭제/미디어 정리 워커가 매일 3시에 실행되므로, 백업 주기를 3시 기준으로 잡으면 삭제 직전 상태를 보존할 수 있습니다.

## 업데이트

```bash
cd writ
git pull
docker compose build api web
docker compose up -d
```

- 새 코드에 DB 마이그레이션이 포함되어 있다면 api 컨테이너 시작 시 `alembic upgrade head`가 자동으로 실행됩니다.
- 업데이트 전 백업을 권장합니다.
- `.env.production.sample`이 변경됐다면 새 환경 변수가 있는지 비교해 `.env.production`에 반영하세요.
- 여러 계정을 등록해 전환하던 사용자가 있다면, 업데이트 후 각 계정으로 한 번씩 다시 로그인해야 전환 목록이 재구성됩니다. (계정 전환이 브라우저 저장 토큰 대신 서버 측 검증으로 바뀌었으며, 구 토큰은 클라이언트에서 자동 삭제됩니다.)

## 로그

- api와 web은 각각 `logs/YYYY-MM-DD.log` 파일로 날짜별 기록이 남습니다 (자정에 자동 로테이션).
- 실시간 확인:

```bash
docker compose logs -f api
docker compose logs -f web
```

- 파일 확인:

```bash
tail -f logs/$(date +%F).log
```

- 관리자 행동 기록(중재 로그)은 관리 화면 `/admin/moderation-log`에서 확인할 수 있습니다.

## 백그라운드 워커

api 컨테이너 안에서 함께 실행되는 작업들입니다.

| 워커 | 주기 | 작업 |
|------|------|------|
| delivery worker | 30초 | 연합 서버로의 활동 전달(PendingDelivery). 최대 7회 재시도. |
| auto-delete | 매일 3시 | 만료된 글 하드 삭제 (기간 설정한 사용자 대상). 서버 부하 시 건너뜀. |
| orphan media cleanup | 매일 3시 | 참조가 없는 `uploads/media/` 파일 정리 (`ORPHAN_MEDIA_MIN_AGE_DAYS` 기준). |
| remote profile refresh | 매시간 | 원격 사용자 프로필(아바타, 소개 등) 갱신. 서버가 한가할 때만, 사용자당 3일 간격. |

## 문제 해결

### 컨테이너가 쓰기 권한으로 실패한다

바인드 마운트 디렉토리 소유자가 컨테이너 UID(999)와 다르기 때문입니다.

```bash
docker compose exec api id          # 컨테이너 UID 확인
sudo chown -R 999:999 data uploads static logs
```

### 로그인 시 "이메일 인증이 필요합니다"

운영 모드에서는 가입 후 이메일 인증을 완료해야 로그인이 됩니다.

- SMTP가 올바르게 설정됐는지 확인하세요 ([환경 변수 참조](./configuration.md)).
- 인증 메일을 못 받았다면 `/verify-email`에서 인증 메일을 다시 요청할 수 있습니다.
- SMTP를 방금 설정했다면 api를 재시작하세요: `docker compose restart api`

### 연합(다른 서버)과 통신이 안 된다

- `BASE_URL`이 실제 공개 도메인/HTTPS로 설정되어 있는지 확인하세요.
- `docker compose exec api` 안에서 밖으로 나가는 HTTPS가 가능한지 확인하세요.
- WebFinger/NodeInfo 응답 확인:

```bash
curl -s https://<도메인>/.well-known/webfinger?resource=acct:<사용자>@<도메인>
curl -s https://<도메인>/nodeinfo/2.0
```

### 마이그레이션 실패로 서버가 뜨지 않는다

api 시작 시 `alembic upgrade head`가 실패하면 스키마 불일치 상태로 기동하는 것을 막기 위해 api가 즉시 종료됩니다. `restart: unless-stopped` 정책에 따라 계속 재시도되므로, 원인을 해결하기 전에는 api가 뜨지 않는 것이 정상입니다.

```bash
docker compose logs api | grep -i -E "error|alembic|migration"
```

원인 예시: DB 미기동(db 컨테이너 헬스체크 확인), `DATABASE_URL` 불일치, 디스크 부족, 손상된 마이그레이션 체인. 복구가 어려우면 [백업](#백업)으로 DB를 복원한 뒤 다시 시도하세요.

### 상태 확인

- api 헬스체크: `GET /api/server-info`
- web 헬스체크: `GET /` (HTTP 200)

```bash
docker compose ps
```
