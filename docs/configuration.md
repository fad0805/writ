# 환경 변수 참조

`APP_ENV`에 따라 `.env.development`(개발) 또는 `.env.production`(운영) 파일이 로드됩니다. 아래 항목은 운영 파일(`.env.production`) 기준입니다.

## 서버 기본

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `APP_ENV` | `development` | `production`으로 설정하면 운영 모드. 운영에서는 이메일 인증이 필수이며 쿠키가 `Secure`로 설정됩니다. |
| `BASE_URL` | (없음) | 서비스 공개 URL (예: `https://writ.example.com`). 연합, 이메일 인증 링크, CORS에 사용됩니다. |
| `DOMAIN` | `BASE_URL`에서 자동 추출 | 도메인 (연합용). |
| `SCHEME` | `BASE_URL`에서 자동 추출 | `http` 또는 `https`. |

## 데이터베이스

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | (필수) | SQLAlchemy 접속 문자열. 기본 제공값은 PostgreSQL. 로컬 테스트용으로 `sqlite:///data/writ.db`도 사용 가능합니다. |
| `POSTGRES_USER` | (없음) | db 컨테이너가 생성할 DB 사용자. |
| `POSTGRES_PASSWORD` | (없음) | db 컨테이너 DB 비밀번호. |
| `POSTGRES_DB` | (없음) | db 컨테이너가 생성할 DB 이름. |

## 보안

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SECRET_KEY` | (필수) | 세션 서명, CSRF 등에 사용되는 랜덤 키. 누출 시 연합 키가 위험해지므로 반드시 길고 무작위한 값을 사용하세요. |
| `KEY_ENCRYPTION_SALT` | (없음, 레거시 호환) | 사용자 ActivityPub 개인키 암호화 전용 솔트. 설정하면 PBKDF2 파생 체계로 저장하고, 기존(솔트 없는) 암호문도 자동으로 읽습니다. |
| `INITIAL_OWNER_PASSWORD` | (없음) | 설정하면 첫 번째 가입자의 비밀번호가 반드시 이 값이어야 owner가 됩니다. |
| `SSRF_ALLOWED_DOMAINS` | (없음) | 서버 측에서 접근을 허용할 추가 도메인 목록 (SSRF 방지 예외). |

> **SECRET_KEY 교체 시 주의**: 이미 암호화된 개인키는 구 시크릿으로만 복호화됩니다. 교체 전에 `app/utils/crypto.py`의 `reencrypt_private_key()`로 모든 개인키를 신 시크릿 조합으로 재암호화해야 합니다.

## SNS 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MAX_POST_LENGTH` | `500` | 한 포스트의 최대 글자 수. |

## 이메일 (SMTP)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SMTP_SERVER` | (없음) | SMTP 서버 주소. **운영에서 이메일 인증/알림을 위해 필수.** |
| `SMTP_PORT` | `587` | SMTP 포트. `465`면 SSL, 그 외에는 STARTTLS를 시도합니다. |
| `SMTP_USER` | (없음) | SMTP 로그인 사용자. |
| `SMTP_PASSWORD` | (없음) | SMTP 로그인 비밀번호. |
| `SMTP_FROM` | (없음) | 발신자 주소. 미설정 시 `noreply@writ.local`. |

> 운영 모드에서 SMTP가 없으면 이메일 인증을 받을 수 없어 **로그인이 불가능**합니다.

## 파일 저장 (S3 호환 오브젝트 스토리지)

미설정이면 로컬 디스크(`uploads/`)에 저장됩니다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `S3_ENABLED` | `false` | `true`로 설정하면 S3 호환 스토리지 사용. |
| `S3_ENDPOINT` | (없음) | S3 엔드포인트. |
| `S3_REGION` | `auto` | 리전. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | (없음) | 인증 키. |
| `S3_BUCKET` | (없음) | 버킷 이름. |
| `S3_PUBLIC_URL` | (없음) | 버킷 공개 URL (예: `https://files.example.com`). |

## 미디어 정리

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ORPHAN_MEDIA_MIN_AGE_DAYS` | `7` | 매일 3시 워커가 참조되지 않은 `uploads/media/` 파일을 정리할 때 기준 일수. 초안 등 나중에 쓰일 미디어를 보호하려면 값을 올리세요. |

## 웹 푸시 (VAPID)

미설정 시 최초 기동 때 자동 생성되어 DB에 저장됩니다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `VAPID_PRIVATE_KEY` | (없음) | 브라우저 푸시 알림용 개인 키. |
| `VAPID_PUBLIC_KEY` | (없음) | 브라우저 푸시 알림용 공개 키. |

사전 생성:

```bash
docker compose exec api python3 -c "
import py_vapid; v=py_vapid.Vapid(); v.generate_keys();
priv=v.private_pem().decode().strip(); pub=v.public_pem().decode().strip()
print('VAPID_PRIVATE_KEY=\"'+priv.replace(chr(10),'\\\\n')+'\"')
print('VAPID_PUBLIC_KEY=\"'+pub.replace(chr(10),'\\\\n')+'\"')
"
```

## CORS

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `CORS_ORIGINS` | `BASE_URL` (없으면 `*`) | 허용할 출처 목록 (쉼표 구분). |
| `CORS_ALLOW_CREDENTIALS` | origin을 명시 설정한 경우에만 `true` | 교차 출처 요청에 쿠키(인증 정보) 포함을 허용합니다. 출처를 명시하지 않아 와일드카드(`*`)로 폴백한 상태에서는 임의 사이트에 인증 쿠키가 노출되지 않도록 강제로 비활성화됩니다. |
