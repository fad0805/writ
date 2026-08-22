# WRIT 서버 설치 가이드

## 요구 사항

- Linux 서버 (권장) 또는 macOS
- Docker 및 Docker Compose v2

## 1단계. 저장소 복제 및 환경 설정 파일 생성

```bash
git clone https://github.com/fad0805/writ.git
cd writ
cp .env.production.sample .env.production
```

## 2단계. `.env.production` 설정

`vi .env.production` (또는 원하는 편집기)으로 열고 **필수 항목**부터 채웁니다.

### 필수 항목

| 항목 | 예시 | 설명 |
|------|------|------|
| `BASE_URL` | `https://writ.example.com` | 서비스의 공개 URL. 연합과 이메일 인증 링크에 사용됩니다. |
| `SECRET_KEY` | 랜덤 문자열 | 서명/암호화 키. 임의의 긴 문자열을 사용하세요. |
| `DATABASE_URL` | `postgresql+psycopg2://dbuser:dbpassword@db:5432/dbname` | PostgreSQL 접속 문자열 (기본값 제공됨) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 각각 | db 컨테이너가 만들 DB 계정/이름 (위 `DATABASE_URL`과 일치해야 함) |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | 각각 | 이메일 발송 설정. **중요: 운영 환경에서 이메일 인증을 받아야 로그인할 수 있으므로 필수**입니다. |

> **SECRET_KEY 생성 예시**
> ```bash
> openssl rand -hex 32
> ```

### 왜 SMTP가 필수인가?

운영 환경(`APP_ENV=production`)에서는 **가입 후 이메일 인증을 완료해야 로그인이 가능**합니다. SMTP가 설정되어 있지 않으면 인증 메일이 발송되지 않아 누구도 로그인할 수 없습니다. 개발 모드(`APP_ENV=development`)에서는 인증 없이 자동으로 처리되지만, 실제 운영 서버에서는 반드시 SMTP를 설정하세요.

### 선택 항목 (필요 시)

- `INITIAL_OWNER_PASSWORD` — 설정하면 첫 번째 가입자가 이 암호를 비밀번호로 입력해야 관리자(owner)가 됩니다. 가입을 임의의 사람에게 막고 싶을 때 사용합니다.
- `MAX_POST_LENGTH` — 글자 수 제한 (기본 500)
- `S3_*` — 미디어를 로컬 대신 S3 호환 오브젝트 스토리지에 저장할 때
- 자세한 항목은 [환경 변수 참조](./configuration.md)를 참고하세요.

## 3단계. 데이터 디렉토리 권한 설정 (중요)

api 컨테이너는 이미지 내부의 `writ` 사용자(**UID 999**)로 실행됩니다. Docker Compose의 바인드 마운트(`data`, `uploads`, `static`, `logs`)는 **호스트 디렉토리의 권한을 그대로 따르므로**, 컨테이너가 쓸 수 있도록 호스트 디렉토리 소유자를 컨테이너 UID와 맞춰야 합니다.

```bash
mkdir -p data uploads static logs
sudo chown -R 999:999 data uploads static logs
```

> `ls -l`에서 소유자가 `lxd`(UID 999)처럼 보여도 상관없습니다. 바인드 마운트 권한은 이름이 아니라 **숫자 UID**로 판단합니다.

컨테이너의 실제 UID가 999가 아니라면(빌드 환경에 따라 다를 수 있음) 다음 명령으로 확인 후 맞춰주세요:

```bash
docker compose exec api id   # 예: uid=999(writ)
```

## 4단계. 실행

```bash
docker compose up -d
```

정상 기동을 확인합니다.

```bash
docker compose ps          # 세 컨테이너가 모두 running 상태여야 함
docker compose logs -f api # 마이그레이션과 서버 시작 로그 확인
```

api 컨테이너가 시작될 때 `alembic upgrade head`(DB 마이그레이션)가 자동 실행됩니다. api는 db 컨테이너의 헬스체크(pg_isready)가 통과한 뒤에 시작되며, 마이그레이션이 실패하면 스키마 불일치 상태로 서비스하는 것을 막기 위해 즉시 종료합니다. 이후 compose의 재시작 정책(`restart: unless-stopped`)에 따라 재시도됩니다.

## 5단계. 첫 계정(관리자) 생성

브라우저에서 `http://<서버주소>:3000/register` 로 접속해 첫 계정을 가입합니다.

- **첫 번째 가입자는 자동으로 `owner`(최고 관리자)**가 됩니다.
- `INITIAL_OWNER_PASSWORD`를 설정했다면 그 값을 비밀번호로 입력해야 합니다.
- 이메일 인증 메일이 도착하면 링크를 눌러 인증을 완료해야 로그인할 수 있습니다.

## 6단계. 역방향 프록시 및 HTTPS 설정 (권장)

WRIT는 ActivityPub 서버이므로 **HTTPS가 사실상 필수**입니다. 연합 서버들이 `BASE_URL`의 도메인으로 요청을 보내며, HTTP면 대부분의 서버가 통신을 거부합니다.

Nginx 예시 (`/etc/nginx/sites-available/writ`):

```nginx
server {
    listen 80;
    server_name writ.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name writ.example.com;

    ssl_certificate     /etc/letsencrypt/live/writ.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/writ.example.com/privkey.pem;

    client_max_body_size 50m;  # 미디어 업로드 용량 (필요에 따라 조절)

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";  # 웹소켓/스트리밍 지원
    }
}
```

- `docker compose`의 `web` 컨테이너는 호스트의 `3000` 포트에 바인딩되어 있습니다.
- SSL 인증서는 Let's Encrypt `certbot`으로 발급받을 수 있습니다.
- 적용 후 `.env.production`의 `BASE_URL`을 `https://...`로 설정하고 재시작하세요.

```bash
docker compose restart api web
```

## 설치 확인

브라우저에서 `https://writ.example.com` 접속, 로그인, 글 작성이 되는지 확인합니다. 연합 동작 확인:

```bash
curl -s https://writ.example.com/.well-known/webfinger?resource=acct:owner@writ.example.com
curl -s https://writ.example.com/nodeinfo/2.0
```
