---
title: Code Review Best Practices — Aggregated Reference
last_reviewed: 2026-05-13
scope: 8 review lenses, 180 checklist items, primary-source-backed
---

# Code Review Best Practices

`prompts/` のレビュアープロンプトを精緻化するために、業界で広く受け入れられているコードレビューのベストプラクティスを **8 つの観点 × 計 180 項目** に分けて整理しました。各項目は **1 件以上の一次情報**（公式ドキュメント・著名エンジニアリングブログ・OWASP/NIST/SLSA 等の標準）に紐づいています。

## ファイル一覧

| # | 観点 | 項目数 | 既存 prompt | 代表的な出典 |
| --- | --- | ---: | --- | --- |
| [01](./01-security.md) | Security | 25 | [security.md](../../prompts/security.md) ✅ | OWASP Top 10 / ASVS / CWE Top 25 / NIST SSDF / OWASP LLM Top 10 |
| [02](./02-performance.md) | Performance | 20 | [performance.md](../../prompts/performance.md) ✅ | Google eng-practices / Brendan Gregg / Martin Thompson / AWS Well-Architected |
| [03](./03-sre.md) | SRE / Reliability | 24 | [sre.md](../../prompts/sre.md) ✅ | Google SRE Book / AWS Builders' Library / Honeycomb / OpenTelemetry |
| [04](./04-coverage.md) | Test Coverage | 21 | [coverage.md](../../prompts/coverage.md) ✅ | Google Testing Blog / xUnit Test Patterns / Stryker / Hypothesis |
| [05](./05-architecture.md) | Architecture | 22 | **未整備** ❌ | Ousterhout APoSD / Fowler / Sam Newman / Vernon DDD |
| [06](./06-dependencies.md) | Dependencies / Supply Chain | 21 | **未整備** ❌ | SLSA / OpenSSF Scorecard / NIST SSDF / Sigstore / CISA SBOM |
| [07](./07-maintainability.md) | Maintainability / Readability | 22 | **未整備** ❌ | Google eng-practices / SE at Google / Fowler Refactoring / Kent Beck Tidy First |
| [08](./08-api-contract.md) | API Contract / Backward Compat | 25 | **未整備** ❌ | Google AIP / Stripe API design / Protobuf style guide / Hyrum's Law |

合計: **180 チェック項目 / 8 観点 / 既存 prompt 4 観点 + 未整備 4 観点**

## 全観点に共通する原則

各観点を読み比べて浮かび上がった、横断的に効くレビュー方針:

1. **「悪用可能か / 障害になるか / クライアントを壊すか」が判定基準** — 理論上の可能性ではなく、到達可能な失敗経路を要求する（Security §critical の定義、SRE の failure_scenario、API contract の breaking change 判定が全て同じ思想）。
2. **diff 単体ではなく境界で見る** — 信頼境界（Security）、モジュール境界（Architecture）、トランザクション境界（Architecture）、契約境界（API contract）、依存境界（Dependencies）。境界をまたぐ変更が最も高シグナル。
3. **観測可能性 = レビュー対象** — 「壊れたあと原因が分かるか」を要件として明示する観点が SRE / Coverage / Maintainability の 3 ヶ所に登場（structured logging のフィールド設計、テストの失敗メッセージ、エラーメッセージの言語化）。
4. **False positive を明示する** — 8 ファイル全てに `Anti-patterns to avoid in review` 章を置き、AI レビュアーが過剰検出しがちなパターン（style nit / 既知 false positive）を列挙。これがないと、レビュアーが信頼を失う。
5. **出典必須** — 「業界の通説だから」ではなく **誰がいつどこで言ったか** を残す。AI が誤情報を生成しても、ベース文書を辿れば訂正できる。

## 既存 prompt とのギャップ要点

各 Gap analysis 章の要約。詳細は個別ファイルへ。

### Security (01) — 既存 prompt に対する追加候補
- カテゴリ追加: `ssrf` / `deserialization` / `csrf` / `sensitive_logging` / `prompt_injection` / `ci_cd_injection` / `mass_assignment` / `open_redirect` / `jwt_alg_confusion`
- 出力スキーマに `<cwe>` 追加（CWE-XXX で機械集計可能化）
- `critical` の severity 定義に「具体的な untrusted-source → sink 経路の特定」を要求

### Performance (02) — 既存 prompt に対する追加候補
- カテゴリ追加: `blocking_io` / `unbounded` / `chatty_interface` / `db_index` / `contention` / `payload_size`
- severity 基準に **p99 / tail latency** を明示（平均だけで判断しない）

### SRE (03) — 既存 prompt に対する追加候補
- カテゴリ追加: `idempotency` / `dlq` / `slo_alignment` / `runbook_alert`
- Task に **ODD（Observability-Driven Development）視点**: 「この変更を観測できる計測点が増えているか」
- severity に **MTTR 増加幅の定量** を要求

### Coverage (04) — 既存 prompt に対する追加候補
- enum 追加: `assertion_quality` / `mutation_readiness` / `concurrency_test` / `property_based_candidate`
- severity 基準に **「セキュリティ・金銭計算パスは critical」** を明示
- `change_detector_test` （実装の鏡写し）を anti-pattern 章に追加

### Architecture (05) — 新規 prompt 推奨
未整備。`05-architecture.md` の Gap analysis 章に 8 項目のスケルトンあり（モジュール境界 / 結合・凝集 / Deep module / API surface / DIP / 横断的関心事 / ACL / トランザクション境界）。

### Dependencies (06) — 新規 prompt 推奨
未整備。`06-dependencies.md` のスケルトンに沿うと、対象 diff が **package.json / pyproject.toml / go.mod / Cargo.toml / lockfile** を含むときだけ起動する条件付きレビュアーとして実装するのが現実的。

### Maintainability (07) — 新規 prompt 推奨
未整備。**ただし注意**: この観点は最も false positive を生みやすい。スケルトンには `Anti-patterns` を最初に書き、bikeshedding / single-use helper の抽出要求 / paradigm pushing を明示的に禁じる構造を提案。

### API Contract (08) — 新規 prompt 推奨
未整備。**最もコスト効率が高い追加候補**: breaking change 1 件で全クライアントを巻き込むため、検出できれば顕著な実害回避になる。対象 diff が OpenAPI / protobuf / GraphQL SDL / DB migration / 公開 SDK のいずれかを含むときに起動する条件付き設計を推奨。

## 推奨されるロードマップ

`prompts/` への反映優先度（投資対効果順）:

1. **API Contract (08)** — 新規追加、最高ROI。breaking change 1 件あたりの実害が大きいため
2. **Security (01) の gap 反映** — CWE タグと追加カテゴリだけでも先に入れる
3. **Dependencies (06)** — 新規追加。条件付き起動（lockfile / manifest 変更時のみ）でコスト抑制
4. **SRE (03) の gap 反映** — `idempotency` / `dlq` の追加
5. **Performance (02) の gap 反映** — p99 と `unbounded` カテゴリ
6. **Architecture (05)** — 新規追加（重要だが false positive リスク高、慎重に）
7. **Coverage (04) の gap 反映**
8. **Maintainability (07)** — 最後。**意図的に保守的に組む**（false positive 多発の最大要因）

## 更新ガイドライン

- このディレクトリのファイルは **半年に 1 回**、`last_reviewed:` を更新しつつ各リンクの 404 と内容変化をチェックする
- 新しい一次情報源（標準、著名ブログ、業界事故）が出たら該当ファイルに追記し、既存項目を rerank する
- prompt と doc は **片方だけ更新しない**（doc を直したら prompt も同方向に直すか、逆も同じ）
