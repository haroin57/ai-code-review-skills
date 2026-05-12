---
title: Architecture Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://google.github.io/eng-practices/review/reviewer/looking-for.html
  - https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf
  - https://martinfowler.com/bliki/Yagni.html
  - https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer
  - https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_1.pdf
  - https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)
  - https://refactoring.guru/smells/primitive-obsession
  - https://www.informit.com/articles/article.aspx?p=2952392&seqNum=9
  - https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/
---

# Architecture Code Review Best Practices

## Why this matters

アーキテクチャ観点のレビューは「動くか」ではなく「**長期に維持できる構造になっているか**」を見る作業です。Google の eng-practices は code review において最も重要な観点を "overall design" だと明言しており、機能やテストよりも先に設計の妥当性を確認すべきと位置づけています ([Google eng-practices](https://google.github.io/eng-practices/review/reviewer/looking-for.html))。

アーキテクチャ的な欠陥は実行時には現れず、半年〜数年後に「触れない領域」「変更コストの爆発」「整合性違反」として顕在化します。John Ousterhout が指摘するように、複雑さの最悪の形は "unknown unknowns" — 何を知らなければならないのかすら分からない状態であり、これは shallow module や leaky abstraction が積み重なって生まれます ([A Philosophy of Software Design](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf))。

diff レビューにおける現実的なスコープは次の通りです:

- 新しく追加されたファイル/モジュール境界は適切か
- 既存の依存方向ルールを破っていないか
- 新しい抽象は「3回目の重複」を待ったものか、それとも投機的か
- bounded context / aggregate / 永続化境界を越える変更が混入していないか

## Review checklist

### 1. モジュール境界が責務を反映しているか
- **What to look for**: 新規ファイル/ディレクトリ追加時、その配置が既存の module map（layer、bounded context、feature）と整合しているか。`utils/` `common/` `shared/` に何でも入れるパターン、機能ファイルが横断的フォルダに散らばるパターン (shotgun surgery の予兆)
- **Why**: 境界が曖昧だと変更の波及範囲（blast radius）が予測不能になり、change amplification を引き起こす
- **How to apply in a diff**: `git diff --stat` の出力で「1つの論理変更が4つ以上の無関係なディレクトリに広がっている」場合は要警戒。新規ファイルは「なぜこの場所か」をPR descriptionで説明させる
- **Source**: [Google eng-practices — Looking for in CL](https://google.github.io/eng-practices/review/reviewer/looking-for.html), [ByteByteGo — Coupling and Cohesion](https://blog.bytebytego.com/p/coupling-and-cohesion-the-two-principles)

### 2. レイヤリング違反 (layering violation)
- **What to look for**: domain 層が infrastructure 層を直接 import している、UI 層が DB アクセスを直接呼ぶ、test helper が production code を逆方向に参照する
- **Why**: dependency direction が乱れると DIP (Dependency Inversion Principle) が崩れ、テスト容易性と差し替え可能性が失われる
- **How to apply in a diff**: 新規 import 文を全件確認。`domain/` → `infrastructure/` の参照、`core/` → `adapters/` の参照を grep で機械的に検出。ArchUnit / dependency-cruiser / import-linter のルールが diff で更新されていないかも確認
- **Source**: [Hexagonal Architecture — Wikipedia](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)), [AWS Prescriptive Guidance — Hexagonal](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html)

### 3. 結合度 (coupling) は最小限か
- **What to look for**: グローバル変数経由のデータ共有 (content coupling)、新規 import が遠いモジュールに伸びている、関数シグネチャに無関係な引数が追加されている (control coupling)
- **Why**: 強結合は「Aを直すとBが壊れる」恐怖を生む。Sam Newman が言う通り、microservice 境界において結合度が高いと "changes in one service can require changes in many other services"
- **How to apply in a diff**: 新規 import 行数を数える。1ファイルで5個以上の新規 cross-module import は cohesion 問題のサイン
- **Source**: [Vijay Anant — Good vs Bad Coupling](https://vijayanant.com/posts/modular-by-design/good-coupling-bad-coupling-and-cohesion/), [Building Microservices 2nd Ed](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/)

### 4. 凝集度 (cohesion) は高いか
- **What to look for**: 1つのクラス/モジュール内で「初期化」「クリーンアップ」「ログ」「変換」「永続化」が同居している (temporal cohesion)。命名に "Manager" "Helper" "Util" が出てくる
- **Why**: 凝集度が低いモジュールは "1文で説明できない" ため、誰も全体像を把握できなくなる
- **How to apply in a diff**: 新規/変更されたクラスについて「このクラスは何をするか」を接続詞 (and / or / also) を使わず1文で書けるか試させる。書けなければ SRP 違反の可能性
- **Source**: [Adelphi — Coupling and Cohesion adages](https://home.adelphi.edu/sbloch/class/adages/coupling_cohesion.html), [Paul Serban — Twin Pillars of Modularity](https://www.paulserban.eu/blog/post/module-coupling-and-cohesion-the-twin-pillars-of-modularity/)

### 5. Deep module vs shallow module
- **What to look for**: pass-through method（他のメソッドをそのまま呼ぶだけのラッパー）、interface に出てくる引数が実装の詳細をそのまま反映しているクラス、`FileInputStream → BufferedInputStream → ObjectInputStream` のような重ね合わせ API
- **Why**: shallow module は隠蔽するコスト > 隠蔽する利得。Ousterhout が "small classes don't contribute much functionality so there have to be a lot of them, each with its own interface" と警告する通り、複雑さがインターフェース側に漏れる
- **How to apply in a diff**: 新規クラスの public method 数と各メソッドの平均実装行数を確認。public surface > implementation depth なら shallow
- **Source**: [A Philosophy of Software Design (Ousterhout)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf), [Pragmatic Engineer — Book Review](https://blog.pragmaticengineer.com/a-philosophy-of-software-design-review/)

### 6. API surface が必要最小か
- **What to look for**: `public` で外部に晒される method/field の数、新規エクスポートシンボル、`export *` 的な再エクスポート
- **Why**: 一度公開された API は consumer が増えるほど変更コストが上がる (Hyrum's Law)。Sam Newman は "Think outside-in: design interface first, then code" と推奨する
- **How to apply in a diff**: 新規 `public` / `export` を全件チェック。internal で済むものが public 化されていたら指摘する
- **Source**: [Building Microservices — Stable Contracts](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/), [Google eng-practices — Standard](https://google.github.io/eng-practices/review/reviewer/standard.html)

### 7. 投機的抽象化 (premature abstraction) を入れていないか
- **What to look for**: 1〜2 回しか使われない interface、現在の要件にない設定パラメータ、"将来の拡張性のため" と称した generic 化、Strategy / Factory パターンが実装1個しかない状態で導入されている
- **Why**: Fowler は YAGNI で "any abstraction that makes it harder to understand the code for current requirements is presumed guilty" と明言。Sandi Metz の "duplication is far cheaper than the wrong abstraction"
- **How to apply in a diff**: 新規 interface / abstract class について「実装が2つ以上あるか」「3回目の重複に達したか (rule of three)」を確認
- **Source**: [Martin Fowler — Yagni](https://martinfowler.com/bliki/Yagni.html), [Rule of three — Wikipedia](https://en.wikipedia.org/wiki/Rule_of_three_(computer_programming))

### 8. 不足している抽象 (missing abstraction)
- **What to look for**: 3 箇所以上に同じロジックがコピペされている、同じ if-else 分岐が複数ファイルに散在、primitive (string, int) で domain concept を表現している
- **Why**: 重複自体より「変更時の整合性ずれ」が問題。Rule of three を満たしているのに抽象化しないと shotgun surgery が発生する
- **How to apply in a diff**: 新規ロジックが既存コードと類似していないか grep。`TODO: extract` レベルで指摘し、本 PR か follow-up PR で対応させる
- **Source**: [Incus Data — Rule of Three](https://incusdata.com/blog/refactoring-the-rule-of-three), [Martin Fowler — Yagni](https://martinfowler.com/bliki/Yagni.html)

### 9. Single Responsibility Principle / god class の予防
- **What to look for**: 既存クラスへのメソッド追加で行数が 500行 / 20メソッド を超えた、無関係な責務 (validation + persistence + notification) が同居
- **Why**: god class は SRP の極端な違反であり、"Just-One-More Syndrome" で徐々に成長する。Robert C. Martin: "A class should have one, and only one, reason to change"
- **How to apply in a diff**: 既存クラスへの追加は「なぜこのクラスか、別クラスではダメか」を必ず問う。`User`, `Manager`, `Service` 系の肥大化は特に警戒
- **Source**: [NDepend — SRP](https://blog.ndepend.com/solid-design-the-single-responsibility-principle-srp/), [thoughtbot — Ruby Science SRP](https://thoughtbot.com/ruby-science/single-responsibility-principle.html)

### 10. Dependency direction / DIP の遵守
- **What to look for**: 高レベルモジュール (use case, domain) が低レベルモジュール (DB driver, HTTP client) を具象クラスで参照している。interface が "下" にあって "上" がそれを実装する逆転構造
- **Why**: DIP が崩れると test double が刺さらず、infrastructure 変更が domain logic に波及する。Hexagonal Architecture の核心
- **How to apply in a diff**: domain 層に追加された import を全件確認。`postgres`, `axios`, `boto3` 等の具象 SDK が domain から見えていたら NG
- **Source**: [Hexagonal Architecture — Wikipedia](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)), [Codeartify — Dependency Inversion](https://codeartify.substack.com/p/dependency-inversion)

### 11. Feature envy
- **What to look for**: メソッド A が、自身のクラスのフィールドより他クラス B のフィールド/メソッドを多く触っている。`order.customer.address.street` のような連鎖アクセス (Law of Demeter 違反)
- **Why**: ロジックがデータと一緒にいない → データを持つクラスを変更したら envious method 側も壊れる。Fowler: "put things together that change together"
- **How to apply in a diff**: 変更されたメソッドで「self/this のフィールド参照数 vs 他クラスのフィールド参照数」をざっと数える。後者が多ければ Move Method を推奨
- **Source**: [InformIT — Feature Envy](https://www.informit.com/articles/article.aspx?p=2952392&seqNum=9), [luzkan — Feature Envy smell](https://luzkan.github.io/smells/feature-envy/)

### 12. Primitive obsession
- **What to look for**: `string email`, `int amountInCents`, `string phoneNumber` のような stringly-typed フィールド、`Map<String, Object>` で構造を表現、unit (cm/m, USD/JPY) が型に出ていない
- **Why**: validation / 表示ロジック / 変換ロジックが分散する。"calculations that treat monetary amounts as plain numbers" の典型バグを生む
- **How to apply in a diff**: 新規 domain 概念 (Email, Money, UserId, Coordinate 等) が primitive で表現されていたら value object 化を提案
- **Source**: [Refactoring.guru — Primitive Obsession](https://refactoring.guru/smells/primitive-obsession), [InformIT — Primitive Obsession](https://www.informit.com/articles/article.aspx?p=2952392&seqNum=11)

### 13. Ports & Adapters 違反
- **What to look for**: domain (hexagon 内側) が adapter (外側) を直接知っている、port (interface) を経由しない infrastructure 呼び出し、adapter 側に business logic が混入
- **Why**: hexagonal の「business logic は infrastructure に依存しない」原則が崩れると、DB/UI/API を差し替えるたびに domain test が壊れる
- **How to apply in a diff**: `domain/` 配下に `import` された具象 adapter 型がないか、port interface が domain 側で定義されているかを確認
- **Source**: [AWS Prescriptive Guidance — Hexagonal](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html), [Java Code Geeks — Hexagonal](https://www.javacodegeeks.com/2025/12/hexagonal-architecture-ports-and-adapters-achieving-true-domain-independence.html)

### 14. Anti-Corruption Layer (ACL) の有無と適切さ
- **What to look for**: 外部システム / レガシー / 別 bounded context との統合点で、外部モデルがそのまま domain にリークしている。`LegacyOrderDto` が domain service の引数になっている
- **Why**: 外部の概念や命名が domain を汚染すると、外部 API 変更のたびに domain が壊れる。Evans のオリジナル DDD 推奨パターン
- **How to apply in a diff**: 外部 API クライアントの応答型が、そのまま repository / use case の戻り値になっていないか確認。Translator / Facade / Adapter の3要素が揃っているか
- **Source**: [Microsoft — Anti-corruption Layer](https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer), [AWS — ACL pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/acl.html), [DevIQ — ACL](https://deviq.com/domain-driven-design/anti-corruption-layer/)

### 15. Bounded context の越境
- **What to look for**: 1 PR で複数の bounded context (例: `billing` と `inventory`) のコードが同時に変更されている、別 context の internal model が直接 import されている
- **Why**: Newman: "If you are constantly making changes across multiple services, your microservices boundaries are wrong"。境界違反は将来の分割不能性に繋がる
- **How to apply in a diff**: 変更されたディレクトリの top-level を集計し、複数 context にまたがる場合は「context 間 contract 更新が必要か」を問う
- **Source**: [Building Microservices 2nd Ed](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/), [DDD Practitioners — ACL](https://ddd-practitioners.com/home/glossary/bounded-context/bounded-context-relationship/anticorruption-layer/)

### 16. Transaction boundary が aggregate と一致しているか
- **What to look for**: 1 トランザクション内で複数 aggregate を更新している、aggregate root を経由しない直接の子 entity 更新、外部 ID 参照ではなくオブジェクト参照で aggregate を跨いでいる
- **Why**: Vernon の Rule 1: "Model true invariants in consistency boundaries"、Rule "modify only one Aggregate instance per transaction"。違反するとロック競合とスケーラビリティ崩壊を招く
- **How to apply in a diff**: トランザクション (`@Transactional`, `db.transaction()`, unit of work) のスコープを確認。複数 aggregate root を save していたら domain event + 結果整合性に分解する提案を出す
- **Source**: [Vernon — Effective Aggregate Design Part I](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_1.pdf), [InformIT — Rule: Model True Invariants](https://www.informit.com/articles/article.aspx?p=2020371&seqNum=2)

### 17. Consistency boundary 外で eventual consistency を採用しているか
- **What to look for**: aggregate 境界を越えた整合性を同期的に強要している (例: order 作成と inventory 引当を同一 transaction に押し込む)
- **Why**: Vernon Rule 4: "Use Eventual Consistency Outside the Boundary"。同期強整合は scalability を破壊し、deadlock を生む
- **How to apply in a diff**: 跨ぎ更新を見つけたら、domain event publish + async subscriber に置き換えられないか議論する
- **Source**: [InformIT — Eventual Consistency Outside](https://www.informit.com/articles/article.aspx?p=2020371&seqNum=5), [Cosmic Python — Aggregates](https://www.cosmicpython.com/book/chapter_07_aggregate.html)

### 18. Service contract の後方互換性
- **What to look for**: 既存 API の field 削除 / 必須化 / 型変更、event schema の breaking change、gRPC `.proto` の互換性違反、consumer-driven contract test が更新されていない
- **Why**: 公開済み contract の breaking change は consumer を破壊する。Newman は CDC (Consumer-Driven Contracts) と tolerant reader / Postel's Law を推奨
- **How to apply in a diff**: schema 系ファイル (`.proto`, OpenAPI, GraphQL SDL, Avro) の変更は専用 reviewer を立てる。新規 field は optional / default 付きで導入されているか確認
- **Source**: [Building Microservices 2nd Ed](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/), [Sam Newman — Monolith to Microservices notes](https://eddmann.com/posts/notes-monolith-to-microservices-by-sam-newman/)

### 19. Pass-through coupling / god service
- **What to look for**: A → B → C → D と引数をそのまま受け渡しているだけのチェーン、1つの service が下流の 5+ service を呼び出している orchestrator
- **Why**: pass-through は intermediary contract を不必要に膨張させ、Ousterhout が指摘する pass-through method と同型の shallow design を生む。中央集権 service は god class の分散版
- **How to apply in a diff**: 新規 service / function の引数が「自分で使っていないが下流に渡しているだけ」のものを数える。3個以上なら設計を疑う
- **Source**: [A Philosophy of Software Design (Ousterhout)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf), [Building Microservices 2nd Ed](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/)

### 20. Over-engineering / 不要な generic 化
- **What to look for**: 1箇所しか使わない plugin システム、設定可能な runtime strategy、将来のために用意された feature flag、ジェネリクスの多用
- **Why**: Google eng-practices: "Reviewers should be especially vigilant about over-engineering. Encourage developers to solve the problem they know needs to be solved now"
- **How to apply in a diff**: 新規の extension point について「現在 N 個の実装があるか」を確認。N=1 なら削除を提案
- **Source**: [Google eng-practices — Looking for](https://google.github.io/eng-practices/review/reviewer/looking-for.html), [Martin Fowler — Yagni](https://martinfowler.com/bliki/Yagni.html)

### 21. 設定パラメータの暴走 (configuration leak)
- **What to look for**: 新規の environment variable / config key が、本来 runtime で計算可能な値、または delegate 先で決定すべき値
- **Why**: Ousterhout: "configuration parameters are an example of moving complexity upwards rather than down"。複雑さを利用者側に転嫁する anti-pattern
- **How to apply in a diff**: 新規 config に対して「自動算出 / 適応的決定はできないか」「ユーザーが妥当な値を選べる根拠があるか」を問う
- **Source**: [A Philosophy of Software Design (Ousterhout)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf), [Pragmatic Engineer — POSD review](https://blog.pragmaticengineer.com/a-philosophy-of-software-design-review/)

### 22. 循環依存 (cyclic dependency)
- **What to look for**: 新規 import が既存の DAG にサイクルを作る、package A ↔ B、module 階層上下双方向参照
- **Why**: 循環依存は build / test / deploy の単位を壊し、変更影響範囲を予測不能にする
- **How to apply in a diff**: `madge`, `import-linter`, `go list`, `pylint cyclic-import` 等のレポートを CI に組み込み、diff で増えていないか確認
- **Source**: [thevaluable.dev — Cohesion and Coupling](https://thevaluable.dev/cohesion-coupling-guide-examples/), [VoltAgent — architect-reviewer](https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/categories/04-quality-security/architect-reviewer.md)

## Anti-patterns to avoid in review

レビュー側が陥りがちな悪手:

- **「動いてるからOK」judgment**: Google eng-practices が明言する通り、最重要観点は design。動作確認はテストの責務であり、レビューは構造を見る場
- **Style bikeshedding に時間を使いきる**: 命名・インデントで満足してアーキ問題を素通りすると、PR が承認された後に "なぜ通したのか" が問われる
- **将来の拡張性を理由に追加抽象を要求する**: YAGNI 違反。reviewer 側が premature abstraction を強要するのは典型的な over-engineering 誘発要因
- **1 PR で全部直そうとする**: 大きな構造問題は本 PR で承認 + follow-up issue 起票が現実的。Ousterhout の "design it twice" の精神で、別 PR での再設計を提案する
- **個別ファイルだけ見て module map を見ない**: diff が小さくても境界違反は致命的。常に「このファイルはなぜここにあるか」を問う
- **既存の violation に同調する**: "他もこうなってるから" は技術的負債を肯定する論理。新規追加分は新基準で評価する

## Gap analysis vs current prompt

**現状**: `/home/ubuntu/ai-code-review-skills/prompts/architecture.md` は存在しない。

**推奨**: 以下の骨子で `prompts/architecture.md` を新規作成する:

```
You are an architecture-focused code reviewer. Review the diff with the following lens.

Skeleton bullets (must be in the prompt):

1. Module boundaries & dependency direction
   - 新規ファイルの配置妥当性を必ず指摘する
   - layer / bounded context を跨ぐ import を全件列挙させる
   - DIP 違反 (domain → infrastructure 具象参照) を最優先で flag

2. Coupling / cohesion smells
   - god class / feature envy / primitive obsession / pass-through method を診断
   - 1 クラスの責務を 1 文 (接続詞なし) で説明できるか問う

3. Abstraction depth (Ousterhout)
   - shallow module (public surface > implementation depth) を検出
   - configuration parameter 追加に対しては自動算出可能性を問う

4. Premature vs missing abstraction (YAGNI / Rule of three)
   - 実装1個しかない interface は削除提案
   - 3+ 箇所重複の primitive ロジックは extract 提案

5. DDD boundaries
   - aggregate を跨ぐ transaction を flag
   - bounded context 越境変更は ACL の有無を確認
   - external model の直接利用 → ACL 経由に変更提案

6. API surface & contract
   - 新規 public / export を全件レビュー
   - schema 変更 (proto / OpenAPI / GraphQL) の breaking change チェック

7. Output format
   - Severity: blocker / major / minor / nit
   - 各指摘に「該当ファイル:行」「smell 名」「推奨リファクタ」「参考リンク」を付与
   - 既存構造の追認ではなく、新規追加分を新基準で評価する旨を明示

8. Anti-engagement guard
   - "looks good" 単独レビューは禁止。最低 1 つは構造観点を挙げるか、明示的に "no architectural concern found because X" を書く
```

この skeleton は本ファイルの checklist 22 項目を圧縮した形で reviewer に渡せるよう設計されている。実装時は項目ごとに具体例 (good / bad) を1組ずつ添付すると検出精度が上がる。

## References

- [Google Engineering Practices — What to look for in a code review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
- [Google Engineering Practices — The Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html)
- [Software Engineering at Google — Chapter 9: Code Review](https://abseil.io/resources/swe-book/html/ch09.html)
- [John Ousterhout — A Philosophy of Software Design (2nd Ed. extract)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf)
- [Pragmatic Engineer — A Philosophy of Software Design review](https://blog.pragmaticengineer.com/a-philosophy-of-software-design-review/)
- [Martin Fowler — Yagni](https://martinfowler.com/bliki/Yagni.html)
- [Martin Fowler & Kent Beck — Refactoring: Feature Envy excerpt](https://www.informit.com/articles/article.aspx?p=2952392&seqNum=9)
- [Martin Fowler & Kent Beck — Refactoring: Primitive Obsession excerpt](https://www.informit.com/articles/article.aspx?p=2952392&seqNum=11)
- [Refactoring.guru — Primitive Obsession](https://refactoring.guru/smells/primitive-obsession)
- [Rule of three (computer programming) — Wikipedia](https://en.wikipedia.org/wiki/Rule_of_three_(computer_programming))
- [Hexagonal Architecture — Wikipedia](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software))
- [AWS Prescriptive Guidance — Hexagonal Architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html)
- [Codeartify — Dependency Inversion between Business and Data Access](https://codeartify.substack.com/p/dependency-inversion)
- [Microsoft Azure — Anti-corruption Layer pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer)
- [AWS Prescriptive Guidance — ACL pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/acl.html)
- [DevIQ — Anti-Corruption Layer](https://deviq.com/domain-driven-design/anti-corruption-layer/)
- [DDD Practitioners — Anticorruption Layer](https://ddd-practitioners.com/home/glossary/bounded-context/bounded-context-relationship/anticorruption-layer/)
- [Sam Newman — Building Microservices, 2nd Edition (O'Reilly)](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/)
- [Edd Mann — Notes: Monolith to Microservices by Sam Newman](https://eddmann.com/posts/notes-monolith-to-microservices-by-sam-newman/)
- [Vaughn Vernon — Effective Aggregate Design Part I (PDF)](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_1.pdf)
- [Vaughn Vernon — Effective Aggregate Design Part II (PDF)](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_2.pdf)
- [InformIT — Rule: Model True Invariants in Consistency Boundaries](https://www.informit.com/articles/article.aspx?p=2020371&seqNum=2)
- [InformIT — Rule: Use Eventual Consistency Outside the Boundary](https://www.informit.com/articles/article.aspx?p=2020371&seqNum=5)
- [Cosmic Python — Chapter 7: Aggregates and Consistency Boundaries](https://www.cosmicpython.com/book/chapter_07_aggregate.html)
- [NDepend — SOLID Single Responsibility Principle](https://blog.ndepend.com/solid-design-the-single-responsibility-principle-srp/)
- [thoughtbot — Ruby Science: Single Responsibility Principle](https://thoughtbot.com/ruby-science/single-responsibility-principle.html)
- [ByteByteGo — Coupling and Cohesion: Two Principles for Effective Architecture](https://blog.bytebytego.com/p/coupling-and-cohesion-the-two-principles)
- [Vijay Anant — Software Coupling and Cohesion: Good vs Bad Design](https://vijayanant.com/posts/modular-by-design/good-coupling-bad-coupling-and-cohesion/)
- [thevaluable.dev — Cohesion and Coupling in Software](https://thevaluable.dev/cohesion-coupling-guide-examples/)
- [VoltAgent — architect-reviewer subagent reference](https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/categories/04-quality-security/architect-reviewer.md)
- [luzkan — Feature Envy smell](https://luzkan.github.io/smells/feature-envy/)
- [Incus Data — Refactoring and the Rule of Three](https://incusdata.com/blog/refactoring-the-rule-of-three)
