# Security Audit TODO

## ap.py 코드 리뷰 (ap.py:116-386)

- [x] 팔로워 전용/멘션 전용 글 AP 조회 불가 — `_ap_post_visible`이 `verify_http_signature(request, b"", {})`로 GET 검증 시 activity가 비어서 바인딩 체크(ap.py:290)가 항상 실패 → 404. GET일 땐 바인딩 체크 생략 필요 (body 없는 요청만 생략, POST는 actor 필수 유지)
- [x] 죽은 삼항식 — `ap.py:538` `following.actor_uri() if ... else following.actor_uri()` → 단일 호출로 정리
- [x] 디버그 `print("[SIG] ...")` 잔존 — `ap.py:218~387` 20여 개 → `logger.debug` 전환
- [x] 인라인 `_Actor` 미영속 — ap.py:269-276 원격 액터를 DB에 저장하지 않아 요청마다 재페치 + `.id` 없어 handle_inbox AttributeError 위험 → `_resolve_actor(lightweight=True)`로 교체, DB 영속화
- [x] `_actor_fail_cache` 무제한 증가 — ap.py:33-34 만료 항목 미삭제 → `_record_actor_fail()`로 만료/최고(最古) 항목 정리 + 크기 상한
- [x] `_check_collection_access` 실질 체크 없음 — ap.py:116-122 request 미사용, 접근제어 아님 → 비활성 계정 404 처리 + 미사용 request 파라미터 제거
- [x] shared_inbox vs user_inbox 검증 불균형 — ap.py:392가 audience/actor/object 검증 및 burst/daily 제한 없음 → `_validate_inbox_activity()` 공통 검증 + burst/daily 제한 추가
- [x] 로컬 유저 전체 루프 조회 — ap.py:222-225, 233-236 시그니처 검증마다 O(n) → `_local_user_by_actor_uri()` O(1) 조회

## CRITICAL (즉시 수정)

- [ ] **Stored XSS** — `PostCard.tsx`, `MiniPostCard.tsx`, `ReplyModal.tsx`, `RightSidebar.tsx`에서 `dangerouslySetInnerHTML`에 DOMPurify 없이 유저 콘텐츠 직접 삽입. DOMPurify 설치 후 모든 dangerouslySetInnerHTML 앞에 적용
- [ ] **XSS via 커스텀 이모지 URL** — `emojis.ts:76`에서 `emoji.url`을 이스케이프 없이 `<img src>`에 삽입. 리모트 서버 악의적 URL 차단. `"` `<` `>` `'` 이스케이프 + `https:` 프로토콜 허용
- [ ] **SSRF** — `activitypub.py` 내 `_save_remote_image(:504)`, `_handle_accept(:918)`, `_fetch_remote_post(:1003)`, `_handle_undo(:1939)`, `_handle_update(:2135)`, `_handle_flag(:2318)`, `_fetch_remote_count(:578)` 에서 `httpx.get(follow_redirects=True)`. 리다이렉트 후에도 `_validate_url` 재검증 또는 `follow_redirects=False`
- [ ] **컨테이너 root 실행** — `Dockerfile`, `web/Dockerfile`에 `USER` 지시어 추가
- [ ] **타이밍 공격** — `auth.py:23`에서 `h == hashed` → `hmac.compare_digest(h, hashed)` 변경

## HIGH (상용 서비스 전)

- [ ] **CORS `["*"]`** — `config.py:44`에서 환경변수로 도메인 목록 지정. 프로덕션에서는 실제 도메인만 허용
- [ ] **에러 메시지 정보 유출** — `api.py:377,5293`에서 `detail=str(exc)` → 일반 메시지로 변경
- [ ] **Rate limiting 없음** — 로그인(`api.py:332`), 회원가입(`api.py:423`), 비밀번호 재설정(`api.py:530`)에 IP 기반 제한 + 로그인 실패 시 지수적 백오프
- [ ] **Session 쿠키 `Secure` 플래그** — `api.py:371`에서 `secure=True` 추가. 프로덕션 HTTPS 전제
- [ ] **Rate limiter TOCTOU** — `main.py:40-55`에서 뮤텍스 또는 원자적 연산으로 변경
- [ ] **WebSocket/SSE 인증 없음** — `main.py:873-906`에서 세션 쿠키 검증 추가
- [ ] **`_federation_allowed` 실패 시 열림** — `activitypub.py:44`에서 `return False`로 변경
- [ ] **IPv6 SSRF 우회** — `activitypub.py:114-124`에 `fc00::/7`, `fe80::/10`, `::ffff:0:0/96` 등 추가
- [ ] **관리자 이메일 유출** — `api_server_info`에서 비관리자에게 이메일 필드 제거. `RightSidebar.tsx:279`에서도 표시 제거
- [ ] **HMAC 64비트 잘림** — `auth.py:29`에서 `[:16]` 제거, 전체 256비트 사용
- [ ] **`SECRET_KEY` 검증** — `config.py:23`에서 시작 시 None/빈 값 체크 후 강제 종료
- [ ] **자동 마이그레이션** — `Dockerfile:22`에서 `alembic upgrade head`를 수동 트리거로 변경 또는 가드 조건 추가
- [ ] **`limit` 파라미터 상한 없음** — `api.py:853` 등 전체 페이지네이션 엔드포인트에 `min(limit, 100)` 적용
- [ ] **`/link-preview` SSRF** — `api.py:6645`에서 인증 필수 + `_validate_url` 적용

## MEDIUM

- [ ] Like/Boost TOCTOU — `api.py:1540,1629`에서 DB 고유 제약 조건 `(user_id, post_id)` 추가
- [ ] 이모지 CRUD 관리자 체크 없음 — `api.py:4860-5033`에서 `user.role` 확인
- [ ] 이미지 업로드 메모리 제한 없음 — `api.py:3558`에서 파일 읽기 전 `Content-Length`/크기 체크
- [ ] 기본 `SCHEME=http` — `config.py:18`에서 프로덕션 기본값 `https`로 변경
- [ ] Activity ID 중복 방지 race condition — `ProcessedActivity`에 고유 제약 조건 추가
- [ ] HTML 새니타이저 널 바이트 미처리 — `activitypub.py:53-92`에서 `\x00` 제거 후 정규식 적용
- [ ] 인증 로딩 3초 타임아웃 — `auth.tsx:28-32`에서 타임아웃 제거 또는 에러 상태 추가
- [ ] 비밀번호 변경 후 세션 무효화 없음 — `api.py:3591`에서 세션 쿠키 만료 처리
- [ ] Docker 보안 강화 — `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges` 추가
- [ ] `npm install` → `npm ci` — `web/Dockerfile:9`
- [ ] Dockerfile HEALTHCHECK 추가
- [ ] `.dockerignore`에 `.env.production` 추가

## LOW

- [ ] 디버그 print문 정리 — `activitypub.py`, `main.py` 내 `print()` → `logger.debug()` 전환
- [ ] `crypto_utils.py:36` 복호화 실패 시 암호문 반환 → 예외 처리
- [ ] Rate limiter 메모리 무한 성장 — `main.py:40`에서 만료 항목 정리 스케줄러
- [ ] 유저 정의 정규식 ReDoS — `api.py:704`에서 정규식 실행 전 타임아웃 설정
- [ ] VAPID 키 재시작마다 새 키 — `config.py:75-98`에서 키 영속화 확인
- [ ] Content-Security-Policy 헤더 추가
- [ ] 관리자 비밀번호 재설정 시 세션 무효화 확인
- [ ] `reset_token` 만료 시간 추가
