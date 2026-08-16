# WRIT

<img src="https://github.com/fad0805/writ/blob/main/web/public/icons/icon-512.png" alt="WRIT Logo" width="100px" />

> 글쓰기를 중심으로 설계된 ActivityPub 플랫폼

WRIT는 **연재(Series)**와 **장문 작성**을 자연스럽게 지원하는 ActivityPub 기반 소셜 플랫폼입니다. Mastodon, Misskey 등 다른 ActivityPub 서버와 연합하면서도, 작가와 독자를 위한 경험을 우선으로 설계되었습니다.

---

## Philosophy

- ✍️ 글쓰기가 중심이 되는 인터페이스
- 📚 시리즈와 에피소드 기반의 연재
- 🌐 ActivityPub 기반의 연합
- 🕒 알고리즘 없이 시간순 타임라인
- 🎯 단순하고 이해하기 쉬운 구조

"SNS에 글쓰기 기능을 추가한" 것이 아니라, **"글쓰기 플랫폼에 연합 기능을 추가한"** 것입니다.

---

## AI와 함께 개발합니다

WRIT는 AI 기반 개발 도구(opencode)의 도움을 받아 개발되고 있습니다. AI는 코드 작성과 리팩터링, 버그 수정, 문서화 등의 작업에 활용됩니다.

---

## Technology Stack

| 영역 | 기술 |
|------|------|
| Backend | Python, FastAPI, SQLAlchemy, PostgreSQL |
| Frontend | React, TypeScript, Next.js |
| Infrastructure | Docker, Docker Compose |

---

## Quick Start

```bash
git clone https://github.com/fad0805/writ.git
cd writ
cp .env.production.sample .env.production
docker compose up -d
```

기본적으로 Docker Compose를 사용하여 실행합니다.

자세한 설치·운영 방법은 [서버 운영 문서](docs/)를 참고하세요.

---

## 설치 (Installation)

### 요구사항
- Docker 및 Docker Compose v2

### 1. 저장소 복제 및 환경설정
```bash
git clone https://github.com/fad0805/writ.git
cd writ
cp .env.production.sample .env.production
```

`.env.production`을 열어 아래 항목을 설정하세요.

| 항목 | 설명 | 필수 |
|------|------|------|
| `BASE_URL` | 서비스의 공개 URL (예: `https://writ.example.com`) | O |
| `DATABASE_URL` | PostgreSQL 접속 문자열 (기본값 제공) | O |
| `SECRET_KEY` | 서명/암호화용 랜덤 키 (없으면 보안 취약) | O |
| `DOMAIN` / `SCHEME` | 미설정 시 `BASE_URL`에서 자동 추출 | - |
| `SMTP_*` | 이메일 알림/인증 발송 | - |
| `S3_*` | 오브젝트 스토리지 (미설정 = 로컬 저장) | - |

### 2. 데이터 디렉토리 소유권 설정 (중요)
API 컨테이너는 이미지 안의 `writ` 사용자(보통 **UID 999**)로 실행됩니다. Docker Compose의 바인드 마운트(`data`, `uploads`, `static`, `logs`)는 **호스트 디렉토리의 권한을 그대로 따르기 때문에**, 컨테이너가 쓸 수 있도록 호스트 디렉토리의 소유자를 컨테이너 UID와 일치시켜야 합니다.

```bash
mkdir -p data uploads static logs
sudo chown -R 999:999 data uploads static logs
```

> `ls -l`에서 소유자가 `lxd`(UID 999)처럼 보여도 상관없습니다. 바인드 마운트 권한은 이름이 아니라 **숫자 UID**로 판단합니다.

컨테이너의 실제 UID가 999가 아니라면(빌드 환경에 따라 달라질 수 있음), 다음으로 확인 후 맞춰주세요:

```bash
docker compose exec api id   # 예: uid=999(writ)
```

### 3. 실행
```bash
docker compose up -d
docker compose logs -f api   # 정상 기동 확인
```

---

## Goals

- 개인 또는 소규모 커뮤니티에서 운영 가능한 서버
- 설치와 유지보수가 쉬운 구조
- ActivityPub과 높은 호환성
- 글쓰기에 적합한 사용자 경험

대규모 상용 SNS를 목표로 하지 않으며, 개인 연재자와 독자 커뮤니티를 위한 플랫폼입니다.

---

## Contributing

버그 리포트와 Pull Request를 환영합니다.

새로운 기능을 추가하기 전에 Issue를 통해 먼저 논의해 주세요.

---

## License

This project is licensed under the MIT License.
