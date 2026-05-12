---
title: API Contract / Backward-Compat Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://google.aip.dev/180
  - https://google.aip.dev/185
  - https://semver.org/
  - https://stripe.com/blog/api-versioning
  - https://stripe.com/blog/idempotency
  - https://opensource.zalando.com/restful-api-guidelines/
  - https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md
  - https://protobuf.dev/programming-guides/proto3/
  - https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html
  - https://graphql.org/learn/schema-design/
  - https://www.apollographql.com/docs/graphos/schema-design/guides/nullability
  - https://datatracker.ietf.org/doc/html/rfc9110
  - https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
  - https://www.rfc-editor.org/rfc/rfc7807
  - https://martinfowler.com/bliki/StranglerFigApplication.html
---

# API Contract Code Review Best Practices

## Why this matters

API契約は「動いている顧客コード」との約束。破ったら客が壊れる、それだけ。
Google AIP-180は明快に書いている: 「APIは本質的にユーザーとの契約であり、ユーザーはそれが動き続けることを前提に本番サービスを書いている。何が後方互換で何がそうでないかを理解することが重要」([AIP-180](https://google.aip.dev/180))。

そして **Hyrum's Law**: 「APIに十分な数のユーザーがいれば、契約で約束したことなど関係なく、観測可能な挙動の全てが誰かに依存される」(https://www.hyrumslaw.com/)。
つまり「ドキュメントに書いてないから壊していい」は通用しない。フィールド順序、エラー文言の細部、ペイロードに含まれない undocumented field — 全部が依存される可能性がある。

破壊的変更のコスト構造:

- **モバイル/組み込みクライアント**: App Store / Play Store経由で更新されるので、ユーザー側の更新は数週間〜数ヶ月遅れる。サーバ側の破壊的変更は古いアプリを即死させる ([Stellarcode 2026](https://stellarcode.io/blog/advanced-api-development-best-practices-2026/))。
- **外部パートナー**: 業務システムは日次デプロイしない。承認サイクル、テストウィンドウ、レガシー連携で数日〜数週間ブロックされる。
- **SDK/ライブラリの推移的依存**: 1階層のbreaking changeが、下流の全ライブラリのメジャー版上げを要求する (semver diamond dependency hell)。
- **DBスキーマ**: 一度本番に流れた行は取り戻せない。NULL backfill不足や型変換失敗は dataloss に直結する。

レビュー観点: **diffを見て「これは on-the-wire / on-disk / on-stack の契約を変えるか?」を常に問う。**
変えるなら、(a) deprecate-then-remove などの移行パスがあるか、(b) semver/APIバージョンが正しく上がっているか、(c) 既存クライアントへの周知が組み込まれているか — この3点を確認する。

---

## Review checklist

### 1. Removed field / endpoint / method

- **What to look for**: response schemaから field消失、endpoint削除、protoの `message`/`rpc` 削除、GraphQL `type`/`field` 削除、SDK public関数の削除。
- **Why**: 既存クライアントが当該fieldを参照していれば即座にruntime error or null参照。AIP-180は明確に「既存のinterfaces/methods/messages/fields/enums/enum valuesを同じmajor versionから削除してはいけない」と禁じている。
- **How to apply in a diff**: `openapi.yaml`、`*.proto`、`schema.graphql`、`*.thrift`、`v1/` 配下のpublic SDKモジュールでの削除行に注目。`git log -p -- '*.proto' | grep '^-.*='` のような検索でtag削除を機械的に拾える。
- **Migration path suggestion**: (1) フィールドに `deprecated = true` を付け、ドキュメントとchangelogに猶予期間を明記。(2) クライアントテレメトリで利用が0になるのを待つ。(3) protoなら `reserved` 化、HTTPなら新major version (`/v2`) に持っていって `/v1` で残す。
- **Source**: [AIP-180 Backwards Compatibility](https://google.aip.dev/180)、[Stripe API versioning](https://stripe.com/blog/api-versioning)

### 2. Renamed field / endpoint / parameter

- **What to look for**: 同じfield numberで `name` だけ変わる proto変更、JSONキー名の変更 (`userName` → `user_name`)、URLパス変更 (`/orders` → `/transactions`)、関数引数名の変更 (kwargsで呼ぶクライアントが壊れる)。
- **Why**: AIP-180は「リネームはremove+addと意味的に等価」と定義。JSONシリアライゼーションを使うprotobufでは、フィールド名も予約しないと再利用で型不整合が起きる ([protobuf compatibility](https://yokota.blog/2021/08/26/understanding-protobuf-compatibility/))。
- **How to apply in a diff**: `git log -p` のrename heuristic に頼らず、`-` と `+` を別々の変更として扱う。OpenAPI diffツール ([oasdiff](https://github.com/Tufin/oasdiff)) はrenameをremove+addとして検出する。
- **Migration path suggestion**: 旧名と新名を両方exposeし、旧名を `deprecated` 化。両方への書き込みを並走させ、観測期間後に旧名を削除。
- **Source**: [AIP-180](https://google.aip.dev/180)、[Earthly: Protobuf forward/backward compatibility](https://earthly.dev/blog/backward-and-forward-compatibility/)

### 3. Type narrowing (int64→int32, string→enum, any→specific)

- **What to look for**: protoで `int64 → int32`、JSON schemaで `string → string with pattern`、SDKの型シグネチャで `Optional[T] → T` や `Union[A, B] → A`。
- **Why**: より狭い型はより少ない値しか受け取れない。古いクライアントが送る合法な値が新サーバで弾かれる、逆方向では新サーバが返す値を古いクライアントがパースできない。protobufは「フィールド型変更はワイヤ互換でも生成コードのbreaking changeになる」と明示 ([protobuf docs](https://protobuf.dev/programming-guides/proto3/#updating))。
- **How to apply in a diff**: schema定義 (`*.proto`、OpenAPI `type:`/`format:`、JSON Schema)、型注釈付き言語の public関数シグネチャ。Buf breaking check (`buf breaking`) で機械的に検出可能。
- **Migration path suggestion**: 新型を新フィールド (新tag) として追加、旧フィールドは deprecate。`buf` をCIで強制。
- **Source**: [Protobuf updating messages](https://protobuf.dev/programming-guides/proto3/#updating)、[Buf breaking change detection](https://buf.build/docs/breaking/overview)

### 4. Optional → Required (required field addition)

- **What to look for**: OpenAPIの `required: [...]` に新field追加、GraphQL inputで `String` → `String!`、SQL列に `NOT NULL` 追加 (default無しで)、関数引数のdefault値削除。
- **Why**: 古いクライアントは新requiredフィールドを送らないので400/validation errorになる。GraphQLでは「nullable input → non-null input は破壊的変更」が明確なルール ([Apollo Nullability](https://www.apollographql.com/docs/graphos/schema-design/guides/nullability))。Zalandoは「optional fieldのみ追加、mandatory fieldは絶対追加しない」を明文化している ([Zalando guideline](https://opensource.zalando.com/restful-api-guidelines/))。
- **How to apply in a diff**: OpenAPIの `required` 配列の追加行、`*.graphql` の `!` 追加、Pydantic / Zod の Optional → required変更。
- **Migration path suggestion**: 新fieldはoptional + sensible default で導入。テレメトリで「全クライアントが送るようになった」を確認後、majorバージョン昇格でrequired化。
- **Source**: [Apollo: Nullability](https://www.apollographql.com/docs/graphos/schema-design/guides/nullability)、[Zalando RESTful API Guidelines](https://opensource.zalando.com/restful-api-guidelines/)

### 5. Required → Optional (output field nullability widening)

- **What to look for**: GraphQL output型で `String!` → `String`、protoで `required` だったフィールド (proto2) の `optional`/`reserved` 化、レスポンス型の `T` → `Optional[T]`。
- **Why**: クライアントは「このfieldは絶対あるはず」と仮定してnullチェック無しでアクセスしている。Apollo: 「output positionをnon-nullableからnullableに変えるのはbreaking change。クライアントはnull処理コードを持たない」。
- **How to apply in a diff**: response型定義、GraphQL schema、TypeScript/Kotlinなどの strict null checking言語のmodel定義。
- **Migration path suggestion**: 完全nullableにせず、`""` や `0` などのzero値を返すことで「不存在」を表現できないか検討。本当にnullableにする場合は major version で。
- **Source**: [Apollo Nullability](https://www.apollographql.com/docs/graphos/schema-design/guides/nullability)、[graphql.org Schema Design](https://graphql.org/learn/schema-design/)

### 6. Default value change

- **What to look for**: protoで `int32 retry_count = 5 [default = 3]` → `[default = 5]`、関数引数の `timeout: int = 30` → `60`、SQL列のDEFAULT変更。
- **Why**: 「クライアントは省略 = 旧default」と思って送信、サーバ側は新defaultで処理 → 観測可能な動作変化。protobuf 3はdefaultをワイヤに乗せないので、`absent value のserialization変更はminor versionで起こしてはならない` (AIP-180)。
- **How to apply in a diff**: `default =`、`= field(default=...)`、`DEFAULT` SQL構文、関数引数のdefault式。
- **Migration path suggestion**: defaultの意味的な変更は新フィールド or 新endpoint で行う。既存fieldのdefaultは原則固定。どうしても変えるならchangelogで「動作変更」として周知。
- **Source**: [AIP-180](https://google.aip.dev/180)

### 7. Enum value added (without UNSPECIFIED / unknown handling guidance)

- **What to look for**: `enum Status { ACTIVE, INACTIVE }` に `SUSPENDED` 追加。protoで `STATUS_UNSPECIFIED = 0` が無いまま値追加。GraphQL enumへの追加。
- **Why**: protobufは未知enum値を保持できる (open enum) が、JSONベースAPIではクライアントが `enum_value not in known_set` で例外を投げる実装が多い。GraphQLは仕様上「クライアントが知らないenum値は受け取れる必要がある」が、実際のクライアントsdk生成コードがswitch網羅性チェックでcompile errorになる。
- **How to apply in a diff**: `*.proto` `enum {...}`、`*.graphql` `enum {...}`、OpenAPI `enum: [...]`、TypeScriptの string union literal。
- **Migration path suggestion**: クライアントSDKのリリースノートに「unknown enum値はforward-compat処理せよ」と明記。pre-existingのswagger codegenクライアントは大抵壊れるので、major bumpを検討。
- **Source**: [Protobuf: Reserved values for enums](https://protobuf.dev/programming-guides/proto3/#reserved)、[Earthly: Backward and Forward Compatibility](https://earthly.dev/blog/backward-and-forward-compatibility/)

### 8. Enum value removed / renamed

- **What to look for**: enumから値が消えた、または名前変更。protoの `enum` での値削除に `reserved` が伴っていない。
- **Why**: 古いクライアントが送る既存の合法enum値を新サーバが拒否する。protobufでは `reserved 2; reserved "DEPRECATED";` の両方が必要 (JSON serializationを使っている場合)。
- **How to apply in a diff**: enum定義から `-` 行、`reserved` 行が同時に追加されているかを確認。
- **Migration path suggestion**: 値はdeprecate表示のまま残し、新サーバは「受け取ったらignoreまたはmapping」する。完全削除は major で。
- **Source**: [Protobuf Reserved](https://protobuf.dev/programming-guides/proto3/#reserved)、[AIP-180](https://google.aip.dev/180)

### 9. Error response shape change

- **What to look for**: `{error: {code, message}}` → `{detail, title}` のような外側構造変更、`code` の値域変更 (HTTPコード数値 → 文字列スラッグ)、Microsoft標準 `{error: {code, message, target, details, innererror}}` から逸脱。
- **Why**: クライアントは大抵 `response.error.code === "INVALID_ARGUMENT"` のような硬いマッチングをしている。RFC 7807 `application/problem+json` への切り替えも、既存クライアントから見れば破壊的。Microsoftの設計指針は「全エラーレスポンスに統一形式を採用し、developerが1つのコードでハンドリングできるようにする」。
- **How to apply in a diff**: error response schema、例外→HTTPマッピングコード、エラーミドルウェアのレスポンスシリアライザ。
- **Migration path suggestion**: 新エラー形式は新major versionで。同一major内では旧形式を返し続け、追加情報は新フィールド (例: `error.trace_id`) で。
- **Source**: [Microsoft REST API Guidelines: errorResponses](https://github.com/microsoft/api-guidelines/blob/vNext/graph/articles/errorResponses.md)、[RFC 7807 Problem Details](https://www.rfc-editor.org/rfc/rfc7807)

### 10. Error code added / removed / semantic shift

- **What to look for**: `INVALID_ARGUMENT` を返していた条件が `FAILED_PRECONDITION` に変わる、新エラーコード追加でクライアントの `default:` 分岐に流れる、HTTP 400 → 422の変更。
- **Why**: クライアントのretry/UI分岐は error code 値に依存する。コードを変えるとretry policy (4xx は再試行しない、5xxはする) が破綻する。
- **How to apply in a diff**: 例外クラス → HTTPコード変換テーブル、`raise ValidationError` → `raise PreconditionFailed` の変更、gRPC `status.Code` 変更。
- **Migration path suggestion**: 既存条件は既存コードを返し続ける。新たな失敗ケースのみ新コードに割り当てる。
- **Source**: [Microsoft REST API Guidelines errorResponses](https://github.com/microsoft/api-guidelines/blob/vNext/graph/articles/errorResponses.md)、[Google AIP-193 Errors](https://google.aip.dev/193)

### 11. HTTP status code semantic change

- **What to look for**: 同じエンドポイントの正常系が `200 OK` → `202 Accepted` (同期 → 非同期化)、または `201 Created` → `200 OK`、`204 No Content` → `200 OK + empty body`、`404` → `403` のような認可意味の変化。
- **Why**: RFC 9110は2xxの細分化に明確な意味を与えている: 202は「受け付けたが未完了」で、その後ステータスをポーリングする責務がクライアント側に発生する。200を返していたエンドポイントを202化すると「同期で結果が返ってきている前提のクライアント」が空レスポンスを受け取って壊れる。
- **How to apply in a diff**: `return Response(status=...)`、`@ResponseStatus(...)` アノテーション、router設定。OpenAPIの `responses:` セクション。
- **Migration path suggestion**: 非同期化が必要な場合は新エンドポイント (`POST /orders` の隣に `POST /orders:async`) を切る。元エンドポイントは同期動作のまま。
- **Source**: [RFC 9110 §15.3 Successful 2xx](https://datatracker.ietf.org/doc/html/rfc9110#section-15.3)、[Zalando guideline](https://opensource.zalando.com/restful-api-guidelines/)

### 12. Pagination semantics change

- **What to look for**: offset-based → cursor-based、`page=1&size=20` → `cursor=...&limit=20`、デフォルト並び順の変更、`total_count` フィールドの消失。
- **Why**: クライアントは「ページ番号で全件巡回」「件数表示UI」を硬くコードしている。Zalandoはcursor-basedを推奨するが、既存offset APIをcursor化するのは破壊的。デフォルトソート順を変えると「最新N件取得」ロジックが壊れる。
- **How to apply in a diff**: `LIMIT/OFFSET` クエリビルダ、cursor encoding/decoding コード、response型の `total`/`next_cursor`/`page` フィールド。
- **Migration path suggestion**: 新方式は新query parameterで opt-in。古いparameterは引き続きサポート。ソート順の安定性 (ULID + secondary sort)を保証。
- **Source**: [Zalando Pagination](https://opensource.zalando.com/restful-api-guidelines/#pagination)、[Google AIP-158 Pagination](https://google.aip.dev/158)

### 13. Filter / sort / search parameter semantic change

- **What to look for**: `?status=active` の match semantics変更 (exact → prefix)、`?q=foo` の検索アルゴリズム変更 (substring → full-text)、フィルタの組み合わせ意味変更 (AND → OR)。
- **Why**: 観測可能な動作 = Hyrum's Law対象。検索結果件数が変わるだけでもクライアントのUIに影響、テストが落ちる。
- **How to apply in a diff**: SQLクエリビルダ、search engine query構築コード、`WHERE` 句の演算子変更。
- **Migration path suggestion**: 新semantic は新parameter名 (例: `?status_exact=...` `?status_prefix=...`) で導入。
- **Source**: [Google AIP-160 Filtering](https://google.aip.dev/160)、[Hyrum's Law](https://www.hyrumslaw.com/)

### 14. Idempotency-key semantics change

- **What to look for**: Idempotency-Keyの有効期限変更 (24h → 1h)、key衝突時の挙動変更 (replay → reject)、対応メソッドの変更 (POST only → POST/PUT両方)、key必須化。
- **Why**: Stripeは「Idempotency-Keyは24時間保持、再送で同じレスポンス (status code + body) を返す」と明文化。これに依存している決済リトライロジックが壊れると二重課金 or 失敗扱いになる。
- **How to apply in a diff**: idempotency middleware、key storage TTL設定、key validation logic。
- **Migration path suggestion**: 動作変更は major versionで。短くするのは特に危険 (古いクライアントのretry windowが短くなる)。
- **Source**: [Stripe: Idempotent requests](https://docs.stripe.com/api/idempotent_requests)、[Stripe blog: Idempotency](https://stripe.com/blog/idempotency)

### 15. Rate-limit header change

- **What to look for**: `X-RateLimit-Remaining` 削除、`Retry-After` の単位変更 (秒 → ミリ秒)、IETFドラフト準拠の `RateLimit` / `RateLimit-Policy` フィールドへの突然の切り替え、レート上限値の引き下げ。
- **Why**: クライアントのバックオフロジックはこれらヘッダに依存。単位を変えると指数バックオフが破綻し、リクエストが詰まる。上限引き下げは「契約上の rate budget」を狭めるので顧客への事前通知が必要。
- **How to apply in a diff**: response middleware、rate limit設定ファイル、`Retry-After` 計算ロジック。
- **Migration path suggestion**: 旧ヘッダと新ヘッダを並走で返す (deprecation periodを設定)。上限引き下げは段階的に行い、影響を受けるテナントへ事前通知。
- **Source**: [IETF draft-ietf-httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)、[RFC 9110 §10.2.3 Retry-After](https://datatracker.ietf.org/doc/html/rfc9110#section-10.2.3)

### 16. Auth-scope / permission semantics change

- **What to look for**: OAuth scopeの分割 (`read:all` → `read:users` + `read:orders`)、必要scope追加、tokenクレーム名変更 (`sub` → `user_id`)、API keyのprefix変更。
- **Why**: 既存トークンは旧scopeを持っている。新scopeを必須化すると即座に403連発。Stripeはこの理由でAPI keyのprefixを変えるときも互換期間を厳格に設定。
- **How to apply in a diff**: middleware の `require_scope(...)`、policy file、IAM定義 (`policy.json`、`*.cedar`、OPA rego)。
- **Migration path suggestion**: 新scopeは「あれば使う」optional化、旧scope保持クライアントは引き続き許可。Token reissuance期間を提供。auth変更は原則 major版で。
- **Source**: [Microsoft REST API Guidelines](https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md)、[Stripe API versioning](https://stripe.com/blog/api-versioning)

### 17. Protobuf reserved field / number reuse

- **What to look for**: 削除されたfieldのtag numberが新fieldで再利用されている、`reserved 5;` が無いまま field 5 を削除→別fieldで5を再追加、JSON serialization使用時に `reserved "old_name"` が無い。
- **Why**: protobufはfield numberでデコードする。旧クライアントがtag 5にstring を入れて送ってきたデータを、新サーバがtag 5の新int32としてパースすると無音の data corruption。
- **How to apply in a diff**: `*.proto` の `reserved` 行と、削除行 (tagやfield) のペアリングを確認。`buf breaking` で自動検出。
- **Migration path suggestion**: 削除と同時に `reserved <number>; reserved "<name>";` を必ず置く。新fieldは常に新しいnumberを使う。
- **Source**: [Protobuf: Reserved fields](https://protobuf.dev/programming-guides/proto3/#reserved)、[Earthly: Backward and Forward Compatibility](https://earthly.dev/blog/backward-and-forward-compatibility/)

### 18. DB column: NULL → NOT NULL without backfill + default

- **What to look for**: `ALTER TABLE ... ALTER COLUMN x SET NOT NULL` が単独で出てくる、新規追加列 `ADD COLUMN x INT NOT NULL` でDEFAULTが無く既存行が存在する、backfill migration が同PR (もしくは前段PR) に存在しない。
- **Why**: 既存行のNULLでmigration自体が失敗、または一時的にlockで本番停止。Postgres/MySQLでデフォルト無し NOT NULL ADD は大テーブルで full rewrite を起こす。
- **How to apply in a diff**: `migrations/*.sql`、Alembic / Flyway / Liquibase script、`change_column_null` などのDSL。
- **Migration path suggestion**: 4 stage migration: (1) column add as nullable + default, (2) app dual-write, (3) batch backfill (gh-ost / pt-online-schema-change / `UPDATE WHERE ... LIMIT` ループ), (4) NOT NULL制約をvalidate-only modeで足す ([Postgres `NOT VALID` → `VALIDATE CONSTRAINT`])。同PRで(1)〜(4)を全部やらない。
- **Source**: [Moments Log: safe DB backfill](https://www.momentslog.com/development/how-to-design-a-safe-database-backfill-without-turning-production-into-a-guessing-game)、[BirJob: zero-downtime migrations](https://www.birjob.com/blog/database-migrations)

### 19. DB column / table rename or drop

- **What to look for**: `RENAME COLUMN`、`DROP COLUMN`、`DROP TABLE`、Active Recordの `rename_column`。
- **Why**: 古いアプリレプリカ (デプロイ中の旧バージョン) が旧名で書き込みを続ける → write fail。読み取りでも `column not found`。Strangler Figパターンに従わない一段階rename/dropは本番落とす。
- **How to apply in a diff**: migration file、ORM model定義、SQL view、reporting query (ダッシュボード)、ETL pipeline。
- **Migration path suggestion**: (1) 新column追加、(2) アプリで dual write、(3) 全レプリカが新columnを読むよう deploy 完了、(4) 観測期間を置く、(5) 旧columnをdrop。Fowler「Strangler Fig」と同じ思想。
- **Source**: [Martin Fowler: Strangler Fig Application](https://martinfowler.com/bliki/StranglerFigApplication.html)、[Rails Migration Guide](https://codewithrails.com/rails-migration-guide/)

### 20. Foreign key / unique constraint added on existing data

- **What to look for**: `ADD CONSTRAINT ... FOREIGN KEY ...`、`CREATE UNIQUE INDEX`、`ADD CONSTRAINT ... CHECK (...)`。
- **Why**: 既存行に違反があるとmigration自体が失敗 (downtime)、または ACQUIRE EXCLUSIVE LOCK で本番停止。同時に古いアプリレプリカがduplicateを生成し続けると永遠に通らない。
- **How to apply in a diff**: SQL DDL、ORM での `validates_uniqueness_of` 追加 (アプリレベルだがDBで強制してない場合は別問題)。
- **Migration path suggestion**: (1) アプリ側で先に制約を満たす書き込みに変更、(2) 既存違反データをクリーンアップ、(3) Postgresなら `NOT VALID` で先に足してから `VALIDATE CONSTRAINT`、MySQLなら gh-ost。
- **Source**: [Postgres: ALTER TABLE NOT VALID](https://www.postgresql.org/docs/current/sql-altertable.html)、[BirJob: zero-downtime migrations](https://www.birjob.com/blog/database-migrations)

### 21. Index drop on hot column / unique index → non-unique

- **What to look for**: `DROP INDEX`、unique→非unique化、composite indexの列順変更。
- **Why**: クエリプランが激変、p99レイテンシが10〜100倍に飛ぶ。本番ユーザは「壊れた」と知覚する。unique制約の削除は同時に invariant 喪失でデータ不整合の窓を開ける。
- **How to apply in a diff**: migration file、`EXPLAIN ANALYZE` をPR descriptionで要求 (大体省かれている)、APM/slow query log。
- **Migration path suggestion**: indexを落とす前に `pg_stat_user_indexes` / `sys.dm_db_index_usage_stats` で利用実績を確認。Postgresは `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` を使う。unique制約は別途 application-level invariantを残す。
- **Source**: [BirJob: zero-downtime migrations](https://www.birjob.com/blog/database-migrations)、[Postgres CREATE INDEX CONCURRENTLY](https://www.postgresql.org/docs/current/sql-createindex.html)

### 22. Kafka / Avro / event schema compatibility level

- **What to look for**: producer側のschema変更、Schema Registry設定 (`BACKWARD` / `FORWARD` / `FULL` / `*_TRANSITIVE`)、新フィールドのdefault値欠如、enum値追加・削除。
- **Why**: Confluent: BACKWARDがデフォルト、`オプションフィールド追加 (default必須)` と `フィールド削除` のみ許可。FULL ではoptional fieldの追加・削除のみ。これを破ったschemaはregistryが拒否、deployが詰まる。逆に compatibility levelをこっそり緩めるとconsumer が壊れる経路ができる。
- **How to apply in a diff**: `*.avsc`、`*.proto` (Kafka向け)、Schema Registry設定 (terraform / yaml)、producer の `register_schema()` 呼び出し。
- **Migration path suggestion**: 新fieldは必ずdefault付きoptional。`compatibility level`を緩める変更はchangelog/ADRで合意してから。Kafka Streamsを使うなら `BACKWARD` 固定 (state store/changelog読み取りに必須)。
- **Source**: [Confluent: Schema Evolution & Compatibility Types](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html)、[Confluent Developer: Schema Compatibility](https://developer.confluent.io/courses/schema-registry/schema-compatibility/)

### 23. SDK public surface: function signature change

- **What to look for**: SDKの公開関数 (`pub fn` / `export function` / `__all__`) の引数追加・削除・順序変更・型変更、クラスのコンストラクタ変更、抽象メソッドの追加。
- **Why**: SDK は配布物。down-streamユーザーは固定バージョンに依存。署名変更は呼び出し側のcompile errorとなり、semver上では必ずmajor bumpが必要 (semver.org §8: 「後方非互換ならMAJORインクリメント必須」)。
- **How to apply in a diff**: `src/index.ts`、`__init__.py`、`pub mod`、`lib.rs`、Java `public` メソッド、Go の頭文字大文字 identifier。
- **Migration path suggestion**: 新シグネチャは新関数名で導入、旧関数を `@deprecated` 化。完全削除はmajor版で。
- **Source**: [Semantic Versioning 2.0.0](https://semver.org/)、[Rust Cargo SemVer Compatibility](https://doc.rust-lang.org/cargo/reference/semver.html)

### 24. Semver bump correctness (MAJOR / MINOR / PATCH)

- **What to look for**: 破壊的変更を含むPRで `version: 1.2.3` → `1.2.4` (patch) や `1.3.0` (minor) になっている。`v0.x` の状態で破壊的変更がpatch扱いになっている (0.x.x ではanything goesだが、実運用者は通常minor bumpを期待)。
- **Why**: semverは下流ツール (`npm`、`cargo`、`go.mod`) の自動バージョン解決の根拠。誤ったbumpは自動更新で本番事故を起こす。Cargoはsemver違反を実害として扱う ([Cargo SemVer Compatibility ref](https://doc.rust-lang.org/cargo/reference/semver.html))。
- **How to apply in a diff**: `package.json`、`Cargo.toml`、`pyproject.toml`、`CHANGELOG.md`、Git tag。本checklist上の他項目 (1〜23) のどれかにヒットしているのに major bumpになっていなければ flag。
- **Migration path suggestion**: CI上で `cargo-semver-checks` / `api-extractor` / `revapi` を回して破壊的変更を機械的に検出、versionと整合性チェック。
- **Source**: [Semantic Versioning 2.0.0](https://semver.org/)、[Cargo SemVer Compatibility](https://doc.rust-lang.org/cargo/reference/semver.html)

### 25. Deprecation / sunset signaling and timeline

- **What to look for**: 破壊的変更を含むのに `Deprecation` / `Sunset` HTTPヘッダ ([RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html)) や changelog記載がない、移行ガイドが無い、SDKに `@deprecated` 注釈が無い。
- **Why**: 移行コストを下流に押し付ける形になる。AIP-180とZalandoはともに「廃止予定はマーキングしてから時間を置いて削除」を要求。Stripeは「日付ベースでpinし、強制update無し」のモデル。
- **How to apply in a diff**: response header設定、SDKのアノテーション、API reference / CHANGELOG.md、`deprecated: true` フラグ。
- **Migration path suggestion**: Deprecation/Sunset headerを最低90日前から出す。Email通知、ダッシュボードでの利用警告を組み込む。
- **Source**: [RFC 8594 Sunset Header](https://www.rfc-editor.org/rfc/rfc8594.html)、[AIP-180](https://google.aip.dev/180)、[Stripe API versioning](https://stripe.com/blog/api-versioning)

---

## Anti-patterns to avoid in review (false positives)

レビュアーが「破壊的」と誤判定しがちな変更。これらに過剰反応すると開発が止まる。

1. **新しいoptional fieldの追加** — レスポンスへの追加フィールドは原則non-breaking。Zalandoも「optional fieldのみ追加せよ」と明文化。クライアントがstrictなdeserializer (例: 古いJackson `FAIL_ON_UNKNOWN_PROPERTIES=true`) を使っていて壊れるケースがあるが、それはクライアント側のバグ扱い ([Zalando guideline](https://opensource.zalando.com/restful-api-guidelines/))。
2. **新エンドポイント / 新メソッドの追加** — `/v1/users/:id/avatar` を新設する変更は既存クライアントに影響なし。レビューで「v2必要では」とは言わない。
3. **internal-only / experimental APIの変更** — `/internal/...`、`x-experimental: true` フラグ、private SDKモジュールは契約外。明示的に「unstable」と告知されている範囲なら破壊的変更でmajor bumpは不要 (実用的semver、[Aaronontheweb: Practical SemVer](https://aaronstannard.com/oss-semver/))。
4. **エラーメッセージ文字列の変更** (codeを変えない範囲で) — `message` フィールドは人間向けでlocaleの影響もある。ロジック分岐に使うなと公式に明記されている。codeさえ固定なら文字列変更は契約外。
5. **パフォーマンス改善によるレイテンシ変化** — p99が遅くなったわけではなく速くなった場合、契約には含まれない。ただし「クライアントがタイミングに依存している」(Hyrum's Law対象) ケースは要注意。
6. **JSONフィールド順序の変更** — RFC 8259 (JSON) はobject member orderingが意味を持たないと明示。これを契約として扱うクライアントは仕様違反。
7. **OpenAPI仕様の表現変更で挙動が同じ場合** — `oneOf` を `anyOf` に書き換えても受理されるJSON集合が同じなら non-breaking。差分ツール (`oasdiff`) が拾うが、実害なし。

---

## Gap analysis

`prompts/api-contract.md` は **存在しない**。

### Skeleton suggestion (for future `prompts/api-contract.md`)

```
You are an API contract reviewer. For each modified file in the diff, classify
changes into one of: ADDITIVE (non-breaking), DEPRECATING (compatible but
signals removal), BREAKING (requires major version bump or migration plan).

Inputs:
  - Diff (unified format)
  - Schema files touched (*.proto, *.graphql, openapi.yaml, *.avsc, migration files)
  - Current semver version
  - Target audience: external SDK consumers / internal services / both

For every BREAKING change, output:
  1. Concrete description (field name, endpoint path, table.column)
  2. Affected client class (mobile / external partner / internal service / SDK)
  3. Required migration steps (deprecate-then-remove, dual-write, version bump)
  4. Suggested timeline (deprecation period in days)
  5. Reference: which checklist item from 08-api-contract.md applies

For every DEPRECATING change, verify:
  - Deprecation marker present (@deprecated, Sunset header, [deprecated=true])
  - CHANGELOG entry added
  - Successor referenced

Output format: structured Markdown with sections per file, severity flags
(CRITICAL / WARNING / INFO), and a final "version bump recommendation"
(MAJOR / MINOR / PATCH) with justification.

Do NOT flag (false-positive list, see 08-api-contract.md):
  - New optional fields / endpoints
  - Internal/experimental surfaces
  - Error message string changes (codes unchanged)
  - JSON member order changes
```

### Recommended integration

- CI hook: `oasdiff` for OpenAPI、`buf breaking` for protobuf、`graphql-inspector` for GraphQL、`cargo-semver-checks` / `api-extractor` for SDKs、`pgroll` / `gh-ost` lint for migrations を並走させてpre-flagし、その出力をプロンプトのcontextに渡す形が token効率良い。
- PR template に「This PR contains breaking changes: [Y/N] — if Y, link migration plan」のチェックボックスを追加。

---

## References

### Primary specs / standards
- [Semantic Versioning 2.0.0](https://semver.org/)
- [RFC 9110 — HTTP Semantics](https://datatracker.ietf.org/doc/html/rfc9110)
- [RFC 8259 — The JavaScript Object Notation (JSON) Data Interchange Format](https://www.rfc-editor.org/rfc/rfc8259)
- [RFC 7807 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc7807)
- [RFC 8594 — The Sunset HTTP Header Field](https://www.rfc-editor.org/rfc/rfc8594.html)
- [draft-ietf-httpapi-ratelimit-headers (IETF)](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)

### Google AIPs (API Improvement Proposals)
- [AIP-180: Backwards compatibility](https://google.aip.dev/180)
- [AIP-185: API Versioning](https://google.aip.dev/185)
- [AIP-158: Pagination](https://google.aip.dev/158)
- [AIP-160: Filtering](https://google.aip.dev/160)
- [AIP-193: Errors](https://google.aip.dev/193)
- [Google Cloud API Design Guide](https://docs.cloud.google.com/apis/design)

### Industry guidelines
- [Microsoft Azure REST API Guidelines](https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md)
- [Microsoft Graph error responses](https://github.com/microsoft/api-guidelines/blob/vNext/graph/articles/errorResponses.md)
- [Zalando RESTful API and Event Guidelines](https://opensource.zalando.com/restful-api-guidelines/)
- [JSON:API specification](https://jsonapi.org/)
- [OpenAPI Initiative](https://www.openapis.org/)
- [AsyncAPI specification](https://www.asyncapi.com/)

### Vendor / project docs
- [Stripe Blog: APIs as infrastructure (versioning)](https://stripe.com/blog/api-versioning)
- [Stripe Blog: Designing robust and predictable APIs with idempotency](https://stripe.com/blog/idempotency)
- [Stripe API Docs: Versioning](https://docs.stripe.com/api/versioning)
- [Stripe API Docs: Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Protocol Buffers Documentation: Updating messages](https://protobuf.dev/programming-guides/proto3/#updating)
- [Buf: Breaking change detection](https://buf.build/docs/breaking/overview)
- [Confluent Schema Registry: Schema Evolution](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html)
- [Apollo GraphQL: Nullability](https://www.apollographql.com/docs/graphos/schema-design/guides/nullability)
- [GraphQL.org: Schema Design](https://graphql.org/learn/schema-design/)

### Patterns / books / blogs
- [Martin Fowler: Strangler Fig Application](https://martinfowler.com/bliki/StranglerFigApplication.html)
- [Hyrum's Law](https://www.hyrumslaw.com/)
- [Cargo SemVer Compatibility (Rust)](https://doc.rust-lang.org/cargo/reference/semver.html)
- [Aaronontheweb: Practical vs Strict SemVer](https://aaronstannard.com/oss-semver/)
- [Earthly: Protocol Buffers Best Practices for Backward and Forward Compatibility](https://earthly.dev/blog/backward-and-forward-compatibility/)
- [Yokota: Understanding Protobuf Compatibility](https://yokota.blog/2021/08/26/understanding-protobuf-compatibility/)
- [Moments Log: How to Design a Safe Database Backfill](https://www.momentslog.com/development/how-to-design-a-safe-database-backfill-without-turning-production-into-a-guessing-game)
- [BirJob: The Complete Guide to Database Migrations Without Downtime](https://www.birjob.com/blog/database-migrations)
- [Bump.sh: API Design Reviews](https://bump.sh/blog/api-design-reviews/)
- [Treblle: API Governance Best Practices for 2026](https://treblle.com/blog/api-governance-best-practices)
- [oasdiff: OpenAPI diff and breaking changes](https://github.com/Tufin/oasdiff)
