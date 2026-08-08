# Security Audit TODO

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

---

# Frontend Audit (web/) — 보안 우선순위

## CRITICAL (즉시 수정)

- [x] **Stored XSS → 계정 탈취 체인** — `web/src/components/RightSidebar.tsx:176`에서 리액션 알림 HTML을 정화 없이 `dangerouslySetInnerHTML`에 삽입. 근본 원인은 `web/src/lib/emojis.ts:183`의 `renderCustomEmojis`가 이모지 keyword를 `alt`/`title` 속성에 이스케이프 없이 삽입하는 것. 원격 서버 `_emojis` keyword에 `"`(예: `x" onerror="...`)를 넣으면 속성 탈출 → 저장형 XSS. 이미 세션 토큰이 `localStorage`(`web/src/lib/api.ts:21` `storeAccount`)에 평문 저장되어 있어 XSS 1건으로 전 계정 탈취. → emojis.ts 속성 이스케이프 + RightSidebar:176에 `sanitizeName` 적용
- [x] **EditModal 미정화 렌더링** — `web/src/components/EditModal.tsx:82`에서 `post.content`를 DOMPurify 없이 `dangerouslySetInnerHTML`. 원격/연합 글을 수정 모달로 열면 저장형 XSS 노출 → `sanitizePost` 적용

## HIGH (상용 서비스 전)

- [x] **관리자 페이지 인증 가드 누락** — `web/src/app/admin/rules/page.tsx`, `web/src/app/admin/announcements/page.tsx`에만 `user.role` 가드 없음 (다른 admin 12개 페이지는 전부 가드 존재). 백엔드가 거부하므로 피해 제한적이나 방어계층 보강 필요
- [x] **sanitize 설정 완화** — `web/src/lib/sanitize.ts:5,10,15`에서 `style` 속성 허용. DOMPurify가 `javascript:` CSS는 차단하지만 `background-image:url(https://evil/collect)` 같은 데이터 유출 CSS는 기본 차단 안 함 → `uponSanitizeAttribute` 훅으로 `url(`/`@import`/`expression(`/`-moz-binding`/`behavior:` 포함 style 제거. 앱 코드에는 `background-image`/`url()` CSS 사용처 없음(검색 확인)
- [ ] **세션 토큰 localStorage 평문 저장** — `web/src/lib/api.ts:6,21`(`storeAccount`), `login/page.tsx:33`, `AccountSwitcher.tsx:92`에서 전 계정 session_token을 localStorage에 저장. HttpOnly 쿠키 기반으로 재검토 (XSS 취약점 1건이면 전 계정 탈취)

## MEDIUM

- [x] **sw.js origin 검사 우회** — `web/public/sw.js:26`에서 `client.url.includes(origin)` 부분 일치 검사. push payload의 `url`을 그대로 `client.navigate()` → 유사 도메인/절대 URL 통과 가능 → `new URL().origin` 정확 비교 + 대상 URL same-origin 제한(비허용 시 `/notifications` 폴백)
- [x] **작성 중 이탈 경고 1회만 동작** — `web/src/lib/useNavigationBlock.ts:13,35,51,63,89`에서 `navigatingRef`가 true가 된 후 리셋 없음. 첫 확인 후 세션 내내 경고 비활성화 → `markNavigating()` 헬퍼로 500ms 후 리셋 + 언마운트 시 타이머 정리

## LOW

- [ ] **미사용 SSE 코드** — `web/src/lib/useStream.ts:16`이 `/api/stream`(미존재)을 여는 dead code. 실제 엔드포인트는 `/api/timeline/stream`, `/api/notifications/stream`

---

# Frontend Audit (web/) — 버그 & 병목

## 버그 (BUG)

- [ ] 인용 글 입력 중 반복 요청 — `web/src/components/PostForm.tsx:161` `!quoteUrl` 가드로 인용 해석 후에도 타이핑마다 `/api/fetch-post` 재요청
- [ ] 서버 정보 1회만 fetch — `web/src/components/RightSidebar.tsx:60` `__serverInfoFetched` 가드 미리셋 → `serverchange`로 갱신 불가, 실패 시 재시도 없음
- [ ] 알림 배열 무한 성장 — `web/src/components/RightSidebar.tsx:43-49` SSE 알림 prepend 상한 없음
- [ ] Backspace 중복 트리거 — `web/src/components/AccountSwitcher.tsx:42-45` 모달 닫기 + KeyboardShortcuts `router.back()` 동시 발생
- [ ] PostForm:104 `seriesEpisodeMatch` dead code / :671 `setPollExpiresIn(24)` 유효 옵션 아님 / :659-662 업로드 실패 조용히 사라짐 / :907 `mediaUploading` 미사용 / :919-924 stale `content` 클로저
- [ ] InfiniteScroll.tsx:28-33 `.main-content` 1회 조회 — 없으면 무한 스크롤 정지
- [ ] Avatar.tsx:13-16 `imgError` 미리셋 — avatar 변경돼도 폴백 유지
- [ ] ScrollRestoration.tsx:56-74 `scrollRestoration="manual"` 미복원
- [ ] MiniPostCard.tsx:62-66 엔티티 디코딩 휴리스틱 — `&amp;` 텍스트가 태그로 변환될 수 있음
- [ ] users/settings/export/page.tsx:41 SettingsNav 탭 오표시 (`current="migrate"`)
- [ ] page.tsx(홈):18 클라이언트 useEffect에서 서버용 `redirect()` 사용 → `router.replace` 권장

## 병목 (PERF)

- [ ] 알림 SSE 2중 연결 — `RightSidebar.tsx:35` + `NotifSound.tsx:37` 페이지당 EventSource 2개
- [ ] 공지 폴링 3중화 — `AnnouncementToast.tsx:52`/`Sidebar.tsx:97`/`MobileNav.tsx:73`이 각각 30초 폴링
- [ ] ScrollRestoration.tsx:46-50 모든 scroll 이벤트마다 sessionStorage 전체 직렬화
- [ ] quote-cache.ts:6 memoryCache 무제한 (세션 동안 인용 글 전부 보유)
- [ ] series/[id]/notices/[nid]/page.tsx:31, [nid]/edit:34, series/[id]/page.tsx:70-73 공지 전체 fetch 후 클라이언트 필터
- [ ] emojis.ts:78 이모지 전체 `limit=9999` 로드 → localStorage 캐시
- [ ] timeline/[type]/page.tsx 계정별 타임라인 localStorage 평문 캐시(5분 TTL)
