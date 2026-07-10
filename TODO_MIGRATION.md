# TODO: 파일 기반 저장소 → SQLite 마이그레이션

지금은 속도 우선으로 JSON/JSONL 파일 + `threading.Lock` 조합을 그대로 쓰고 있다.
아래 저장소들이 전부 같은 패턴이라, SQLite로 옮길 때 한 번에 정리한다. 개별적으로
하나씩 리팩토링하지 말 것 — 빠뜨리는 저장소가 생기면 그 저장소만 예전 버그를
그대로 안고 간다.

## 대상 저장소 (main.py)

| 클래스 | 파일 경로 | 패턴 | 문제 |
|---|---|---|---|
| `RateLimiter` | `usage/{key}_{month}.json` | 키+월별 파일, read-modify-write | 파일 개수만 늘어남, 개별 파일은 작아서 상대적으로 안전 |
| `APIKeyStore` | `keys/api_keys.json` | 전체 고객 키를 **하나의 파일**에 저장 | 고객이 늘수록 모든 요청이 이 파일을 두고 경합 (전역 병목) |
| `TransactionStore` | `usage/transactions/{key}.jsonl` | append-only, 조회 시 **전체 파일 읽음** | Pro/Enterprise가 "무제한"이라 활성 고객일수록 대시보드가 느려짐 |
| `WebhookStore` (설정) | `keys/webhooks.json` | 전체 고객 webhook 설정을 하나의 파일에 저장 | APIKeyStore와 동일한 전역 병목 |
| `WebhookStore` (배달 로그) | `usage/webhook_deliveries/{key}.jsonl` | append-only, 무제한 증가 | TransactionStore와 동일한 문제 |
| `AccessTokenManager` | `usage/x402_token_*.json` | 토큰 1건당 파일 1개 생성, 삭제 로직 없음 | 디스크에 파일이 계속 쌓임 (기능엔 영향 없지만 정리 필요) |

## 왜 지금 안 고치나

- 지금 트래픽 규모(디자인 파트너 3~5명, 무료 온보딩 단계)에서는 체감 성능 저하 없음.
- `threading.Lock`은 **단일 프로세스** 기준으로는 안전. 지금 배포가 `uvicorn main:app`
  단일 워커라 문제 없음.
- 저장소 5개를 따로따로 옮기면 스키마가 제각각이라 나중에 더 헷갈림. SQLite로 갈 때
  한 번에 테이블 설계하는 게 낫다.

## 언제 해야 하나 (트리거 조건 — 하나라도 해당되면 착수)

1. `uvicorn --workers N` (N>1) 또는 여러 인스턴스로 배포하게 될 때
   → `threading.Lock`은 프로세스 간 경합을 못 막음. 특히 `APIKeyStore.revoke_key`
   같은 쓰기 작업이 조용히 유실될 수 있음 (키 폐기했는데 안 먹힌 것처럼 보이는 버그).
2. 유료 고객이 두 자릿수를 넘어가서 `keys/api_keys.json` / `keys/webhooks.json`이
   커질 때 → 모든 요청이 이 파일을 매번 통째로 읽고/쓰므로 고객이 늘수록 전체
   응답 속도가 느려짐.
3. Pro/Enterprise 고객 중 트랜잭션이 많이 쌓인 활성 사용자가 생겨서
   `/usage/dashboard`, `/usage/transactions` 응답이 눈에 띄게 느려질 때.

## 마이그레이션 방향 (착수할 때 참고)

- SQLite (파일 하나, WAL 모드) + 기존 sync 함수를 `ThreadPoolExecutor`로 감싸는
  현재 패턴 그대로 재사용 (이미 XRPL 호출에 쓰고 있는 방식과 동일).
- 테이블 후보: `api_keys`, `webhooks`, `webhook_deliveries`, `transactions`, `usage_counters`.
  `api_keys.key_hash`에 인덱스 걸면 `find_by_key` 조회가 지금처럼 파일 전체를
  읽을 필요 없이 O(1)에 가까워짐.
- `TransactionStore.list_transactions` / `cumulative_fees`는 `WHERE api_key_hash = ? ORDER BY
  timestamp DESC LIMIT ?` 같은 쿼리로 대체 — 지금처럼 파일 전체를 메모리에 올릴 필요 없음.
- `AccessTokenManager`는 토큰 자체가 JWT라 서버 측 조회가 필요 없으므로, 감사 로그
  목적이 아니라면 파일 기록 자체를 없애는 것도 고려 (지금은 디버깅용으로만 남아있음).
- 여러 프로세스로 스케일아웃할 계획이 확정되면 SQLite WAL로도 부족할 수 있으니
  그때는 Redis(락/캐시)나 Postgres 전환도 같이 검토.
