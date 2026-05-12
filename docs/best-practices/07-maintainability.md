---
title: Maintainability Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://google.github.io/eng-practices/review/reviewer/looking-for.html
  - https://google.github.io/eng-practices/review/reviewer/comments.html
  - https://google.github.io/eng-practices/review/reviewer/standard.html
  - https://google.github.io/eng-practices/review/reviewer/speed.html
  - https://abseil.io/resources/swe-book/html/ch09.html
  - https://google.github.io/styleguide/
  - https://refactoring.com/catalog/
  - https://martinfowler.com/bliki/CodeSmell.html
  - https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf
  - https://www.oreilly.com/library/view/tidy-first/9781098151232/
  - https://stackoverflow.blog/2021/12/23/best-practices-for-writing-code-comments/
  - https://en.wikipedia.org/wiki/Cyclomatic_complexity
  - https://en.wikipedia.org/wiki/Don%27t_repeat_yourself
  - https://kentcdodds.com/blog/aha-programming
  - https://github.com/adidas/api-guidelines/blob/master/general-guidelines/minimal-api-surface.md
---

# Maintainability Code Review Best Practices

## Why this matters

ソフトウェアは **書かれる回数より読まれる回数の方が圧倒的に多い**。Robert Martin の見積もりでは read:write 比は約 10:1 であり、Google の "Software Engineering at Google" でも「コードベースの寿命は人間の寿命より長く設計しろ」と明示されている。保守性レビューは「今動くか」ではなく「**6 ヶ月後、別の人間がこれを安全に変更できるか**」を問う作業である。

経験則上、以下のコストカーブが効く：
- 関数の cyclomatic complexity が 10 を超えると欠陥密度は実証研究で 2〜3 倍に跳ねる（McCabe, NASA SATC）。
- 直されないコメントは「嘘の文書」になり、no-comment より有害になる（Stack Overflow Rule 2）。
- 一度公開された public API は実質 **永続的なコミットメント** になる（Enterprise Craftsmanship）。

ただし Google eng-practices の最重要原則を忘れない: 「**Perfect ではなく Better を求めよ**」。レビューは現状より良くするものであって、理想形に書き直させる場ではない。

## Review checklist

