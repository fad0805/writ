# ActivityPub 안정화 TODO

모든 항목 완료됨 ✅

- [x] `DOMAIN`/`SCHEME` 환경변수 설정
- [x] `Novel` 모델 import 누락
- [x] `User.actor_uri()`를 SQL 컬럼처럼 사용
- [x] 존재하지 않는 `actor_url` 컬럼 조회
- [x] `_deliver_sync`가 HTTP 에러를 성공으로 처리
- [x] Digest 헤더가 GET 요청에도 필수
- [x] Mention이 AP `tag` 배열 아닌 본문 텍스트에서만 파싱
- [x] Create activity의 `attributedTo` 불일치 미검증
- [x] 게시글 삭제 전파 수신자 오류
- [x] Date 헤더 `%Z` 파싱 불안정
- [x] `to_ap_note()`에 `attachment` 배열 누락
- [x] `to_ap_note()`에 `sensitive` 플래그 누락
- [x] Like/Boost 엔드포인트에 `media_type` 누락
- [x] WebFinger에 `Content-Type: application/jrd+json` 누락
- [x] Username 정규식이 `\w+`만 허용
- [x] 시그니처 헤더 `created`가 signed headers에 없음
- [x] 아웃바운드 재시도가 에러 유형 구분 없음
- [x] `ap_id`/`ProcessedActivity.id` 길이 512
- [x] SMTP 환경변수명 불일치
- [x] 자기 자신에게 알림 생성 가능
- [x] 원격 액터 도메인 검증 없음
- [x] `robots.txt` 추가
- [x] Actor JSON에 `updated` 필드 추가
- [x] Create activity ID가 dereferenceable하지 않음
- [x] 인바운드 `_handle_create` 콘텐츠 길이 제한
- [x] 공유 인박스 엔드포인트 광고
- [x] `_handle_accept`에서 원본 Follow 요청 존재 확인
