---
title: SRE Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://sre.google/sre-book/evolving-sre-engagement-model/
  - https://sre.google/sre-book/launch-checklist/
  - https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
  - https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/
  - https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html
  - https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html
  - https://opentelemetry.io/docs/specs/semconv/general/trace/
  - https://opentelemetry.io/docs/concepts/semantic-conventions/
  - https://www.honeycomb.io/blog/observability-driven-development-for-tackling-the-great-unknown
  - https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/
---

# SRE Code Review Best Practices

## Why this matters

SRE レビューは「深夜3時に pager が鳴ったとき、このコードから障害原因を特定し、SLO を守って復旧できるか」を判定する作業である。Google SRE Book は本番投入前の Production Readiness Review (PRR) で instrumentation・monitoring・emergency response を網羅的に検証することを必須としており [1]、Honeycomb の Charity Majors は「テストなしの PR を受け入れないのと同様に、`how will I know when this isn't working?` に答えられない PR は受け入れるな」と明言している [9]。レビューで取りこぼした reliability gap は、本番では MTTR の増加・SLO error budget の浪費・cascading failure として顕在化する [3][5]。

## Review checklist

### 1. 外部呼び出しに明示的な timeout が設定されているか
- **What to look for**: HTTP client / DB driver / RPC client / message broker への呼び出しで、connect timeout・read timeout・overall deadline が設定されているか。`http.Client{}` (Go default = 無限)、`requests.get(url)` (Python default = 無限) など、デフォルトが無限大の API は特に注意。
- **Why**: timeout なしの呼び出しは、下流が hang したときに上流の goroutine / thread / connection を食い潰し、cascading failure を起こす [3]。AWS は「many failures appear as requests taking longer than usual, and potentially never completing」と指摘 [3]。
- **How to apply in a diff**: `requests.`, `http.Get`, `urlopen`, `psycopg2.connect`, `grpc.Channel`, `redis.Redis(` などのパターンで grep し、timeout 引数の有無を確認。context 経由なら `context.WithTimeout` / `context.WithDeadline` の伝播もチェック。
- **Failure scenario**: 深夜3時、決済 API が応答停止。timeout 未設定のため worker thread が全て待機状態に陥り、関係ない /health エンドポイントも応答しなくなる。Kubernetes が liveness probe 失敗で全 Pod を再起動するが、再起動後すぐ同じ状態に戻り復旧不能。
- **Source**: [AWS Builders' Library — Timeouts, retries and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)

### 2. リトライに exponential backoff + jitter が入っているか
- **What to look for**: 失敗時の `time.sleep(1)` 固定待機や `delay *= 2` のみ (jitter 無し) のループ。AWS SDK の full jitter (`sleep = random_between(0, min(cap, base*2^attempt))`) パターンが推奨。
- **Why**: 固定待機・jitter 無し backoff は thundering herd を引き起こす。下流が一瞬詰まっただけで全クライアントが同時にリトライし、復旧を遅延させる [3][4]。
- **How to apply in a diff**: `retry`, `backoff`, `sleep(`, `Thread.sleep` を grep。リトライループ内で random 要素が無いものは flag。
- **Failure scenario**: DB が 2 秒間スパイクで詰まり 1000 クライアントが同時タイムアウト。jitter なし固定 1 秒リトライで、復旧直後の DB に 1000 req/s が殺到し再度ダウン。リトライ storm で 30 分復旧不能。
- **Source**: [AWS Architecture Blog — Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)

### 3. リトライに max attempts と全体 deadline があるか
- **What to look for**: `while True:` 無限リトライ、max retry count 未設定、外側の context deadline 未設定。各リトライにも個別 timeout が必要。
- **Why**: 上限の無いリトライは worker を永久占有し、リトライ予算 (retry budget) を破壊する。AWS は「retries should add no more than 10% traffic」を rule of thumb として提示 [3]。
- **How to apply in a diff**: リトライロジックで `max_attempts` / `max_retries` / `MaxElapsedTime` パラメータが渡されているか。`context.WithTimeout` が親 context に設定されているか。
- **Failure scenario**: 下流が完全停止しているのにリトライが永遠に続き、上流の queue が溢れて全リクエストが OOM kill される。
- **Source**: [AWS Prescriptive Guidance — Retry with backoff](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/retry-backoff.html)

### 4. リトライ対象エラーが正しく限定されているか
- **What to look for**: 4xx (特に 400/401/403) を retry している、`except Exception:` で全例外 retry、context cancel (deadline exceeded ではなく主動 cancel) も retry している、など。
- **Why**: non-retryable error の retry はサーバーリソースを浪費するだけで成功確率は上がらない。429 と 503/408/5xx・network timeout のみ retry すべき [3]。
- **How to apply in a diff**: retry 判定の `if` 条件で、status code・error type が明示的に絞られているか。
- **Failure scenario**: 認証トークン期限切れで 401 を返している API に 5 回リトライし、最終的にユーザーに 5 倍遅れたエラーを返却。MTTR は変わらず、ただ体感劣化のみ。
- **Source**: [AWS Builders' Library — Timeouts, retries and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)

### 5. 書き込み系操作に idempotency token があるか
- **What to look for**: 決済・リソース作成・課金など mutating operation で、client-supplied idempotency key / request id が渡されているか。サーバー側は token を atomic に永続化しているか。
- **Why**: timeout やネットワーク断による retry で副作用が二重実行されると、二重課金・重複リソース作成が発生。AWS Well-Architected REL04-BP04 は「make mutating operations idempotent」を必須要件として規定 [6]。
- **How to apply in a diff**: `POST /payments`, `CreateInstance`, `enqueue` などの mutating call で `Idempotency-Key` ヘッダや `ClientToken` 引数が無い場合 flag。サーバー側実装では token を DB unique constraint で保存しているか確認。
- **Failure scenario**: 決済 API が timeout、クライアントが retry。同じユーザーから 3 件の決済レコードが作成され、$300 が三重課金される。CS から問い合わせが殺到し、手動で返金処理。
- **Source**: [AWS Well-Architected — REL04-BP04 Make mutating operations idempotent](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_prevent_interaction_failure_idempotent.html)

### 6. 持続的な障害に対する circuit breaker / fail-fast があるか
- **What to look for**: 同一下流への大量失敗が続いても retry し続けていないか。`failure_threshold`, `open_timeout`, `half_open_max_calls` を持つ breaker 実装が挟まっているか。
- **Why**: transient failure は retry で吸収できるが、systemic failure (下流が落ちている) では retry はリソース浪費。breaker で fail-fast すべき [3][5]。
- **How to apply in a diff**: 外部依存呼び出し箇所で `pybreaker`, `resilience4j`, `gobreaker`, `Polly` などの breaker wrap が無い場合、または手書きで failure count をしていない場合 flag。
- **Failure scenario**: 下流 API が完全停止しているのに 100 ms ごとに retry し続け、上流の thread pool を埋め尽くす。breaker があれば 5 秒で fail-fast し、上流の他のエンドポイントは正常応答できた。
- **Source**: [AWS Prescriptive Guidance — Circuit breaker pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html)

### 7. 例外を握りつぶしていないか
- **What to look for**: `except Exception: pass`, `catch (Exception e) {}`, Go の `_ = err`, Rust の `let _ = result;` など error を完全に silent drop しているコード。
- **Why**: 握りつぶされたエラーは observability gap を生み、本番障害時に根本原因が一切残らない。silent failure は最悪のクラスの failure mode [9]。
- **How to apply in a diff**: `except.*:\s*pass`, `catch.*\{\s*\}`, `_ = .*Err`, `\.unwrap_or\(\)` を grep。意図的な無視であれば `// intentionally ignored: ...` のコメント or context-aware log が必要。
- **Failure scenario**: バックグラウンドジョブが silent fail を続けていたが、エラーログが一切出ていないため誰も気付かず、3 日後に「データが更新されていない」と顧客から通報。
- **Source**: [Google SRE Book — Chapter 6: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)

### 8. エラーが context を保ったまま wrap されて propagate されているか
- **What to look for**: Go で `return err` のまま (どの関数で起きたか不明)、Python で `raise NewError("failed")` で原因 traceback を捨てている、Rust で `.map_err(|_| MyError)` で source を失っている、など。
- **Why**: context 無しに propagate された error は、stack trace と業務情報 (user_id, request_id, operation) が欠落し、debugging が困難。Go は `fmt.Errorf("...: %w", err)`、Python は `raise X from e`、Rust は `anyhow::Context` / `thiserror #[from]` で source chain を保つべき。
- **How to apply in a diff**: error return 箇所で wrap 関数の使用を確認。`return err` だけのものは flag。
- **Failure scenario**: 「`connection refused`」というログだけが残り、どの下流・どのテナント・どの operation で起きたか不明。原因特定に 2 時間。
- **Source**: [Go Blog — Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)

### 9. ログが structured (JSON / key-value) で出ているか
- **What to look for**: `print(f"user {user_id} failed: {err}")` のような文字列補間ログ、`log.Info("processing")` で context 情報が無いログ。
- **Why**: 構造化されていないログは grep でしか検索できず、ダッシュボード化・アラート化・aggregation ができない。OTel / AWS / GCP 各社が structured logging を必須とする [7]。
- **How to apply in a diff**: ログ呼び出しで `logger.info("msg", extra={...})` や `slog.Info("msg", "key", value)`、JSON formatter の使用を確認。f-string / `%s` のみの logger は flag。
- **Failure scenario**: 障害時に「user_id=12345 だけ失敗している」を確認したいが、ログが `failed to update user X` 形式で grep するしかなく、集計に 30 分。
- **Source**: [OpenTelemetry — Structured Logs Specification](https://opentelemetry.io/docs/specs/otel/logs/)

### 10. ログに correlation ID (trace_id / request_id) が付いているか
- **What to look for**: ログ出力箇所で trace_id / span_id / request_id が常に含まれているか。OTel SDK 使用時は LogRecord に自動注入されるが、手書き logger では明示が必要。
- **Why**: 分散システムでは複数サービスのログを横断検索する必要があり、correlation ID 無しでは「あるリクエストが失敗した経路」を辿れない [7]。
- **How to apply in a diff**: logger 設定で trace context injection が有効か。middleware で request_id を logger に bind しているか。
- **Failure scenario**: ユーザーから「注文 ID X が失敗した」と報告。5 サービスを順に grep で追うが、サービス間の対応関係が不明で 1 時間ロスト。
- **Source**: [OpenTelemetry — Logs Specification (Correlation)](https://opentelemetry.io/docs/specs/otel/logs/)

### 11. メトリクスラベルの cardinality が爆発していないか
- **What to look for**: `counter.inc(user_id=u, request_id=r)` のように unbounded な値をラベルに入れているコード。URL を `/users/123` のまま記録、エラーメッセージ全文をラベルに入れる、なども cardinality 爆発の原因。
- **Why**: metric label の cardinality は時系列数に直結し、Prometheus / Datadog の cost を線形増加させる。OTel SDK は default cardinality limit 2000 を超えるとオーバーフロー [7]。
- **How to apply in a diff**: メトリクス emit 箇所で label に user_id / order_id / 生 URL / IP が混入していないか確認。URL は `/users/{id}` のように parameterize。
- **Failure scenario**: 新機能リリース後、Prometheus メモリが 10x に膨張し OOM。週末に on-call が呼ばれる。
- **Source**: [Better Stack — OpenTelemetry Best Practices](https://betterstack.com/community/guides/observability/opentelemetry-best-practices/)

### 12. 重要操作にトレーススパンが張られ、attribute が付いているか
- **What to look for**: 外部呼び出し・DB クエリ・キュー操作で span が作成されているか。`http.method`, `db.system`, `messaging.system` など OTel semantic convention に従った属性が付いているか。
- **Why**: span attribute は「特定のテナントのみ遅い」「特定の DB shard だけ失敗」を判別する高 cardinality な debugging を可能にする。低 cardinality な metric では絶対に得られない情報 [8][9]。
- **How to apply in a diff**: 新規追加のサービス境界で `tracer.start_as_current_span(...)` の呼び出しがあるか。属性キーが OTel semconv (`http.request.method`, `db.system.name` 等) に準拠しているか。
- **Failure scenario**: p99 latency が 2 倍に劣化したが、特定の下流の特定の操作だけ遅いことが span 無しで特定できず、原因特定に 4 時間。
- **Source**: [OpenTelemetry — Trace Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/general/trace/)

### 13. SLI に直結する重要パスにメトリクスが emit されているか
- **What to look for**: 新規エンドポイント / 新規バックグラウンドジョブ追加時に、request count / error count / latency histogram (RED method) が必ず emit されているか。
- **Why**: SLO 違反を検知するための SLI が無いコードは「壊れていても気付けない」。Google SRE Book は SLI/SLO/SLA をサービスの第一級要件として扱う [1][2]。
- **How to apply in a diff**: 新規 handler で `histogram.record(...)` や `counter.add(...)` の呼び出しがあるか。既存の middleware で自動取得されている場合はそれを確認。
- **Failure scenario**: 新エンドポイントが 5% エラーを返しているが、メトリクス未配線でダッシュボードに出ず、顧客 escalation で初めて発覚。
- **Source**: [Google SRE Book — Chapter 4: Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)

### 14. liveness と readiness probe が分離されているか
- **What to look for**: Kubernetes Deployment YAML / ヘルスチェックハンドラで、liveness と readiness が同一 endpoint を使っていないか。liveness が DB チェックなど heavy な依存を含んでいないか。
- **Why**: 同一 endpoint だと「依存が一時的に落ちたら全 Pod が再起動」する restart loop を起こす。liveness はプロセス生存確認のみ、readiness は依存込みで判定すべき。
- **How to apply in a diff**: `livenessProbe.httpGet.path` と `readinessProbe.httpGet.path` が異なるか。`/healthz/live` と `/healthz/ready` のように分離されているか。
- **Failure scenario**: 下流 DB が 30 秒詰まっただけで、liveness probe が失敗し全 Pod が同時に再起動。スタートアップ中に再度 probe 失敗で再起動ループに突入し、自力復旧不能。
- **Source**: [Kubernetes — Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)

### 15. graceful shutdown と in-flight request 完了が考慮されているか
- **What to look for**: SIGTERM を受けてから shutdown までに、(a) readiness probe を fail にする、(b) in-flight request の完了を待つ、(c) DB / queue connection を flush、というシーケンスがあるか。
- **Why**: 急停止は in-flight request を打ち切り、ユーザーに 5xx を返す。デプロイ毎に微小 error rate が出ると、SLO error budget を浪費する。
- **How to apply in a diff**: `server.Shutdown(ctx)`, `signal.Notify`, `atexit`, `app.on_shutdown` の使用箇所で、grace period が `terminationGracePeriodSeconds` 以下に設定されているか。
- **Failure scenario**: 1 日 10 回のデプロイで毎回 200 req の 5xx が発生、月間 60K error。SLO 99.9% を破る。
- **Source**: [Microsoft Azure — Graceful Termination](https://learn.microsoft.com/en-us/azure/spring-apps/basic-standard/how-to-configure-health-probes-graceful-termination)

### 16. 依存障害時の graceful degradation / fallback が定義されているか
- **What to look for**: cache miss / 推薦エンジン down / 検索 down など non-critical 依存が失敗したときに、機能を縮退して 200 を返す path があるか。完全に 5xx になるか。
- **Why**: critical path と non-critical path を区別せず全て fail させると、ユーザー影響が不必要に拡大。SRE Workbook も「部分機能で生き残る」設計を推奨。
- **How to apply in a diff**: 推薦・検索・パーソナライズなどの呼び出しで fallback (default 値 / cache / 空配列) が用意されているか。
- **Failure scenario**: 推薦エンジンが落ちたら EC サイト全体の商品一覧が表示できなくなり、売上が 1 時間ゼロに。fallback で「人気商品」を出していれば被害は 5% 程度で済んだ。
- **Source**: [Google SRE Book — Chapter 22: Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)

### 17. feature flag で新機能が rollback 可能になっているか
- **What to look for**: ユーザー影響のある変更 (新エンドポイント / アルゴリズム変更 / DB schema 切替) が feature flag の裏に隠されているか。flag は「default OFF」でデプロイされているか。
- **Why**: コードデプロイ単位の rollback は 5-30 分かかるが、flag toggle は数秒。MTTR を桁違いに短縮できる [10]。
- **How to apply in a diff**: 新機能の entry point に `if flag.enabled("new_feature", user):` のような分岐が無い場合、レビュアーは flag 化を提案。
- **Failure scenario**: 新ランキングアルゴリズムが本番でだけ panic 連発。デプロイ revert に 20 分、その間 100% のユーザーが影響を受ける。flag 化されていれば 30 秒で off にして影響範囲を限定できた。
- **Source**: [Honeycomb — Observability-Driven Development](https://www.honeycomb.io/blog/observability-driven-development-for-tackling-the-great-unknown)

### 18. canary / gradual rollout が考慮されているか
- **What to look for**: 大きな変更 (新依存追加・データモデル変更・性能特性変化) が一気に 100% に出ないか。1% → 10% → 50% → 100% など段階的 rollout の計画があるか。
- **Why**: 一気に 100% にすると、prod でしか出ない bug の blast radius が最大化する。canary なら 1% で異常検知して止められる [10]。
- **How to apply in a diff**: PR description に rollout plan が書かれているか、deploy config (Argo Rollouts / Flagger / LaunchDarkly target) が canary を含むか。
- **Failure scenario**: メモリリークがある変更を全 Pod に同時デプロイし、30 分後に全 Pod が OOM kill で再起動ループ。canary なら 1% で OOM が観測でき、本格 rollout 前に停止できた。
- **Source**: [Harness — Canary Releases and Feature Flags](https://www.harness.io/blog/canary-release-feature-flags)

### 19. config / 環境変数の validation が起動時に行われているか
- **What to look for**: 必須環境変数が無いときに「最初のリクエストで初めて NPE」ではなく、起動時に fail-fast しているか。値の型・範囲チェックがあるか。
- **Why**: config の不備は本番でしか露見しないことが多く、起動時 validation が無いと「デプロイ完了後しばらくして突然 5xx」となり原因特定が困難。
- **How to apply in a diff**: アプリ起動 / `main()` 直後で config struct への parse・validation が走っているか。`os.Getenv("X")` を業務ロジックの途中で呼んでいないか。
- **Failure scenario**: 新環境変数 `RETRY_MAX` を設定し忘れたまま deploy、`int("")` で panic、Pod が CrashLoopBackOff。production traffic 受け取り前に検知できれば被害ゼロだった。
- **Source**: [AWS Well-Architected — Operational Excellence Pillar](https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html)

### 20. secret / config の reload や rotation が動作中に可能か
- **What to look for**: DB password・API key が起動時のみ読み込まれて以降 reload 不能になっていないか。rotation 時に強制 restart が必要か。
- **Why**: 動的 reload が無いと、secret rotation のたびに全 Pod restart が必要となり、リスクが高まる。
- **How to apply in a diff**: secret 読み込みが viper / k8s SecretWatcher / SIGHUP 経由など、reload 可能なメカニズムを使っているか。
- **Failure scenario**: DB password rotation を実施、3 時間後に古い password を使い続けた worker が一斉に認証失敗、緊急 restart が必要に。
- **Source**: [AWS Well-Architected — Reliability Pillar](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html)

### 21. timeout / retry / rate limit が SLO と整合しているか
- **What to look for**: 上位 SLO が p99 = 500ms なのに、下流呼び出しの timeout が 30 秒になっているなど、SLO とパラメータが噛み合わない設定。retry 込みの最悪レイテンシが SLO を超えないか。
- **Why**: 下位 timeout が SLO より大きいと、SLO 違反を内側で吸収する仕組みが無い [1]。
- **How to apply in a diff**: timeout / max retry の値が PR で変更される場合、SLO ドキュメントとの整合性をレビュアーが確認。
- **Failure scenario**: timeout 30 秒で 3 回 retry すれば最悪 90 秒待つことになるが、SLO p99 = 500ms。SLO 違反を保証する設定だが PR では誰も気付かず merge。
- **Source**: [Google SRE Book — Chapter 4: Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)

### 22. 新規 alert / runbook が併せて作成されているか
- **What to look for**: 新規エラー条件・新規 SLI を追加した PR で、対応する alert ルールと runbook (playbook) が同時に更新されているか。
- **Why**: alert 無しの SLI は「異常を検知できない」、runbook 無しの alert は「鳴っても対応できない」。両方揃って初めて運用可能 [1]。
- **How to apply in a diff**: PR の changeset に Prometheus rule・Datadog monitor・runbook.md のいずれかが含まれているか。コードだけの PR で SLI 新設は flag。
- **Failure scenario**: 新メトリクスが追加されたが alert ルールが未配線、p99 が 10x になっても誰も気付かず 6 時間放置。
- **Source**: [Google SRE Book — Chapter 6: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)

### 23. 非同期処理に DLQ / 失敗時の可視化があるか
- **What to look for**: Kafka / SQS / Celery / Sidekiq などのバックグラウンドジョブで、最大リトライ超過後に dead letter queue (DLQ) に送られるか、ログ・メトリクスで失敗が観測可能か。
- **Why**: バックグラウンドジョブは silent fail しがち。DLQ と DLQ depth alert が無いと「データが反映されていない」と顧客から指摘されるまで気付けない。
- **How to apply in a diff**: queue consumer 設定で `dead_letter_queue` / `max_receive_count` が設定されているか。DLQ depth に対する alert があるか。
- **Failure scenario**: メール送信ジョブが 100% 失敗していたが retry 後 silent drop、3 日間メール未送信に気付かず CS から escalation。
- **Source**: [AWS Well-Architected — Reliability Pillar](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html)

### 24. レビュー対象の変更が観測可能 (instrument) されているか
- **What to look for**: 新規 conditional・新規エラーパス・新規 feature flag に対して、対応する log / metric / span が追加されているか。Charity Majors の「how will I know when this isn't working?」原則。
- **Why**: instrument 無しの新コードは本番で動作確認できず、勘で「動いている」と信じるしかない。ODD (observability-driven development) は instrument を test と同等の必須要件とみなす [9]。
- **How to apply in a diff**: 新規 `if` / `try/except` ブランチに対応する telemetry emit があるか。flag toggle の発火に対応するメトリクスがあるか。
- **Failure scenario**: 新しい if 分岐に入る条件が production で 0 件、または 100% 失敗していても、ログ・メトリクスが無いため誰も気付かない。
- **Source**: [Honeycomb — A Next Step Beyond Test-Driven Development](https://www.honeycomb.io/blog/a-next-step-beyond-test-driven-development2)

## Anti-patterns to avoid in review

レビュアーが指摘しがちだが、実害が小さい・他レビュアーの責務である項目。SRE レビューでは持ち込まない。

1. **ログメッセージの文言や絵文字の好み**: 「`[ERROR]` ではなく `error:` にすべき」のような bikeshed。structured logging さえ守られていれば本質ではない。
2. **既存コードとの一貫性のためだけの変更要求**: 「他のファイルでは logger.error を使っているのでこちらも合わせて」など。新規バグを生まないなら指摘しない。
3. **ビジネスロジックの正しさへの指摘**: 認可ロジックの可否・ドメイン整合性は security / domain レビュアーの責務。
4. **「いつかメトリクスが必要かもしれない」レベルの speculative instrumentation**: SLI に直結しない、観測されない metric を増やすと cost と noise が増えるだけ。
5. **過剰な防御的プログラミング**: 「念のため try/except を全関数に」は逆に context を失う。propagate して中央で扱う方が良い。
6. **lock-free / atomic 化のような micro-perf 提案**: performance レビュアーの担当。SLO に直結しない限り SRE 視点では不要。
7. **テスト網羅率の指摘**: coverage レビュアーの責務。

## Gap analysis vs current prompt

`/home/ubuntu/ai-code-review-skills/prompts/sre.md` を読み、本リファレンスとの差分を整理する。

### Already covered (prompt が既に明示している項目)
- エラーハンドリング: 握りつぶし・不適切リトライ・fallback 未定義 (本リスト #4 #6 #7 #16)
- 可観測性: log / metric / trace の有無 (本リスト #9 #11 #12 #13)
- 耐障害性: timeout / circuit breaker / graceful degradation (本リスト #1 #6 #16)
- デプロイ安全性: feature flag / canary / rollback (本リスト #17 #18)
- 「深夜3時」原則と failure_scenario フィールド

### Missing (現在の prompt に明示が無いがレビュー観点として有用)
- **Idempotency token** (本リスト #5): mutating operation の retry safety。現在 prompt は「不適切なリトライ」と曖昧。
- **Backoff + jitter** の具体パターン (本リスト #2 #3): retry 一般ではなく、jitter 無し thundering herd の検出を明示すべき。
- **エラーの context propagation / wrap** (本リスト #8): 「握りつぶし」だけでなく、wrap せず捨てている context loss も観点。
- **Correlation ID / trace_id 注入** (本リスト #10): log が出ていても correlation 無しでは追えない。
- **Metric label の cardinality** (本リスト #11): observability コストと SDK overflow 制限。
- **OTel semantic convention 準拠** (本リスト #12): 属性キー命名の標準化。
- **Liveness/readiness probe 分離** (本リスト #14): k8s 文脈で頻出するアンチパターン。
- **Graceful shutdown / in-flight 完了** (本リスト #15): デプロイ時の余計な 5xx の原因。
- **Config validation の fail-fast** (本リスト #19): 起動時検証の重要性。
- **Secret rotation 対応** (本リスト #20): 動的 reload の必要性。
- **Timeout/retry が SLO と整合** (本リスト #21): SLO とパラメータの不整合検出。
- **Alert と runbook の同時更新** (本リスト #22): code-only PR で SLI 新設を flag。
- **DLQ と非同期ジョブの可観測性** (本リスト #23): silent fail の温床。
- **ODD 観点: 新分岐に対する instrument 追加** (本リスト #24): Charity Majors の PR ゲート原則。

### Suggested additions to prompt
1. `category` に `idempotency`, `cardinality`, `config_validation`, `correlation` を追加候補として明示。
2. Task に「6. 非同期ジョブ・DLQ・config validation も対象」を追加。
3. severity 基準に「SLO error budget の浪費量」を定量例示 (例: critical = monthly budget の 10% 以上消費を起こす)。
4. Persona の判定基準として「Charity Majors の `how will I know when this isn't working?` を満たすか」を追加。

## References

1. [Google SRE Book — The Evolving SRE Engagement Model](https://sre.google/sre-book/evolving-sre-engagement-model/)
2. [Google SRE Book — Appendix E: Launch Coordination Checklist](https://sre.google/sre-book/launch-checklist/)
3. [AWS Builders' Library — Timeouts, retries and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
4. [AWS Architecture Blog — Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
5. [AWS Prescriptive Guidance — Circuit breaker pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html)
6. [AWS Well-Architected — REL04-BP04 Make mutating operations idempotent](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_prevent_interaction_failure_idempotent.html)
7. [OpenTelemetry — Logs Specification](https://opentelemetry.io/docs/specs/otel/logs/)
8. [OpenTelemetry — Trace Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/general/trace/)
9. [Honeycomb — A Next Step Beyond Test-Driven Development (Charity Majors)](https://www.honeycomb.io/blog/a-next-step-beyond-test-driven-development2)
10. [Harness — Canary Releases and Feature Flags](https://www.harness.io/blog/canary-release-feature-flags)
11. [Kubernetes — Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
12. [Google SRE Book — Chapter 4: Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)
13. [Google SRE Book — Chapter 6: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)
14. [Google SRE Book — Chapter 22: Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)
15. [AWS Builders' Library — Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
16. [AWS Well-Architected — Reliability Pillar](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html)
17. [AWS Well-Architected — Operational Excellence Pillar](https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html)
18. [Microsoft Azure — Graceful Termination for Spring Apps](https://learn.microsoft.com/en-us/azure/spring-apps/basic-standard/how-to-configure-health-probes-graceful-termination)
19. [Honeycomb — Observability-Driven Development for Tackling the Great Unknown](https://www.honeycomb.io/blog/observability-driven-development-for-tackling-the-great-unknown)
20. [Better Stack — OpenTelemetry Best Practices](https://betterstack.com/community/guides/observability/opentelemetry-best-practices/)
21. [Go Blog — Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
22. [AWS Prescriptive Guidance — Retry with backoff pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/retry-backoff.html)