### 1. 命名は「何を表すか」を即座に伝えるか
- **What to look for**: 単一文字変数（数学的慣習・短いスコープのループ index 以外）、`data` / `info` / `tmp` / `handle` / `manager` のような無情報語、略語の乱用、型を名前に埋め込んだハンガリアン残骸、boolean に動詞が無い (`user` vs `isUser`)、関数名が副作用を隠している (`getUser()` が DB に書き込む)。
- **Why**: 名前は **そのコードを読む全員が払う税金**。悪い名前は読むたびに脳内で翻訳作業が発生し、誤読は本物のバグになる。
- **How to apply in a diff**: その名前だけを 5 秒見て、「これは何を返す/保持する/する」と一文で言えるか試す。言えなければコメントで「`xs` → `pendingInvoices` のように内容が分かる名前に」と提案する。ただし周囲のコードが既に短い慣習なら**周辺との一貫性を優先**する（Google スタイルガイドの "BE CONSISTENT"）。
- **Source**: [Google Style Guides](https://google.github.io/styleguide/), [Gemini Code Assist style guide](https://developers.google.com/gemini-code-assist/docs/code-review-style-guide)

### 2. 関数の長さ・責務がスクリーン 1 画面に収まるか
- **What to look for**: 100 行を超える関数、レベル 4 以上のインデント、複数の "and" で説明される責務 ("ユーザを検証して、DB に保存して、メールを送って、メトリクスを記録する")。
- **Why**: 長い関数は cyclomatic complexity の主因であり、テスト網羅困難・部分理解不能・差分レビュー困難の三重苦を生む。
- **How to apply in a diff**: 関数の docstring/要約を「**and / または を使わずに**」書けるか試す。書けなければ責務分離を提案。ただし無理矢理 1-shot helper に切り出すと「Shallow Module」(Ousterhout) になり逆効果なので、切り出し先が再利用または **独立にテスト可能** であることを確認する。
- **Source**: [A Philosophy of Software Design (Ousterhout)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf)

### 3. Cyclomatic complexity が閾値 10 を超えていないか
- **What to look for**: 多段ネストの `if`/`for`/`switch`、boolean flag を分岐に多用する関数、`else if` の長いチェーン。
- **Why**: McCabe の元論文と NASA SATC の実証研究で、CC=10 を境に欠陥密度が顕著に上がる。CC は完全パスカバレッジに必要な最小テスト数とも一致する。
- **How to apply in a diff**: CI に lizard/radon/SonarQube 等が居るならその出力を引く。手動なら if/else/case/&&/|| の数を数えて +1 する。10〜15 はチーム判断で許容可能、20+ は **必ず** 早期 return（guard clause）または Strategy パターンで分解を提案。CC が低くてもネストが深ければ Cognitive Complexity を別途指摘する。
- **Source**: [Cyclomatic complexity (Wikipedia)](https://en.wikipedia.org/wiki/Cyclomatic_complexity), [Cognitive vs Cyclomatic (Packmind)](https://dev.to/packmind/cyclomatic-complexity-and-cognitive-complexity-4c03)

### 4. ネストの深さ（cognitive complexity）が過大でないか
- **What to look for**: インデント 4 段以上、ループの中の `if` の中のループ、try/except の入れ子。
- **Why**: 同じ CC でも flat な分岐より入れ子の方が読み手のワーキングメモリ消費が大きい。3 段ネストを超えると人間は文脈追跡を失う。
- **How to apply in a diff**: 早期 return / guard clause、Extract Method、`continue` でフラット化を提案。`if X { ... } else { return }` は `if !X return; ...` に反転できる。
- **Source**: [Cognitive complexity (SonarSource)](https://dev.to/packmind/cyclomatic-complexity-and-cognitive-complexity-4c03)

### 5. コメントは "WHY" を語っているか、"WHAT" を繰り返していないか
- **What to look for**: `i++ // increment i` のような同語反復、関数シグネチャをそのまま日本語訳した docstring、TODO without owner/date、嘘になっているコメント（コードと矛盾）。
- **Why**: Stack Overflow Rule 1〜4 (Vogel)。間違ったコメントは **コメント無しより有害**。コンパイラはコメントを検証しないので、放置するとアンチドキュメントになる。
- **How to apply in a diff**: WHAT コメントは「**コードを clarify する方が先**」と指摘し（Google: "explanations only in review tool don't help future readers"）、WHY コメント（性能上の workaround、業務ルールの背景、外部仕様の参照リンク、`# noqa` の理由）は積極的に肯定する。
- **Source**: [Stack Overflow: best practices for writing code comments](https://stackoverflow.blog/2021/12/23/best-practices-for-writing-code-comments/), [Google eng-practices: comments](https://google.github.io/eng-practices/review/reviewer/comments.html)

### 6. Magic number / magic string が定数化されているか
- **What to look for**: `if status == 7`、`sleep(86400)`、`if role == "adm1n_v2"`、HTTP status コードのリテラル散在。
- **Why**: Fowler の古典的 code smell。意味不明な数値は読み手に "**なぜこの値？**" を毎回質問させ、変更時の grep 漏れで部分修正のバグを生む（Shotgun Surgery への階段）。
- **How to apply in a diff**: `MAX_RETRY_COUNT = 3`、`SECONDS_PER_DAY = 86400` 等の名前付き定数に。ただし `0` / `1` / `-1` / 空文字列 / 自明な配列インデックス（`arr[0]` で「先頭」が明白）は除外。
- **Source**: [Code smell (Wikipedia)](https://en.wikipedia.org/wiki/Code_smell), [Refactoring catalog](https://refactoring.com/catalog/)

### 7. 重複ロジック (DRY) — ただし Rule of Three を守っているか
- **What to look for**: 3 箇所以上で同じ計算式・同じバリデーション・同じエラーハンドリングが繰り返されている。1 文字違いの似たメソッドが並んでいる（"Alternative Classes with Different Interfaces"）。
- **Why**: 重複は変更コストを線形に膨らませ、片方だけ修正されてバグになる典型パターン。
- **How to apply in a diff**: **2 回目までは許容、3 回目で抽象化** (Rule of Three / Pragmatic Programmer)。逆に「似ているが**ドメイン的に別概念**」（決済の割引と会員ランクの割引など）は無理に DRY 化しない — Kent C. Dodds の AHA principle "duplication is far cheaper than the wrong abstraction"。差分レビューでは「現時点で抽象化するか / Issue として記録するか」を選択肢として書く。
- **Source**: [DRY (Wikipedia)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself), [AHA Programming (Kent C. Dodds)](https://kentcdodds.com/blog/aha-programming)

### 8. Dead code / unreachable code / コメントアウトの墓場
- **What to look for**: 呼び出されていない private 関数、`if False:` ブロック、`return` 後のコード、コメントアウトされたままの大ブロック、未使用 import / 未使用変数。
- **Why**: dead code は読み手に "**まだ使われているのか？**" の問いを強制し、依存解析と grep 結果を汚染する。VCS が履歴を保管しているのでコメントアウトは不要。
- **How to apply in a diff**: 削除を提案する。「将来使うかも」は YAGNI 違反で却下根拠になる。Linter (unused-import, dead-code) が拾える層は自動化に任せる。
- **Source**: [Refactoring catalog: Remove Dead Code](https://refactoring.com/catalog/), [Tidy First? (Kent Beck)](https://www.oreilly.com/library/view/tidy-first/9781098151232/)

### 9. Long parameter list / Data clumps
- **What to look for**: 5 つ以上の引数を取る関数、いつも一緒に渡される引数群（`startDate, endDate, timeZone, calendar` のような）、boolean flag 引数。
- **Why**: 引数順の間違いがバグ源、テスト fixture が肥大化する。引数群は実は **欠落したドメイン概念** を示唆している（Fowler "Data Clumps"）。
- **How to apply in a diff**: 関連引数をオブジェクト/struct/dataclass にまとめる Extract Parameter Object を提案。boolean flag は関数を 2 つに割る（"Replace Parameter with Explicit Methods"）。
- **Source**: [Refactoring catalog: Introduce Parameter Object](https://refactoring.com/catalog/introduceParameterObject.html)

### 10. Flag arguments — boolean で挙動を切り替える関数
- **What to look for**: `render(item, isPreview=True)`、`save(user, dryRun=False)` のような呼び出しで全く違う処理経路を取る関数。
- **Why**: Fowler の明示的 smell。呼び出し側で `render(item, True)` と書かれると、True が何を意味するか call site から消える。
- **How to apply in a diff**: `renderPreview(item)` / `renderFinal(item)` のように関数を分割する。Python なら keyword-only 引数を強制して呼び出しを `render(item, is_preview=True)` に固定する妥協案も提示できる。
- **Source**: [Refactoring catalog: Remove Flag Argument](https://refactoring.com/catalog/removeFlagArgument.html)

### 11. Divergent change / Shotgun surgery
- **What to look for**: 1 つの変更要求で複数のクラス/ファイルを同期して直す必要がある（Shotgun surgery）。逆に 1 つのクラスが無関係な複数の理由で頻繁に変更される（Divergent change）。
- **Why**: コードの境界がドメインの境界と一致していない兆候。両者とも変更コストを指数的に膨らませる。
- **How to apply in a diff**: PR 自体が shotgun surgery なら、責務分離 (Move Method/Field) を別 PR で先行することを Tidy First の発想で提案。1 PR の中で構造変更と振る舞い変更が混在しているなら **分割を必須要求** する（Kent Beck）。
- **Source**: [Refactoring catalog](https://refactoring.com/catalog/), [Tidy First? (Kent Beck)](https://www.oreilly.com/library/view/tidy-first/9781098151232/)

### 12. Deep modules / shallow modules
- **What to look for**: 公開メソッド 1〜2 個で内部に膨大なロジックを抱える「Deep module」は良い兆候。逆に「getter/setter だけのクラス」「ラッパーが薄すぎてただの委譲」「`FooManager` / `BarHelper` のように責務が言語化できない」は shallow module。
- **Why**: Ousterhout の中核命題：モジュールの **利益は実装、コストはインタフェース**。shallow module は学習コストばかりかかって実装で得をしない。
- **How to apply in a diff**: 「このクラスを使う側のコードが、内部実装を知らずに正しく使えるか」を試す。configuration parameter を呼び出し側に押し付けているなら "Pull complexity downward" を提案。逆に **不要な小クラス乱立** (classitis) も指摘する。
- **Source**: [A Philosophy of Software Design (Ousterhout)](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf)

### 13. Public API surface の最小性
- **What to look for**: `public` / `export` されているが 1 箇所からしか呼ばれない関数、used-internally なフィールドが getter 経由で外に出ている、デフォルト引数の組み合わせ爆発、overload の乱立。
- **Why**: 公開した API は **実質永続的**。後で消すには deprecate → 移行期間 → 削除という長い儀式が必要。
- **How to apply in a diff**: 「**この API は今 PR で必要か？**」を問う。No なら private に。Public にする場合は YAGNI を一旦保留して「**1 年後ここを変えたくなった時、後方互換を保ったまま変えられるか**」だけは事前に検討する（Enterprise Craftsmanship: 公開 API は YAGNI の例外）。
- **Source**: [adidas API guidelines: minimal API surface](https://github.com/adidas/api-guidelines/blob/master/general-guidelines/minimal-api-surface.md), [Enterprise Craftsmanship: OCP vs YAGNI](https://enterprisecraftsmanship.com/posts/ocp-vs-yagni/)

### 14. デフォルト引数・オーバーロードの組み合わせ爆発
- **What to look for**: 同じ関数に optional 引数が 5 個以上、デフォルト値が他の引数の値に依存する、互いに排他的なオプションが並んでいる (`use_cache` と `force_refresh`)。
- **Why**: 呼び出しパターン数が組み合わせ爆発し、テスト不能・後方互換維持不能になる。
- **How to apply in a diff**: 互いに排他的なオプションは別関数に。共通設定が多いなら "Replace Parameter With Method" や builder/options-object パターンを提案。
- **Source**: [Refactoring catalog](https://refactoring.com/catalog/)

### 15. Mutability の最小化 — 不変・純粋関数を優先しているか
- **What to look for**: 引数を変更する関数（"out parameter"）、グローバル状態の暗黙的更新、setter が連鎖呼び出しを生む、同じ入力で異なる結果を返す関数（テスト不能）。
- **Why**: 不変データと純粋関数は **テストしやすく、並行化しやすく、推論しやすい**。可変共有状態は heisenbug の主要源。
- **How to apply in a diff**: 戻り値で新オブジェクトを返す形に書き換える、`const`/`final`/`readonly`/frozen dataclass を使う、副作用を関数境界に集めて core ロジックを純粋に保つ（functional core / imperative shell）。ただし **性能要件がある hot path** では in-place 更新の合理性を尊重する。
- **Source**: [Pragmatic Programmer (Hunt & Thomas)](https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/), [Refactoring catalog](https://refactoring.com/catalog/)

### 16. 中間変数（explaining variable）の使い方
- **What to look for**: 1 行に複雑な式が詰め込まれている (`if (user.role == "admin" && user.lastLogin > now() - 86400 && !user.disabled)`)。逆に **使われない一回限りの中間変数の乱用**（`x = 5; return x;`）。
- **Why**: 命名された中間変数はコメント代わりの **意図の説明** になる（Extract Variable refactoring）。ただし無意味な中間変数は読みのジャンプを増やすだけ。
- **How to apply in a diff**: 複雑式は `isActiveAdmin = ...` のような explaining variable に分解する。逆に 1 回しか使われず名前が冗長なだけの変数はインライン化を提案。
- **Source**: [Refactoring catalog: Extract Variable](https://refactoring.com/catalog/extractVariable.html)

### 17. エラーメッセージ・例外の情報量が十分か
- **What to look for**: `raise Exception("error")`、`assert False`、catch しただけで swallow している、ユーザに見せるメッセージにスタックトレースが直接出る、機械可読のエラーコードが無い。
- **Why**: エラー発生時のデバッグコストは **メッセージの質に直結**。曖昧なエラーは現場の SRE/サポートを破壊する。
- **How to apply in a diff**: 「**何が失敗したか・どの入力で・どう回復すべきか**」をメッセージに含める。ユーザ向けと開発者向け（ログ）でメッセージレベルを分ける。例外チェーン (`raise ... from e`) で原因を保つ。
- **Source**: [Pragmatic Programmer](https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/), [Google eng-practices](https://google.github.io/eng-practices/review/reviewer/looking-for.html)

### 18. Over-engineering / 投機的汎化 (Speculative Generality)
- **What to look for**: 「将来使うかも」で追加された interface、1 実装しかない abstract class、unused configuration parameter、未使用の plugin point、generic 型パラメータが過剰。
- **Why**: Google eng-practices の reviewer 心得："**Encourage developers to solve the problem they know needs to be solved now, not the problem that the developer speculates might need to be solved in the future**"。汎化は実際の use case 3 件を見てから（Rule of Three）。
- **How to apply in a diff**: 「**この抽象化を使う 2 番目の caller は今のコードベースに居るか？**」を質問する。居なければ削除を提案。
- **Source**: [Google eng-practices: looking-for (Complexity)](https://google.github.io/eng-practices/review/reviewer/looking-for.html), [Premature Generalization (deparkes)](https://deparkes.co.uk/2017/11/03/premature-generalization/)

### 19. Structural change と behavioral change の混在を分離しているか
- **What to look for**: 1 つの PR の中で「ファイル分割 + 機能追加 + リネーム + バグ修正」が同時に行われている。
- **Why**: Kent Beck "Tidy First?" の核心：構造変更（振る舞いを変えない）と振る舞い変更を **同じコミット/PR で混ぜると、レビュー困難・rollback 困難・bisect 困難** になる。
- **How to apply in a diff**: 構造変更を先に別 PR にする提案を出す。「ファイル移動 + リネーム」だけの PR は **自動承認に近いスピード** でマージできるので、本質的な振る舞い変更レビューに集中できる。
- **Source**: [Tidy First? (Kent Beck)](https://www.oreilly.com/library/view/tidy-first/9781098151232/), [InfoQ: Tidy First (Kent Beck)](https://www.infoq.com/presentations/refactoring-cleaning-code/)

### 20. 一貫性（local consistency）を守っているか
- **What to look for**: 同ファイル内で命名規則が混在、似た処理が片方では try/except、片方では `if err != nil`、片方は同期的・片方は非同期的、import 順や型注釈スタイルの不揃い。
- **Why**: Google スタイルガイドの基本ルール: "**Use common sense and BE CONSISTENT**"。周辺コードと一貫していれば読み手は局所文脈だけ把握すれば良く、不一致は無駄な認知コストを生む。
- **How to apply in a diff**: スタイルガイドにある事項は厳格に。スタイルガイドに無い事項は「周辺の既存スタイルに合わせる」のが原則で、好み（スペース vs タブ哲学、関数 vs クラス）で reject しない。
- **Source**: [Google Style Guides](https://google.github.io/styleguide/), [Google eng-practices: standard](https://google.github.io/eng-practices/review/reviewer/standard.html)

### 21. テスト可能性 — ユニットテスト可能な粒度か
- **What to look for**: グローバル状態への暗黙依存、現在時刻 / random / network / FS への直接依存、private メソッドにしかロジックが無く public は薄いラッパー、constructor 内で重い初期化。
- **Why**: テストできないコードは **保守時に変更を恐れさせる**。Ousterhout も "**unknown unknowns**" の主因として挙げる。
- **How to apply in a diff**: 副作用を依存注入 (DI) で外から差し替え可能にする、現在時刻 / 乱数は Clock/RNG オブジェクト経由にする。ただし **小さなスクリプト / 一回限りのジョブ** にまで強要しない（YAGNI と過剰設計のバランス）。
- **Source**: [Software Engineering at Google ch.9](https://abseil.io/resources/swe-book/html/ch09.html), [A Philosophy of Software Design](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf)

### 22. TODO / FIXME / HACK の管理
- **What to look for**: 所有者・チケット番号・期限のない TODO、何年も前の FIXME、`// HACK: don't ask` のような意味不明コメント。
- **Why**: 無主の TODO は **永遠に放置される** ことが知られている (Google eng-practices: "clean up later" のアンチパターン)。
- **How to apply in a diff**: `TODO(username, ISSUE-1234, 2026-Q4): ...` の形式を要求する。期限切れの古い TODO はこの PR で削除 or 解消 or 再オーナーアサインを促す。
- **Source**: [Google Python Style Guide: TODO comments](https://google.github.io/styleguide/pyguide.html), [Google eng-practices: looking-for](https://google.github.io/eng-practices/review/reviewer/looking-for.html)

## Anti-patterns to avoid in review

レビュワー自身が陥りやすい「**過剰指摘**」を意識的に避ける。Google eng-practices の "Perfect ではなく Better" 原則の運用。

1. **Bikeshedding on names** — `userCount` vs `numUsers` のように **どちらでも意味が通る** 命名で議論を引き延ばす。Google: 「Aspects of software design are almost never a pure style issue」だが、**逆に純粋に好みの問題は議論不要**。スタイルガイドに無い命名好みは "Nit:" プレフィックスをつけて非ブロッキングに。

2. **Style nits を blocking として出す** — フォーマッタや linter で自動化できる事項を人間が指摘する。`black` / `prettier` / `gofmt` を CI に入れ、人間レビューはセマンティクスに集中する。スペース・改行・import 順を blocking change request にしない。

3. **"もっと関数型で書け" / "もっと OOP で書け" の押し付け** — 動いている命令型ループを reduce/map に書き換えろ、あるいはその逆。パラダイム趣味の押し付けは PR の目的を歪める。**現コードベースの慣習に従っているか** だけを基準にする。

4. **自明なコードへのコメント強要** — `i = 0  # initialize counter` のような what-comment を要求する。Stack Overflow Rule 2: 「Good comments do not excuse unclear code」。自明なら **コメントは害**。

5. **1 箇所でしか使われない private helper の抽出強要** — 「3 行あるから関数に切り出せ」と機械的に要求する。Shallow module / Classitis (Ousterhout) を増やすだけ。**3 回目で抽象化** (Rule of Three) を基準にする。

6. **"将来のために" 抽象化を要求する** — interface 化・generic 化・plugin point 追加を speculation で要求する。Google eng-practices "**avoid over-engineering**" の真逆。YAGNI 違反の口実を作らせない。

7. **個人攻撃・受動攻撃的コメント** — "Why did you write this?" "Did you even test?" のような developer 自身への言及。Google: "**always making comments about the code and never making comments about the developer**"。事実と影響を述べる文に書き換える。

8. **"clean up later" を理由に LGTM 要求を呑む** — Google eng-practices: "**usually unless the developer does the clean up immediately after the present CL, it never happens**"。後でやる宣言を受け入れず、この PR でやるか別 PR をブロッカーとして紐付ける。

## Gap analysis

リポジトリ `/home/ubuntu/ai-code-review-skills/prompts/` には現在 `coordinator.md` / `coverage.md` / `performance.md` / `security.md` / `sre.md` のみが存在し、**`maintainability.md` プロンプトは欠如**している。本ベストプラクティス文書を基に以下の骨子で生成すべき：

```markdown
# Maintainability Reviewer Prompt (skeleton)

ROLE: You are a senior maintainability reviewer. You read code as future
maintainers will, not as the current author does.

PRIORITY (in order):
1. Naming & readability of new symbols
2. Complexity hotspots (CC > 10, nesting > 3, function > 100 lines)
3. Comments: WHY only, no WHAT, no stale
4. Duplication (Rule of Three) & speculative generality (YAGNI)
5. Public API surface minimality
6. Mutability / testability of new code
7. Structural-vs-behavioral change separation (Tidy First)

OUTPUT FORMAT:
- For each finding, include: file:line, smell category from Fowler's
  catalog, severity {blocking, suggestion, nit}, concrete refactor.
- Use "Nit:" prefix for non-blocking style/preference comments.
- Approve (LGTM) when current state is better than baseline, even if
  not perfect (Google "Perfect-vs-Better" rule).

ANTI-PATTERNS TO AVOID:
- Do not bikeshed names where either choice is acceptable.
- Do not demand comments on self-explanatory code.
- Do not request extraction of single-use private helpers.
- Do not push paradigm preferences (functional vs imperative).
- Do not accept "I'll clean up later" — block or file a tracked issue.

INPUTS: <diff>, <file context>, <language style guide>
```

このプロンプトは Coordinator から `maintainability` 分担で呼び出され、`performance` / `security` / `sre` / `coverage` と並列実行される想定。

## References

### 一次資料（書籍）
- Winters, Manshreck, Wright — *Software Engineering at Google* (O'Reilly, 2020) — [Chapter 9: Code Review (free HTML)](https://abseil.io/resources/swe-book/html/ch09.html)
- John Ousterhout — *A Philosophy of Software Design* (2nd ed.) — [free chapter PDF](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf)
- Martin Fowler — *Refactoring: Improving the Design of Existing Code* (2nd ed.) — [book page](https://martinfowler.com/books/refactoring.html), [online catalog](https://refactoring.com/catalog/)
- Kent Beck — *Tidy First? A Personal Exercise in Empirical Software Design* (O'Reilly, 2023) — [book page](https://www.oreilly.com/library/view/tidy-first/9781098151232/)
- Andy Hunt & Dave Thomas — *The Pragmatic Programmer (20th Anniversary Edition)* — [book page](https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/)
- Robert C. Martin — *Clean Code* — **caveat**: 命名・関数長・コメント章は有用だが、SRP の極端な解釈や継承パターン推奨は Ousterhout の Shallow Module 警告と矛盾するため批判的に読む

### Google 一次資料
- [Google eng-practices: The Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html)
- [Google eng-practices: What to look for in a code review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
- [Google eng-practices: How to write code review comments](https://google.github.io/eng-practices/review/reviewer/comments.html)
- [Google eng-practices: Speed of Code Reviews](https://google.github.io/eng-practices/review/reviewer/speed.html)
- [Google Style Guides (hub)](https://google.github.io/styleguide/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html)
- [Gemini Code Assist style guide](https://developers.google.com/gemini-code-assist/docs/code-review-style-guide)

### Cross-check スタイルガイド
- [LLVM Coding Standards](https://llvm.org/docs/CodingStandards.html)
- [Chromium C++ style](https://chromium.googlesource.com/chromium/src/+/HEAD/styleguide/c++/c++.md)

### コメント・複雑度・DRY
- [Stack Overflow: Best practices for writing code comments](https://stackoverflow.blog/2021/12/23/best-practices-for-writing-code-comments/) — Peter Vogel's 9 rules
- [Cyclomatic complexity (Wikipedia)](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
- [McCabe NIST 235r — Cyclomatic Complexity testing methodology (PDF)](https://www.mccabe.com/pdf/mccabe-nist235r.pdf)
- [Cognitive vs Cyclomatic Complexity (Packmind)](https://dev.to/packmind/cyclomatic-complexity-and-cognitive-complexity-4c03)
- [DRY (Wikipedia)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself)
- [AHA Programming — Kent C. Dodds](https://kentcdodds.com/blog/aha-programming)
- [Code Smell — Martin Fowler bliki](https://martinfowler.com/bliki/CodeSmell.html)

### Microsoft
- [Microsoft Engineering Playbook — Code Reviews](https://microsoft.github.io/code-with-engineering-playbook/code-reviews/)

### YAGNI / Premature Generalization
- [Enterprise Craftsmanship — OCP vs YAGNI](https://enterprisecraftsmanship.com/posts/ocp-vs-yagni/)
- [Premature Generalization (deparkes)](https://deparkes.co.uk/2017/11/03/premature-generalization/)
- [adidas API guidelines — minimal API surface](https://github.com/adidas/api-guidelines/blob/master/general-guidelines/minimal-api-surface.md)
