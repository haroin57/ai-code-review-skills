---
title: Performance Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://google.github.io/eng-practices/review/reviewer/standard.html
  - https://www.brendangregg.com/usemethod.html
  - https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html
  - https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside
  - https://www.postgresql.org/docs/current/using-explain.html
  - https://lmax-exchange.github.io/disruptor/disruptor.html
  - https://blog.cloudflare.com/two-weeks-later-finding-and-eliminating-long-tail-latencies/
---

# Performance Code Review Best Practices

## Why this matters

パフォーマンス問題は本番のデータ規模で初めて顕在化することが多く、コードレビュー段階で `O(n²)` ループや N+1 クエリを潰すコストは、運用段階で同じバグを潰すコストの 10〜100 分の 1 とされる [1][2]。ただし「測定なき最適化」は害悪でもあり、Google のレビュー指針も Brendan Gregg の USE 方法論も「症状ベース・根拠ベース」で判断することを求める [3][4]。本ドキュメントは diff 上で確認可能なチェック項目のみを扱い、プロファイラ実行を前提とした項目は含めない。

## Review checklist

### 1. ループ内での DB / 外部 API 呼び出し（N+1）
- **What to look for**: `for`/`forEach`/`map`/`Stream` の中で `findById`, `SELECT ... WHERE id = ?`, `fetch()`, ORM の遅延ロード（`user.posts`, `order.customer.address`）が走るパターン。Rails の `posts.each { |p| p.author.name }`、Django の `[p.author for p in posts]`、TypeORM の lazy relation。
- **Why**: 1 + N クエリで、リスト 100 件 → 101 クエリ。RTT 1ms でも合計 100ms 増。さらに DB の shared buffer を汚染し、関係ない well-indexed クエリまで遅くする副作用がある [5]。
- **How to apply in a diff**: 追加された `for`/`each`/`map` の本体に `await db.*`, `await fetch`, `repo.findOne` 系の呼び出しがあるか確認。ORM なら `.includes` / `select_related` / `prefetch_related` / `JOIN FETCH` / `with()` の同行追加があるか。
- **Quantitative impact**: 100 件 × 1ms RTT = 100ms、1000 件 × 1ms = 1s（タイムアウト圏内）。
- **Source**: [AppSignal — N+1 Queries Explained](https://blog.appsignal.com/2020/06/09/n-plus-one-queries-explained.html), [Scout — Understanding N+1 Database Queries](https://www.scoutapm.com/blog/understanding-n1-database-queries)

### 2. ホットパス上の同期 I/O / ブロッキングコール
- **What to look for**: `async def` 内の `requests.get`, `boto3`, 同期 ORM、`time.sleep`、`open()` 同期 read。Node では `readFileSync`, `execSync`, `pbkdf2Sync`, `gzipSync` 等の `Sync` サフィックス。Java の `Thread.sleep` がリクエストハンドラ内。
- **Why**: イベントループは単一スレッド。同期コール 1 つで他の全リクエストが待たされる。Node ベンチマークでは event loop delay が 15.5ms → 4744ms（約 306x）に悪化したケースあり [6]。Python の `requests` を async 関数内で呼ぶと p95 が 180ms → 1400ms に劣化した実例も [6]。
- **How to apply in a diff**: `async`/`await` を含む関数で、`await` 無しの I/O ライブラリ呼び出しを検出。`grep -E '(Sync\(|requests\.(get|post)|time\.sleep|boto3\.)' diff`。
- **Quantitative impact**: 単一ハンドラで 200ms ブロッキング → 全並行リクエストに 200ms 追加レイテンシ。RPS が 1/N に低下。
- **Source**: [FastAPI — Async/Sync guidance](https://fastapi.tiangolo.com/async/), [StackInsight — 250 Node.js Repos Blocking I/O Study](https://stackinsight.dev/blog/blocking-io-empirical-study)

### 3. 容量制限のないキュー / コレクション / キャッシュ
- **What to look for**: `Executors.newFixedThreadPool()`（内部は unbounded `LinkedBlockingQueue`）、`new LinkedBlockingQueue<>()` 引数なし、`new ArrayList<>()` に append し続け clear しない、Go の `map[K]V` への永続追加、Python の `cache = {}` を関数モジュールスコープに。
- **Why**: プロデューサがコンシューマより速いと OOM 直行。生産環境では「数日後に死ぬ」型の障害になり検知が遅れる [7]。
- **How to apply in a diff**: 新規追加のコレクション/キャッシュ/プールで、(a) サイズ上限指定、(b) 削除/eviction ロジック、(c) backpressure（block/drop/reject）戦略のいずれも無いものを検出。
- **Quantitative impact**: 1KB/msg × 100 msg/s × 24h = 8.6GB。コンテナの memory limit を超えた瞬間 OOMKill。
- **Source**: [HeapHero — Unbounded Caches Anti-pattern](https://blog.heaphero.io/unbounded-caches-static-collections-and-unclosed-resources-the-3-killer-anti-patterns-causing-memory-leaks/), [Baeldung — BlockingQueue Guide](https://www.baeldung.com/java-blocking-queue)

### 4. アルゴリズム計算量（Big-O）の悪化
- **What to look for**: ネストした for ループで両方とも入力サイズに比例（`O(n²)`）、`list.contains()` を for 内で（`O(n²)` 線形検索）、`array.unshift`/`list.insert(0, x)` をループで（`O(n²)` シフト）、毎回 sort を呼ぶ。
- **Why**: 入力規模 100 → 10,000 → 100,000 で実行時間が 10,000x 増。staging（n=100）では通るが本番（n=10⁵）でタイムアウト。
- **How to apply in a diff**: ネスト深度を見て、内側ループの境界が外側と独立か（独立なら `O(n·m)`）、依存（リスト全体探索）なら `O(n²)`。`in array` / `array.includes()` がループ内にあれば `Set`/`Map` に置換可能か検討。
- **Quantitative impact**: n=10⁴ で `O(n²) = 10⁸` ops ≒ 数秒、`O(n log n) = ~13×10⁴` ops ≒ ミリ秒。差は 1000x。
- **Source**: [Google eng-practices — Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html), [Brendan Gregg — Performance Methodology](https://www.brendangregg.com/methodology.html)

### 5. 重複計算 / メモ化漏れ
- **What to look for**: 同じ引数で同じ純粋関数を複数回呼んでいる、ループ内で正規表現を毎回コンパイル、ループ内で `JSON.parse(config)` を毎回実行、リクエストごとに証明書/設定をパース。
- **Why**: 純粋計算の繰り返しはキャッシュ可能。1 回 5ms の計算を 1000 回呼べば 5s ロス。
- **How to apply in a diff**: 新規関数で、ループ外に出せる計算がループ内にないか。`re.compile`, `new RegExp`, `JSON.parse`, `yaml.load` がホットパス内なら警告。
- **Quantitative impact**: 正規表現 1 回 100µs × 10,000 呼び出し/sec = 1s/sec の CPU。
- **Source**: [AWS Well-Architected — Performance Efficiency](https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html), [V8 Inline Caching — Mathias Bynens](https://mathiasbynens.be/notes/shapes-ics)

### 6. ネットワーク往復回数（chatty interface）
- **What to look for**: 1 リクエスト処理内で複数の独立した外部呼び出しを sequential `await` で連発（`await a(); await b(); await c();`）、SDK の単一アイテム API をループで呼ぶ（`PutItem` × 100 vs `BatchWriteItem`）。
- **Why**: 各 RTT が直列に積み重なる。AWS 内のサービス間でも 1〜5ms、リージョン間なら 50〜100ms。
- **How to apply in a diff**: 連続する `await` 同士に依存関係があるか確認。なければ `Promise.all` / `asyncio.gather` / `errgroup` に統合可能。Batch API（`BatchGetItem`, `mget`, IN 句）が利用可能なら per-item ループは flag。
- **Quantitative impact**: 5 直列呼び出し × 20ms RTT = 100ms。並列化で 20ms に短縮（5x 改善）。バッチ化で 1 RTT に圧縮可能。
- **Source**: [APIs You Won't Hate — Optimizing for the Speed of Light](https://apisyouwonthate.com/blog/optimizing-for-the-speed-of-light/), [Tyk — How to Reduce API Latency](https://tyk.io/blog/how-to-reduce-api-latency-and-optimize-your-api/)

### 7. 大きなオブジェクトのコピー / 不要なシリアライズ
- **What to look for**: `copy.deepcopy(huge_list)`, `JSON.parse(JSON.stringify(obj))`, Go での `append` による大スライスの再アロケート、Python の `list[:]` 全体スライス、Java の `new ArrayList<>(bigList)`。
- **Why**: メモリ帯域は CPU より遥かに遅い。10MB のコピーは数 ms かかり、GC 圧力も増やす。
- **How to apply in a diff**: deep copy / slice copy / serialize-deserialize ラウンドトリップが本当に必要か。read-only なら参照で十分。Go なら `make([]T, 0, cap)` で事前 capacity 指定。
- **Quantitative impact**: 100MB heap 上の deep copy = 数十 ms + GC pause。同じ処理を 1000 RPS で走らせれば CPU 飽和。
- **Source**: [Go Optimization Guide — Stack Allocations](https://goperf.dev/01-common-patterns/stack-alloc/), [Tech Edu Byte — Escape Analysis in Go](https://www.techedubyte.com/go-memory-allocation-escape-analysis-code/)

### 8. 不適切なデータ構造選択
- **What to look for**: メンバーシップ判定に `Array.includes` / `List.contains` を使う（`O(n)`）、順序が要らないのに `LinkedList`、ハッシュキー衝突が多発しそうな key 設計、Python で頻繁削除する dict（fragmentation）。
- **Why**: `Set`/`Map`/`HashSet` なら平均 `O(1)`。データ構造の選択ミスは Big-O レベルで効く。
- **How to apply in a diff**: 「`includes`/`contains` がループ内」「複数回 lookup する list」「順序不要の list」を見たら別構造を提案。
- **Quantitative impact**: n=10⁴ での containment 検査、`Set` で 10µs vs `Array` で 10ms、1000x 差。
- **Source**: [Google eng-practices](https://google.github.io/eng-practices/review/reviewer/standard.html), [V8 Hidden Classes — Mathias Bynens](https://mathiasbynens.be/notes/shapes-ics)

### 9. DB インデックス欠落 / インデックス活用阻害
- **What to look for**: 新規 `WHERE` 句のカラムに対応する index が migration に無い、`WHERE LOWER(email) = ?` のような関数適用、`WHERE date_col::text LIKE ...` の型変換、複合 index の leading column 違反（`(a,b)` の index で `WHERE b=?` だけ問い合わせ）。
- **Why**: PostgreSQL の planner は selectivity と統計に基づき seq scan を選ぶ。関数適用や型変換は index を無効化する。staging では小さくて気付かないが、本番テーブルが 10⁷ 行になった瞬間死ぬ [5][8]。
- **How to apply in a diff**: 追加された SQL/ORM クエリの `WHERE`, `ORDER BY`, `JOIN ON` を抽出し、対応する migration の `CREATE INDEX` を確認。`EXPLAIN` 結果を PR description に貼ることを要求。
- **Quantitative impact**: 10⁶ 行に対する seq scan は 100ms〜数秒、b-tree index scan なら sub-ms。差は 1000x 以上。
- **Source**: [PostgreSQL Docs — Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html), [pgMustard — Why isn't Postgres using my index](https://www.pgmustard.com/blog/why-isnt-postgres-using-my-index)

### 10. トランザクション境界 / ロック保持時間
- **What to look for**: `BEGIN ... COMMIT` の中に外部 HTTP 呼び出しがある、ロック取得後に重い計算、`SELECT ... FOR UPDATE` した行への long-running 操作、Java の `synchronized` ブロック内で I/O。
- **Why**: ロック保持中は他のリクエストが待たされ、スループットが直列化する。100ms の lock × 100 RPS = キュー爆発。
- **How to apply in a diff**: トランザクション/ロックスコープを最小化する原則。I/O、ネットワーク呼び出し、ユーザ入力待ちが lock 内にあれば critical。
- **Quantitative impact**: 50ms 保持 × 50 concurrent users = 全員 50ms 待たされる。スループット ceiling = 1/lock_time。
- **Source**: [Martin Thompson — Mechanical Sympathy: Single Writer Principle](https://mechanical-sympathy.blogspot.com/), [Baeldung — JDBC Connection Pool Best Practices](https://www.baeldung.com/java-best-practices-jdbc-connection-pool)

### 11. False sharing / キャッシュライン競合（高並行コード）
- **What to look for**: 同一構造体内で複数スレッドが書き込む隣接フィールド（カウンタ、stats）。Java の `volatile long a, b;`、Go の隣接 `atomic.Int64`、C/C++ の隣接 `std::atomic`。
- **Why**: 64-byte cache line を共有する変数への書き込みは、別変数でも cache coherency で競合し、性能が桁違いに落ちる。Disruptor では padding で 25M msg/s を実現 [9]。
- **How to apply in a diff**: 高並行データ構造（lock-free queue, counter, stats）でフィールド配置を確認。Go なら `_ [CacheLinePad]byte` 等の padding、Java なら `@Contended`。
- **Quantitative impact**: padding なしで 10x の throughput 低下が一般的（LMAX 計測例）。
- **Source**: [Martin Thompson — False Sharing](https://mechanical-sympathy.blogspot.com/2011/07/false-sharing.html), [LMAX Disruptor Paper](https://lmax-exchange.github.io/disruptor/disruptor.html)

### 12. キャッシュ戦略の欠落 / 不適切な TTL
- **What to look for**: 同一データに対し毎リクエスト DB を引いている、TTL 無しキャッシュ（stale 永続化）、キャッシュキーに user-controllable な値を含めて爆発、cache stampede 対策なし（lock/single-flight 無し）。
- **Why**: cache miss を全並行リクエストが同時に踏むと DB に thundering herd。TTL なしは memory leak の温床。
- **How to apply in a diff**: 新規キャッシュ追加時に (a) TTL or eviction、(b) invalidation 戦略、(c) stampede protection、(d) cache 障害時の fallback、をレビュー。
- **Quantitative impact**: キャッシュヒット率 95% → 90% で DB 負荷が 2x に。stampede 時は瞬間的に 100x。
- **Source**: [Azure — Cache-Aside Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside), [AWS — Database Caching Strategies](https://docs.aws.amazon.com/whitepapers/latest/database-caching-strategies-using-redis/caching-patterns.html)

### 13. コネクションプール設定 / リソースリーク
- **What to look for**: pool size がデフォルト（往々にして小さい/大きすぎる）、`try-finally` や context manager で connection が必ず返却されているか、acquire timeout 設定、SELECT が長時間プールを占有していないか。
- **Why**: 過小だとリクエストがキューイングで待たされ p99 悪化、過大だと DB 側で context switching コスト。Pool exhaustion はカスケード障害になる [10]。サイズ目安: `connections = (2 * core_count) + number_of_disks` [10]。
- **How to apply in a diff**: 新規コネクション使用箇所で `defer conn.Close()` / `try-with-resources` / `async with` の有無、pool config 変更ならサイズ根拠と timeout 設定。
- **Quantitative impact**: pool size 5 vs 50 で 1000 RPS 時の待ち時間が秒オーダーで変動。
- **Source**: [Microsoft — SQL Server Connection Pooling](https://learn.microsoft.com/en-us/dotnet/framework/data/adonet/sql-server-connection-pooling), [Baeldung — JDBC Connection Pool Sizing](https://www.baeldung.com/java-best-practices-jdbc-connection-pool)

### 14. ペイロードサイズ / オーバーフェッチ
- **What to look for**: `SELECT *` で 50 カラム取得して 2 つしか使わない、API レスポンスに不要なフィールド、GraphQL で巨大な nested query、画像/動画を base64 で JSON に埋め込み。
- **Why**: ネットワーク帯域、シリアライズ CPU、クライアント側パース時間が全部増える。モバイル環境では特に効く。
- **How to apply in a diff**: `SELECT *` を flag、API 応答スキーマに新規追加された大きいフィールド（blob, 配列）はオプトイン化できないか提案。
- **Quantitative impact**: 1KB → 10KB レスポンスで p99 が 50ms 程度劣化（モバイル 3G 環境）。
- **Source**: [AWS Well-Architected — Network Selection](https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html), [Cloudflare — Tail Latency](https://blog.cloudflare.com/two-weeks-later-finding-and-eliminating-long-tail-latencies/)

### 15. 不要な heap allocation / GC 圧力（管理言語）
- **What to look for**: Go でホットループ内の `fmt.Sprintf`, `interface{}` への boxing、closure による escape、Java の autoboxing（`Long` vs `long`）、JS でホットパスのオブジェクト形状変更（`obj.newProp = ...`）による hidden class 変更。
- **Why**: heap allocation は GC pause を引き起こし tail latency を悪化させる。Go の escape analysis、V8 の hidden class が破壊されると最適化が崩れる [11][12]。
- **How to apply in a diff**: ホットパスのコードで `interface{}`, `Sprintf`, 大 struct の pointer return、JS で object literal にあとから property を追加する記述を flag。
- **Quantitative impact**: JSON microservice で `interface{}` 排除によりアロケーション 25% 減・レイテンシ 50µs → 40µs（20% 改善）の実例 [11]。
- **Source**: [Go Optimization Guide — Stack Allocations](https://goperf.dev/01-common-patterns/stack-alloc/), [V8 Hidden Classes — Mathias Bynens](https://mathiasbynens.be/notes/shapes-ics)

### 16. タイムアウト / リトライの欠落・暴走
- **What to look for**: HTTP クライアント呼び出しに timeout が指定されていない（デフォルト無限大が多い）、リトライが exponential backoff 無し、retry count に上限なし、circuit breaker 無し。
- **Why**: 下流が遅延した瞬間、上流のスレッド/コネクションが全部占有されて雪崩。リトライ嵐は障害を増幅させる。
- **How to apply in a diff**: 新規外部呼び出しで client timeout / retry policy / circuit breaker の有無を確認。`requests.get(url)`（timeout 無し）、`fetch(url)`（デフォルトタイムアウト無し）は critical。
- **Quantitative impact**: 下流 5s 遅延 + timeout 無しで、上流の pool が数秒で枯渇しカスケード障害。
- **Source**: [Cloudflare — Story of One Latency Spike](https://blog.cloudflare.com/the-story-of-one-latency-spike/), [AWS Well-Architected — Performance Efficiency](https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html)

### 17. 大量データの全件メモリロード
- **What to look for**: `users = User.all()` で全件 in-memory、CSV 全行を `lines = f.readlines()`、巨大 JSON を `json.load(f)`、`SELECT * FROM table` をページネーションなしで取得。
- **Why**: 入力サイズに比例してメモリが線形に伸びる。10⁷ 行 × 1KB = 10GB、OOM 直行。
- **How to apply in a diff**: 一括取得 → ストリーミング/ページネーション（`cursor`, `iterator`, `LIMIT/OFFSET`, keyset pagination）を提案。
- **Quantitative impact**: 1M レコード × 1KB = 1GB heap、staging（1K records）では問題なし、本番で死ぬ典型例。
- **Source**: [PostgreSQL — Cursor / Pagination](https://www.postgresql.org/docs/current/queries-limit.html), [AWS Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html)

### 18. tail latency 観点の欠落（p50 だけ見る誤り）
- **What to look for**: ベンチマーク/SLO が average や p50 のみで定義されている、新規 metric が `avg_latency_ms`、ヒストグラム/percentile が無い。
- **Why**: 平均は外れ値を隠す。p99/p999 がユーザ体験を決める。Cloudflare の検証では「平均 70ms 速い」が他社比較で見えるのは raw data があってこそ [13]。
- **How to apply in a diff**: 新規 metrics 定義で histogram/summary 形式を要求。SLO ドキュメントで「avg」しか無ければ p95/p99 を必須化。
- **Quantitative impact**: p50=50ms, p99=2000ms のサービスは「平均良好」だが 1% のユーザが 2 秒待つ。
- **Source**: [Cloudflare — Performance Measurements](https://blog.cloudflare.com/loving-performance-measurements/), [RED Method — Tom Wilkie / Grafana](https://www.infoworld.com/article/2270578/the-red-method-a-new-strategy-for-monitoring-microservices.html)

### 19. 観測可能性の欠落（RED/USE が取れない実装）
- **What to look for**: 新規エンドポイント/ワーカーで Rate/Errors/Duration（RED）が出ない、新規リソース利用（thread pool, queue）で Utilization/Saturation/Errors（USE）が出ない。
- **Why**: 計測できないものは最適化できない。本番障害時の MTTR が桁違いに伸びる。
- **How to apply in a diff**: 新規サービス/ハンドラ追加時に metrics 出力（counter, histogram）の有無、queue 系は `queue_length`, `queue_wait_seconds` の出力を要求。
- **Quantitative impact**: 観測なしの障害は原因特定に数時間〜数日、観測ありなら数分。
- **Source**: [Brendan Gregg — USE Method](https://www.brendangregg.com/usemethod.html), [InfoWorld — RED Method](https://www.infoworld.com/article/2270578/the-red-method-a-new-strategy-for-monitoring-microservices.html)

### 20. ロック粒度の粗さ / グローバル mutex
- **What to look for**: グローバル mutex で広範な処理を保護、`synchronized` メソッド全体（細粒度化可能でないか）、Python の GIL を意識しない CPU bound 処理を `threading` で並列化（実は直列）、Go の sync.Mutex を struct 全体に。
- **Why**: ロック競合はスレッドのスケーラビリティ上限を決める。Amdahl の法則：直列部分 5% でも 20 コアで頭打ち。
- **How to apply in a diff**: 新規 mutex/lock 追加時に、保護範囲が必要最小か、shard 可能（per-key lock, sync.Map）か、atomic 操作で代替可能かをレビュー。
- **Quantitative impact**: グローバル lock = 1 core 分のスループットしか出ない。fine-grained で N コア分にスケール。
- **Source**: [Martin Thompson — Single Writer Principle](https://mechanical-sympathy.blogspot.com/), [Brendan Gregg — USE Method (locks as resource)](https://www.brendangregg.com/usemethod.html)

## Anti-patterns to avoid in review

レビュアーが over-flag しがちで、生産性を下げるだけの指摘：

1. **ホットパスでない箇所のマイクロ最適化**: `i++ vs ++i`、StringBuilder の容量 hint、初期化処理での `Sprintf`。本番で 1 回しか呼ばれないコードを最適化しても意味がない。Google ガイドラインも「改善は連続的、完璧でなくてよい」を強調 [3]。
2. **ベンチマーク無しの「遅そう」**: 「ここはハッシュマップの方が速いと思います」は数値根拠が無ければ noise。実測 or Big-O 分析を要求する。
3. **可読性を犠牲にする最適化**: ループ展開、bit trick、変数の reuse による寿命圧縮。コンパイラ/JIT がやる仕事を人間がやると保守性が落ちる。
4. **早すぎる並列化**: `Promise.all` を闇雲に。並列度を上げると下流（DB, API）に負荷が集中し全体としては悪化することがある。
5. **「とりあえずキャッシュ」**: invalidation 戦略無しのキャッシュは memory leak + 整合性バグの温床。read traffic が低い場合キャッシュは害の方が大きい。
6. **ベンチでしか速い最適化**: micro benchmark が分岐予測やキャッシュ温度の影響で実態と乖離する。JMH 等の正しいツールを使っているか確認。
7. **言語機能だけで判断（"Go の defer は遅い"）**: 2026 時点では多くは過去の話。最新版のベンチマークが無ければ flag しない。

## Gap analysis vs current prompt

`/home/ubuntu/ai-code-review-skills/prompts/performance.md` との対照。

### 既にカバー済み
- N+1（item 1）— prompt の Task 1 と一致
- メモリ allocation（item 7, 15）— prompt の Task 2
- 計算量（item 4, 8）— prompt の Task 3
- キャッシュ可能な計算の繰り返し（item 5, 12）— prompt の Task 4
- ホットパス判定基準 — prompt の「やるな」セクションで明示済み
- ベンチマーク無し推測の禁止 — prompt で明示済み

### 不足項目（prompt 追加候補）
- **同期 I/O / ブロッキング検出（item 2）**: 現 prompt の category `io` を細分化し、`blocking_io` を追加すべき
- **unbounded コレクション（item 3）**: critical 級で OOM につながるが prompt のカテゴリに無い → `unbounded` カテゴリ追加
- **ネットワーク往復回数（item 6）**: N+1 と区別される独立トピック → `chatty_interface` カテゴリ
- **DB インデックス欠落（item 9）**: 現 prompt は N+1 中心で index 観点が弱い → `db_index` カテゴリ追加、または diff に migration を含めることを要求
- **トランザクション/ロック保持（item 10, 20）**: 並行性パフォーマンスが現 prompt に無い → `contention` カテゴリ
- **タイムアウト/リトライ（item 16）**: 信頼性とパフォーマンスの境界だが、cascading failure 経由の性能影響として明示すべき
- **ペイロードサイズ（item 14）**: シリアライズコスト・帯域として独立項目に
- **tail latency 観点（item 18）**: severity 判定で「p99 影響」を critical 基準に追加

### Prompt への具体的追加提案
1. `<category>` enum に `blocking_io`, `unbounded`, `chatty_interface`, `db_index`, `contention`, `payload_size` を追加
2. severity 基準に「p99 / tail latency への影響有無」を明示
3. Task に「5. 同期 I/O がホットパスにないか」「6. リソース（コネクション、メモリ、ロック）に上限・タイムアウトがあるか」を追加
4. ホットパス判定の補助として「リクエストハンドラ / イベントループ / GC 走るパス」を `is_hot_path` の判定材料として明示

## References

1. [Jellyfish — Peer Code Review Best Practices](https://jellyfish.co/library/developer-productivity/peer-code-review-best-practices/)
2. [IBM research on defect cost (via 42 Coffee Cups summary)](https://www.42coffeecups.com/blog/code-review-best-practices)
3. [Google eng-practices — The Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html)
4. [Brendan Gregg — The USE Method](https://www.brendangregg.com/usemethod.html)
5. [Mergify — Why PostgreSQL Ignored Our Index](https://mergify.com/blog/why-postgresql-ignored-our-index-(and-what-the-planner-was-thinking))
6. [StackInsight — Blocking I/O Empirical Study (Node.js)](https://stackinsight.dev/blog/blocking-io-empirical-study)
7. [HeapHero — 3 Anti-Patterns Causing Java Memory Leaks](https://blog.heaphero.io/unbounded-caches-static-collections-and-unclosed-resources-the-3-killer-anti-patterns-causing-memory-leaks/)
8. [PostgreSQL Docs — Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
9. [LMAX Disruptor Technical Paper](https://lmax-exchange.github.io/disruptor/disruptor.html)
10. [Baeldung — Sizing the JDBC Connection Pool](https://www.baeldung.com/java-best-practices-jdbc-connection-pool)
11. [Go Optimization Guide — Stack Allocations and Escape Analysis](https://goperf.dev/01-common-patterns/stack-alloc/)
12. [Mathias Bynens — JavaScript Engine Fundamentals: Shapes and Inline Caches](https://mathiasbynens.be/notes/shapes-ics)
13. [Cloudflare — Two Weeks Later: Finding and Eliminating Long Tail Latencies](https://blog.cloudflare.com/two-weeks-later-finding-and-eliminating-long-tail-latencies/)
14. [Cloudflare — Performance Measurements and the People Who Love Them](https://blog.cloudflare.com/loving-performance-measurements/)
15. [Microsoft Azure — Cache-Aside Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
16. [AWS Well-Architected Framework — Performance Efficiency Pillar](https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html)
17. [AWS — Database Caching Strategies Using Redis](https://docs.aws.amazon.com/whitepapers/latest/database-caching-strategies-using-redis/caching-patterns.html)
18. [Martin Thompson — Mechanical Sympathy: False Sharing](https://mechanical-sympathy.blogspot.com/2011/07/false-sharing.html)
19. [Martin Fowler — Principles of Mechanical Sympathy](https://martinfowler.com/articles/mechanical-sympathy-principles.html)
20. [FastAPI — Concurrency and async/await](https://fastapi.tiangolo.com/async/)
21. [AppSignal — Performance and N+1 Queries Explained](https://blog.appsignal.com/2020/06/09/n-plus-one-queries-explained.html)
22. [Scout APM — Understanding N+1 Database Queries](https://www.scoutapm.com/blog/understanding-n1-database-queries)
23. [pgMustard — Why Isn't Postgres Using My Index?](https://www.pgmustard.com/blog/why-isnt-postgres-using-my-index)
24. [pganalyze — Deconstructing the Postgres Planner](https://pganalyze.com/blog/deconstructing-the-postgres-planner)
25. [Baeldung — Guide to BlockingQueue](https://www.baeldung.com/java-blocking-queue)
26. [Microsoft Docs — SQL Server Connection Pooling](https://learn.microsoft.com/en-us/dotnet/framework/data/adonet/sql-server-connection-pooling)
27. [InfoWorld — The RED Method: A New Strategy for Monitoring Microservices](https://www.infoworld.com/article/2270578/the-red-method-a-new-strategy-for-monitoring-microservices.html)
28. [APIs You Won't Hate — Optimizing for the Speed of Light](https://apisyouwonthate.com/blog/optimizing-for-the-speed-of-light/)
29. [Tyk — How to Reduce API Latency and Optimize Your API](https://tyk.io/blog/how-to-reduce-api-latency-and-optimize-your-api/)
30. [Cloudflare — The Story of One Latency Spike](https://blog.cloudflare.com/the-story-of-one-latency-spike/)
