# レビュー観点（8 lenses）

| # | 観点 | 何を見るか | 起動 |
| --- | --- | --- | --- |
| 1 | **Security** | OWASP Top 10 / CWE 経路。`exec`/`pickle`/SSRF/SQL/XSS/SSRF/CSRF/JWT/秘密漏れ/LLM prompt injection を sink までトレース | 常時 |
| 2 | **Performance** | N+1、blocking I/O、unbounded growth、O(N²)、DB index、contention、payload size、p99/tail latency | 常時 |
| 3 | **SRE** | timeout/retry/circuit breaker、構造化ログ、metric カーディナリティ、idempotency、DLQ、feature flag、graceful shutdown、SLO/MTTR 影響 | 常時 |
| 4 | **Coverage** | 新規ロジック・境界値・エラーパス・回帰・並行・property-based 候補、mutation で生き残る弱 assertion、test smell（flaky / change-detector / mystery guest） | 常時 |
| 5 | **API Contract** | breaking change（フィールド削除/型ナロー/必須化/enum/HTTP status/pagination/auth scope/protobuf reserved/DB NOT NULL/SDK signature/semver） | スキーマ / migration / SDK が diff にあるとき |
| 6 | **Dependencies** | 必要性 / Scorecard / typosquatting / install script / lockfile 整合 / pinning / CVE / license / 署名 / freshness / capability creep（20 項目） | manifest / lockfile が diff にあるとき |
| 7 | **Architecture** | モジュール境界 / レイヤ違反 / 結合度 / 凝集度 / shallow module / 早すぎる抽象 / god class / DDD 境界 / ACL / 循環 | `--reviewers all` 等で明示指定時のみ |
| 8 | **Maintainability** | 複雑度 / マジック定数 / Rule-of-Three 後の DRY / デッドコード / shallow module / コメント WHY-not-WHAT / 構造変更と挙動変更の混在 | `--reviewers all` 等で明示指定時のみ |

各観点とも **「悪用可能か / 障害になるか / クライアントを壊すか」が判定基準**。理論上の可能性ではなく到達可能な失敗経路だけ報告する。各 prompt の冒頭に「flag してはいけない anti-patterns」を明示し、bikeshed・命名 nit・style 押し付けを構造的に排除している。

## Severity 共通定義
- **critical**: 本番影響に直結（RCE / データ漏洩 / SLO 違反 / breaking change without migration）
- **warning**: 防御層欠如 or MTTR 増 or 測定可能な劣化
- **suggestion**: 改善余地、現時点で実害なし

## 出力
各観点が `<*_review>` XML を独立に生成 → **Coordinator** が重複排除・severity 降順ソート・最終 verdict（`APPROVE` / `REQUEST_CHANGES` / `NEEDS_DISCUSSION`）を出す。critical が 1 件でもあれば先頭に `🚨 CRITICAL ISSUES FOUND`。

## 一次情報源
OWASP Top 10 / CWE Top 25 / NIST SSDF / SLSA / OpenSSF Scorecard / Google SRE Book / Google AIP / AWS Builders' Library / Brendan Gregg / Martin Fowler / John Ousterhout APoSD / Kent Beck Tidy First / Honeycomb ODD / xUnit Test Patterns / Stryker / Hypothesis

詳細チェックリスト（180 項目、出典 URL 付き）: [`docs/best-practices/`](./best-practices/)
