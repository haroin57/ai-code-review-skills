---
title: Test Coverage Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://testing.googleblog.com/2020/08/code-coverage-best-practices.html
  - https://martinfowler.com/articles/practical-test-pyramid.html
  - http://xunitpatterns.com/
  - https://stryker-mutator.io/docs/
  - https://www.thoughtworks.com/en-au/radar/techniques/mutation-testing
  - https://microsoft.github.io/code-with-engineering-playbook/automated-testing/unit-testing/
  - https://www.hillelwayne.com/post/pbt-contracts/
  - https://hypothesis.readthedocs.io/
  - https://jqwik.net/property-based-testing.html
---

# Test Coverage Code Review Best Practices

## Why this matters
カバレッジ率（line %）は「テストが実行した行」を測るだけで、「テストがバグを検出できるか」は測らない。100% line coverage でも assertion が弱ければ mutation はほぼ生き残り、本番障害は防げない[1][4]。Google も「coverage は test gap の指標であって test quality の指標ではない」と明言しており、レビュアーは数値ではなく **どの failure class が検知できないか** を見る必要がある[1][2]。

## Review checklist

### 1. 新規/変更ロジックに対応する test が同一 PR に含まれているか
- **What to look for**: production code の追加・変更があるのに test file が touch されていない PR。`'I'll add tests next'` のコメント。
- **Why**: test を後追いにすると PR レビュー時点の意図が失われ、regression net がない状態でマージされる。Microsoft Playbook は "Tests should always be committed in the same PR as the code itself" と明記[6]。
- **How to apply in a diff**: diff の production file に対応する test file の diff が存在するか確認。`src/foo.ts` の変更に対し `test/foo.spec.ts` または同等の change が無ければ flag。
- **Test scenario suggestion**: 新規 public function の happy path + 主要 branch を最低 1 ケースずつ。
- **Source**: [Microsoft Code-With Engineering Playbook — Reviewer Guidance](https://microsoft.github.io/code-with-engineering-playbook/code-reviews/process-guidance/reviewer-guidance/)

### 2. 境界値（boundary）の test が存在するか
- **What to look for**: range / length / index / threshold を使う条件文（`x >= 18`, `arr.length > 0`, `i < n`）に対し、`min-1, min, min+1, max-1, max, max+1` のいずれかが欠けている。
- **Why**: バグの多くは境界の比較演算子ミス（`<` vs `<=`）や off-by-one で発生する。Myers 以来の経験則[7]。
- **How to apply in a diff**: 不等号・配列インデックス・loop bound を変更している箇所に、境界 input を与える test ケースが追加されているか確認。
- **Test scenario suggestion**: `age == 17, 18, 65, 66`、`list = [], [single], full, full+1` の robust BVA セット。
- **Source**: [GeeksforGeeks — Boundary Value Analysis](https://www.geeksforgeeks.org/software-testing/software-testing-boundary-value-analysis/)

### 3. Error path / 例外パスがカバーされているか
- **What to look for**: `try/except`, `if (err != nil)`, `Result::Err`, custom exception raise などのエラー分岐に test が当たっていない。happy path だけの test 群。
- **Why**: production 障害の多くは正常系ではなく **想定外入力 / 下流障害** で発生する。Google は "exercise normal, edge case, AND failure scenarios" を coverage 必須条件としている[1]。
- **How to apply in a diff**: error branch の各 raise/return に対し、それを trigger する test が同 PR にあるか。`pytest.raises(...)` / `assertThrows(...)` の有無。
- **Test scenario suggestion**: 下流 API が 500 / timeout / malformed JSON を返したときの挙動、不正型・null・空文字の入力。
- **Source**: [Google Testing Blog — Code Coverage Best Practices](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)

### 4. Bug fix PR に regression test がついているか
- **What to look for**: "fix: ..." commit で production code は変わっているが、その bug を再現する test が追加されていない。
- **Why**: Kent Beck の TDD bug-fix workflow は **「まず bug を露呈する failing test を書く → fix」**。test なしの fix は同じバグの再発を防げない[8]。
- **How to apply in a diff**: fix commit に対し test file の追加行があり、その test が「fix 前のコードでは fail する」内容になっているか（コメントや issue ID 参照があると望ましい）。
- **Test scenario suggestion**: 報告された input そのものを使った reproduction test。issue 番号を test 名に含める。
- **Source**: [Kent Beck — Test-Driven Development by Example (notes)](https://adamtuttle.codes/blog/2021/tdd-by-example-kent-beck/)

### 5. Property-based testing が向く箇所で example-based のみになっていないか
- **What to look for**: parser / serializer / encoder-decoder pair / sort / 数値関数 / 集合演算など **invariant が言える** ロジックに example test だけしかない。
- **Why**: 例ベースは「思いついた入力」しか試さない。`decode(encode(x)) == x`, `sort(xs)` は permutation を保つ、などの property は Hypothesis/jqwik が 1000+ ケース自動生成し shrinking で minimal failing case まで提示してくれる[9][10]。
- **How to apply in a diff**: 上記のような関数で `@given` / `@Property` / `forAll` の使用がないなら suggestion を出す。逆に already PBT がある箇所では tries 数・seed 固定の妥当性を確認。
- **Test scenario suggestion**: `@given(st.lists(st.integers()))` で `sorted(sorted(xs)) == sorted(xs)` (idempotence) や round-trip property。
- **Source**: [Hypothesis docs — What is Property-Based Testing](https://hypothesis.readthedocs.io/en/latest/quickstart.html) / [jqwik — Property-Based Testing](https://jqwik.net/property-based-testing.html)

### 6. Mutation testing で生き残る test を許容していないか
- **What to look for**: assertion が `assertNotNull(result)` だけ、`verify(mock).called()` だけ、戻り値の型しか見ていない test。Stryker/PIT を回すと boundary mutator・conditional mutator が大量に survive する形。
- **Why**: 「テストは pass するが mutant は kill されない」状態 = test がバグを検知できない。ThoughtWorks Radar は mutation testing を coverage の代替指標として ADOPT 級で推奨[4][5]。
- **How to apply in a diff**: critical logic (pricing, auth, money, security check) の test で assertion が値の中身まで verify しているか。`assert result == expected` の形になっているか。
- **Test scenario suggestion**: 計算結果の **具体値** を assert。境界（`<` → `<=` mutation）をキルする input 2 点を追加。
- **Source**: [ThoughtWorks Technology Radar — Mutation Testing](https://www.thoughtworks.com/en-au/radar/techniques/mutation-testing) / [Stryker Mutator Docs](https://stryker-mutator.io/docs/)

### 7. Assertion が存在するか / Assertion Roulette になっていないか
- **What to look for**: test body に assertion が無い（実行できれば pass）、または assertion が 10 個並んでいて failure 時にどれが落ちたか分からない。
- **Why**: Meszaros の Behavior Smell "Assertion Roulette"。1 test 内に複数の独立したアサーションがあると失敗箇所の特定に時間がかかり、最初の fail で後続が実行されない場合は本当の問題を隠す[3]。
- **How to apply in a diff**: 追加された test 関数すべてに最低 1 つの assertion があるか。`expect/assert` 0 個の test は flag。複数 assertion はメッセージ付きか、ケース分割すべきでないか確認。
- **Test scenario suggestion**: 1 test = 1 scenario に分解し、assertion に message を付ける。
- **Source**: [xUnitPatterns — Assertion Roulette](http://xunitpatterns.com/Assertion%20Roulette.html)

### 8. Flaky / Erratic test を生む依存（時計・乱数・network・順序）を排除しているか
- **What to look for**: test 内で `new Date()`, `Math.random()`, 実 HTTP、ファイルシステムへの直アクセス、外部 DB を抽象化せず使っている。並列実行で順序依存になる shared state。
- **Why**: Meszaros の "Erratic Test" smell。flaky test は CI を信頼不能にし、最終的に "retry until green" 文化を生む[3]。
- **How to apply in a diff**: 新規 test が wall clock / 実乱数 / 実 network を踏んでいないか。clock は injectable / virtual clock 化、random は seed 固定、HTTP は fake/stub を使っているか。
- **Test scenario suggestion**: `Clock` を DI して `FakeClock(2026-05-13)` を注入。`Random(seed=42)`。HTTP は `responses` / `WireMock`。
- **Source**: [xUnitPatterns — Erratic Test](http://xunitpatterns.com/Erratic%20Test.html)

### 9. Over-mocking / interaction-only test になっていないか
- **What to look for**: `verify(mock).methodA(); verify(mock).methodB(); verify(mock, times(3)).methodC();` のように呼び出しの順序や回数だけを検証し、**最終的な結果（戻り値・状態変化・外部副作用）** を assert していない test。mock が mock を返すような nested mock。
- **Why**: 実装詳細に couple した brittle test を生む。refactor のたびに test 修正が必要になり、結局「production と test を両方書き換える」二重保守になる。Google は "Test state, not interactions" を推奨[11]。
- **How to apply in a diff**: 新規 test の assertion が `verify(...)` だけで end-result の検証が無いなら flag。mock を 3 つ以上 stub している test は SUT の責務過多のサインとして design 改善を suggest。
- **Test scenario suggestion**: collaborator が観測可能な outcome（returned value, persisted row, emitted event）を assert する形に書き換える。stub には verify を当てない。
- **Source**: [Google Testing Blog — Testing State vs. Testing Interactions](https://testing.googleblog.com/2013/03/testing-on-toilet-testing-state-vs.html)

### 10. Test に conditional logic / loop が入っていないか
- **What to look for**: test 関数の中に `if`, `for`, `try/except` が含まれており、テスト自身が分岐していて何を検証したか実行ごとに変わる。
- **Why**: Meszaros の "Conditional Test Logic" は Buggy Test の主要原因。test に logic があると「test 自体のバグ」のリスクが production と同等になり、test を信頼できなくなる[3][12]。
- **How to apply in a diff**: 追加 test に if/for があるなら parameterized test (`@pytest.mark.parametrize`, `@ParameterizedTest`) への分解を suggest。
- **Test scenario suggestion**: 入力・期待値を直書きしたケースに展開。1 case = 1 直線的な arrange-act-assert。
- **Source**: [Google Testing Blog — Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html)

### 11. Test が独立して実行可能か（test isolation）
- **What to look for**: test の実行順を変えると fail する、`@Test` 間で shared mutable state（class variable, singleton, real DB row）に依存している、`setUp` が前 test の副作用を仮定している。
- **Why**: order dependence は CI で並列化したりランダムシャッフル（pytest-randomly, junit-random-order）したときに突然壊れる。Microsoft Playbook の unit test 必須条件 "Isolated"[6]。
- **How to apply in a diff**: 新規 test が module-level state, static field, env var, file system 共有を書き換えていないか。teardown / fixture scope が適切か。
- **Test scenario suggestion**: 各 test で独自 fixture を生成、shared resource は `function`-scope fixture か transactional rollback。
- **Source**: [Microsoft Engineering Playbook — Unit Testing](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/unit-testing/)

### 12. Fixture setup が "Mystery Guest" になっていないか
- **What to look for**: test 本体だけ読んでも入力データが何か分からない。外部ファイル（`fixtures/users.json`）や DB seed に依存し、test が暗黙的 input に頼っている。
- **Why**: Meszaros の "Mystery Guest" code smell。fixture が test から見えないと、test 失敗の原因究明に時間がかかり Fragile Test の温床になる[3]。
- **How to apply in a diff**: 新規 test が external fixture を使うなら、test 本体内で関連 field を明示してから act する `Test Data Builder` パターンを推奨。
- **Test scenario suggestion**: `aUser().withAge(18).build()` のような builder で test 内に意図を表現。
- **Source**: [xUnitPatterns — Mystery Guest](http://xunitpatterns.com/Mystery%20Guest.html)

### 13. 並行処理コードに concurrency test があるか
- **What to look for**: 新規に thread / async task / shared mutable state / lock を導入しているのに、test は単一スレッドの正常系のみ。
- **Why**: race condition は単発実行ではほぼ顕在化せず、production 負荷下で初めて発火する。MIT 6.031 が示すとおり標準 unit test では thread safety を検証できない[13]。
- **How to apply in a diff**: `synchronized` / `Mutex` / `atomic` / `goroutine` / `asyncio` の追加に対し、(a) 並列に走らせて invariant 検証する stress test、(b) ThreadSanitizer / `-race` flag 付き CI、(c) lock 順序の review を要求。
- **Test scenario suggestion**: N スレッドから同時に呼び出して最終 state の invariant（合計 = N、ユニーク ID の重複なし）を assert する property test。
- **Source**: [MIT 6.031 — Thread Safety](https://web.mit.edu/6.031/www/sp21/classes/21-thread-safety/)

### 14. Slow test が unit suite に紛れ込んでいないか
- **What to look for**: 1 test に 1 秒以上かかる、suite 全体で数分かかる、test 内で `sleep(...)` を使って async を待っている。
- **Why**: Meszaros の "Slow Test" smell。unit suite は数秒以内で回らないと開発者が回さなくなり、結果的に test の価値が消える[3]。Microsoft Playbook も "Fast - should run in milliseconds"[6]。
- **How to apply in a diff**: 新規 test に `Thread.sleep`, `await new Promise(r => setTimeout(r, 5000))`, 実 DB 起動などがあるなら integration suite 側への移動か fake への置換を suggest。
- **Test scenario suggestion**: 時間依存は virtual clock、async は `await` + deterministic scheduler、DB は in-memory / testcontainers の reuse。
- **Source**: [xUnitPatterns — Slow Tests](http://xunitpatterns.com/Slow%20Tests.html)

### 15. Test Pyramid の歪み（ice-cream cone / hourglass）を起こしていないか
- **What to look for**: 1 PR で E2E test だけを大量追加、unit test ゼロ。あるいは整合性のために遅い integration test を増やしている。
- **Why**: Fowler が示すとおり、上位層が太いと feedback loop が遅く flaky になりやすい。pyramid 形を保つことで保守性と速度の両立が得られる[2]。
- **How to apply in a diff**: 同じ振る舞いを検証するのに E2E しか書かれていない場合、より低い層（unit / contract test）に分解できるか質問。
- **Test scenario suggestion**: ビジネスルールは unit、HTTP の wiring は narrow integration、ユーザーフローのみ E2E。
- **Source**: [Martin Fowler — The Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html)

### 16. Change-detector test（実装の写経）になっていないか
- **What to look for**: production code と 1:1 で同じ構造を assert しているだけ。private method の呼び出し回数を verify、出力を全フィールド verify。
- **Why**: Google が "Change-Detector Tests Considered Harmful" で警告する通り、refactor のたびに test を直す必要が生じ safety net としての価値がない[14]。
- **How to apply in a diff**: assertion が「振る舞い」ではなく「内部構造の文字列一致」になっていないか。`toMatchSnapshot()` を新規追加する場合は意図を確認。
- **Test scenario suggestion**: public contract / observable behavior のみ assert。snapshot は意味のある単位に絞る。
- **Source**: [Google Testing Blog — Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)

### 17. Coverage 報告が branch / condition レベルか
- **What to look for**: CI で line coverage しか見ていない。`isSquare(s) || (isBlue(s) && !isCircle(s))` のような複合条件で一部の組み合わせしか test されていない。
- **Why**: Google のガイドは「line coverage では `||` の右辺が全く test されていなくても 100% に見える」と警告し、branch + condition coverage を推奨[1]。
- **How to apply in a diff**: 複合 boolean 条件を追加・変更した PR では、各 sub-condition の true/false 組み合わせをカバーする test があるか確認。
- **Test scenario suggestion**: MC/DC（修正条件判定カバレッジ）相当 — 各サブ条件が独立に結果を変える input を 1 ペアずつ。
- **Source**: [Google Testing Blog — Code Coverage Best Practices](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)

### 18. Contract / invariant が言える箇所で contract test が無いか
- **What to look for**: pre/post-condition が明確な関数（`balance >= 0`, `len(out) == len(in)`）に runtime assertion も property test もない。
- **Why**: Hillel Wayne が示すとおり、contract + PBT の組み合わせは "integration test as fuzzer" として極めて強力で、契約違反が caller / callee どちらにも検出可能になる[15]。
- **How to apply in a diff**: 数値・コレクション・ステートマシンを扱う関数で、`assert` / `dpcontracts` / `@require/@ensure` がなく、test も example だけなら contract 追加を suggest。
- **Test scenario suggestion**: post-condition を sanity check として埋め込み、Hypothesis で random input を流し contract 違反を検出。
- **Source**: [Hillel Wayne — Property Tests + Contracts = Integration Tests](https://www.hillelwayne.com/post/pbt-contracts/)

### 19. Test name が intent を表しているか
- **What to look for**: `test1`, `testFoo`, `it works` のような名前。失敗時にどの仕様が壊れたか分からない。
- **Why**: test 名はライブドキュメント。`shouldReject_whenAgeIsBelow18` のように given/when/then を含む名前は failure 通知だけで原因の当たりがつく。Microsoft Playbook も推奨[6]。
- **How to apply in a diff**: 新規 test 関数名が条件と期待結果を含むか。テンプレ: `<method>_<condition>_<expectedResult>`。
- **Test scenario suggestion**: `withdraw_whenBalanceInsufficient_throwsInsufficientFundsError`。
- **Source**: [Microsoft Playbook — Unit Testing](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/unit-testing/)

### 20. Security / auth / money 系コードに critical-severity の test gap がないか
- **What to look for**: 認証・認可・課金・暗号化・PII 取扱いの critical path に test が無い、または happy path のみ。
- **Why**: これらは failure mode が即インシデント。Google の coverage best practice も "critical code requires higher bar"、ThoughtWorks も "focus mutation testing on critical paths" を推奨[1][4]。
- **How to apply in a diff**: `@Authorize`, password 比較, signature verify, payment charge などのキーワードを含む追加コードに対応する negative test（権限なし、署名不一致、二重課金）があるか確認。
- **Test scenario suggestion**: 認可: 他人の resource アクセス → 403。署名: tampered payload → reject。課金: idempotency key 同一 → 1 回のみ課金。
- **Source**: [Google Testing Blog — Code Coverage Best Practices](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)

### 21. Snapshot / golden file test が hygienic に管理されているか
- **What to look for**: `__snapshots__/` が PR 内で大量更新されている、レビュアーが差分を読まずに承認、生成時刻や乱数を含む snapshot。
- **Why**: snapshot を毎回 update する文化は change-detector test の典型例。意味のある差分を埋もれさせる[14]。
- **How to apply in a diff**: snapshot 更新がある PR では「なぜ変わったか」を description に書かせる。non-deterministic な field（timestamp, UUID）はマスクしてから snapshot に取る運用か確認。
- **Test scenario suggestion**: deterministic な serializer を用いる、timestamp は固定 clock、UUID は seeded generator。
- **Source**: [Google Testing Blog — Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)

## Anti-patterns to avoid in review
レビュアー側がやってはいけない false positive。

1. **Trivial getter/setter に test を要求する** — `getName()` をテストしても mutation で kill 価値がない。レビュー時間と test maintenance コストの無駄[1]。
2. **カバレッジ率 % の数値目標だけで pass/fail を判断する** — 80% を満たすために assertion 無し test を量産する逆効果。質を見ること[1][4]。
3. **「test がない」だけを理由に critical でない変更を blocking する** — typo fix、コメント変更、純粋な rename は test を増やす意味がない。scope discipline[6]。
4. **すべての関数に property-based test を要求する** — 単純な CRUD wrapper に PBT は overkill。invariant が言える計算ロジックに限る[9]。
5. **Mock を全否定する** — 外部 API / DB / 時計などは mock/fake が妥当。問題は「内部 collaborator まで mock すること」[11]。
6. **命名規則を細かく指摘する** — intent が伝わるなら snake_case か camelCase かは scope 外。chairperson が拘ると review が炎上する。
7. **100% mutation score を求める** — equivalent mutant や cost-benefit が合わない箇所は残してよい。80% 程度で十分強い指標[4][5]。

## Gap analysis vs current prompt
`prompts/coverage.md` 現状と本ドキュメントの差分。

**Already covered**:
- 新規/変更ロジックの test 有無（item 1）
- 境界値・edge case（item 2）
- error path / 例外（item 3）
- assertion 不足 / over-mock / flaky（item 7, 8, 9）
- trivial getter の除外 / カバレッジ率数値の除外（anti-patterns）

**Missing**:
- mutation testing readiness の観点（item 6）
- property-based testing 候補の検出（item 5, 18）
- regression test for fixed bug（item 4）
- concurrency / thread safety test（item 13）
- conditional logic in tests（item 10）
- mystery guest fixture / test data builder（item 12）
- branch/condition coverage の意識（item 17）
- test pyramid 歪み（item 15）
- change-detector / snapshot 過剰（item 16, 21）
- security/money critical path への critical severity 付与（item 20）

**Suggested additions** to `prompts/coverage.md`:
- `<category>` enum に `concurrency_test`, `property_based`, `regression`, `mutation_survivor` を追加
- severity 基準に「security/money/auth は無条件 critical」を明文化
- 出力フォーマットに `mutation_hint`（どんな mutation が survive しそうか）optional field を追加し、reviewer 行動を bug-detection 寄りに誘導
- "test 自体に logic / conditional がある" を `test_quality` の重要 sub-pattern として例示

## References
1. [Google Testing Blog — Code Coverage Best Practices](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)
2. [Martin Fowler — The Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html)
3. [Gerard Meszaros — xUnit Test Patterns (xunitpatterns.com)](http://xunitpatterns.com/)
4. [ThoughtWorks Technology Radar — Mutation Testing](https://www.thoughtworks.com/en-au/radar/techniques/mutation-testing)
5. [Stryker Mutator — Documentation](https://stryker-mutator.io/docs/)
6. [Microsoft Code-With Engineering Playbook — Unit Testing & Reviewer Guidance](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/unit-testing/)
7. [GeeksforGeeks — Boundary Value Analysis](https://www.geeksforgeeks.org/software-testing/software-testing-boundary-value-analysis/)
8. [Adam Tuttle — Notes on TDD By Example (Kent Beck)](https://adamtuttle.codes/blog/2021/tdd-by-example-kent-beck/)
9. [Hypothesis — Quickstart / What is PBT](https://hypothesis.readthedocs.io/en/latest/quickstart.html)
10. [jqwik — Property-Based Testing](https://jqwik.net/property-based-testing.html)
11. [Google Testing Blog — Testing State vs. Testing Interactions](https://testing.googleblog.com/2013/03/testing-on-toilet-testing-state-vs.html)
12. [Google Testing Blog — Don't Put Logic in Tests](https://testing.googleblog.com/2014/07/testing-on-toilet-dont-put-logic-in.html)
13. [MIT 6.031 — Thread Safety](https://web.mit.edu/6.031/www/sp21/classes/21-thread-safety/)
14. [Google Testing Blog — Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html)
15. [Hillel Wayne — Property Tests + Contracts = Integration Tests](https://www.hillelwayne.com/post/pbt-contracts/)
16. [PIT (Pitest) — Mutation Testing for Java](https://pitest.org/)
17. [xUnitPatterns — Fragile Test](http://xunitpatterns.com/Fragile%20Test.html)
18. [xUnitPatterns — Erratic Test](http://xunitpatterns.com/Erratic%20Test.html)
