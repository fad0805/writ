# ActivityPub 안정화 TODO

## 필수
- [ ] 신고(`Flag`) activity 구현 — 로컬 신고를 원격 서버로 전송, 수신한 신고 처리
- [ ] 전송 실패 시 재시도/큐잉 — outbound delivery 신뢰성 확보
- [ ] 원격 미디어 캐싱/저장 — 용량 제한, 만료 정책
- [ ] Inbound activity 검증 강화 — HTTP Signatures, activity 유효성, 중복 체크
- [ ] Rate limiting — inbound 활동 제한

## 중요
- [ ] NodeInfo — 서버 정보 공개 (연합 discoverability)
- [ ] WebFinger — `user@domain` 형식의 계정 검색 지원
- [ ] `Move` activity — 계정 이전
- [ ] `Reject` activity — 팔로우 거절 전파
- [ ] `Delete` activity 전파 — 게시글/계정 삭제를 원격에 알림
- [ ] 인스턴스 차단/뮤트 전파 — 차단된 서버와의 상호작용 차단

## 개선
- [ ] Remote follow (원격 계정을 로컬에서 팔로우)
- [ ] 컬렉션 페이지네이션 (followers/following/outbox)
- [ ] ActivityPub CORS 헤더
- [ ] 객체 만료/정리 — 오래된 원격 activity 정리
- [ ] 성능: DB 인덱스 최적화, bulk insert
