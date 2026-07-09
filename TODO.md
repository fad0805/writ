# ActivityPub 안정화 TODO

## 🔴 즉시 (테스트 통신을 위해 반드시 필요)

- [ ] `DOMAIN`/`SCHEME` 환경변수 설정 — `config.py:9-11`
  `BASE_URL = "None://None"` → 모든 AP URI가 깨짐. `.env`에 `DOMAIN`과 `SCHEME` 추가.
- [ ] `Novel` 모델 import 누락 — `main.py:592`
  `get_series_by_handle`에서 `NameError`. `Novel`을 import에 추가.
- [ ] `User.actor_uri()`를 SQL 컬럼처럼 사용 — `activitypub.py:1086`
  `User.actor_uri() == old_actor_url` → `TypeError`. 로컬 유저 조회 로직 수정 필요.
- [ ] 존재하지 않는 `actor_url` 컬럼 조회 — `activitypub.py:1042`
  `.filter_by(actor_url=...)` → `InvalidRequestError`. `remote_url` 또는 `actor_uri()`로 변경.
- [ ] `_deliver_sync`가 HTTP 에러를 성공으로 처리 — `activitypub.py:1154-1163`
  `httpx.post()`가 4xx/5xx에서 예외를 던지지 않음. `raise_for_status()` 또는 상태 코드 체크 추가.

## 🟡 높음 (기능/호환성)

- [ ] Digest 헤더가 GET 요청에도 필수 — `main.py:304-328`
  잠긴 계정의 outbox/followers 컬렉션 접근 불가. GET 요청은 Digest 검증 생략 필요.
- [ ] Mention이 AP `tag` 배열 아닌 본문 텍스트에서만 파싱 — `activitypub.py:741-747`
  `tag` 배열에서 `Mention` 타입 항목 처리 추가.
- [ ] Create activity의 `attributedTo` 불일치 미검증 — `activitypub.py:694-827`
  내부 Note의 `attributedTo`가 활동 `actor`와 일치하는지 확인.
- [ ] 게시글 삭제 전파 수신자 오류 — `activitypub.py:1016-1032`
  `send_to_shared_inbox(sender, delete)`는 sender가 팔로우하는 계정에 보냄 → 잘못됨.
- [ ] Date 헤더 `%Z` 파싱 불안정 — `main.py:350`
  `email.utils.parsedate_to_datetime`으로 교체.

## 🟢 중간

- [ ] `to_ap_note()`에 `attachment` 배열 누락 — `models.py:239-290`
  미디어 첨부물이 AP Note에 포함되지 않음.
- [ ] `to_ap_note()`에 `sensitive` 플래그 누락 — `models.py:239-290`
  민감한 게시글 표시 불가.
- [ ] Like/Boost 엔드포인트에 `media_type` 누락 — `main.py:523-563`
  `media_type="application/activity+json"` 추가.
- [ ] WebFinger에 `Content-Type: application/jrd+json` 누락 — `main.py:181-219`
- [ ] Username 정규식이 `\w+`만 허용 — `activitypub.py:134`
  점/하이픈 등 포함하도록 수정.
- [ ] 시그니처 헤더 `created`가 signed headers에 없음 — `activitypub.py:1180-1185`
  `headers` 파라미터에 `(created)` 추가.
- [ ] Rate limiting 인메모리 (재시작 시 초기화) — `main.py:31-68`
  다중 워커 환경에서 무의미. DB 기반 고려.
- [ ] 아웃바운드 재시도가 에러 유형 구분 없음 — `activitypub.py:1154-1163`
  4xx는 영구 실패로 즉시 중단, 5xx만 재시도.
- [ ] `ap_id`/`ProcessedActivity.id` 길이 512 — `models.py:193,643`
  일부 URL에서 잘림 가능. `String(1024)` 또는 `Text`로 변경.
- [ ] SMTP 환경변수명 불일치 — `.env.production:23`
  `SMTP_FROM_ADDRESS` → `SMTP_FROM`으로 통일.
- [ ] 자기 자신에게 알림 생성 가능 — `activitypub.py:796-803`
  답글 알림에서 발신자와 수신자가 같으면 skip.
- [ ] 원격 액터 도메인 검증 없음 — `activitypub.py:469-570`
  `_resolve_actor`가 응답의 도메인이 요청 URL과 일치하는지 확인.

## 🔵 개선

- [ ] `robots.txt` 추가
- [ ] Actor JSON에 `updated` 필드 추가 — `models.py:101-143`
- [ ] Create activity ID가 dereferenceable하지 않음 — `models.py:296`
  `GET /activities/create/{id}` 엔드포인트 추가.
- [ ] 인바운드 `_handle_create` 콘텐츠 길이 제한 — `activitypub.py:694-827`
- [ ] Locked 계정 검증 시 GET 요청 signed string `"post"` → `"get"` 수정 — `main.py:364`
- [ ] 공유 인박스 엔드포인트 광고
- [ ] `_handle_accept`에서 원본 Follow 요청 존재 확인
- [ ] `_handle_delete`에서 삭제 전파 (받은 삭제를 다른 인스턴스로)
