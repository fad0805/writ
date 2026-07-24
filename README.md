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
cp .env.production.example .env
docker compose up -d
```

기본적으로 Docker Compose를 사용하여 실행합니다.

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
