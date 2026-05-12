---
title: Dependency / Supply-Chain Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://slsa.dev/spec/v1.0/levels
  - https://www.cisa.gov/sbom
  - https://github.com/ossf/scorecard/blob/main/docs/checks.md
  - https://github.com/actions/dependency-review-action
  - https://docs.sigstore.dev/cosign/verifying/verify/
  - https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html
  - https://www.sonatype.com/state-of-the-software-supply-chain/2024/introduction
  - https://en.wikipedia.org/wiki/XZ_Utils_backdoor
---

# Dependency / Supply-Chain Code Review Best Practices

## Why this matters

サプライチェーン経由の侵害は、もはや「想定外」ではなく定常リスク。Sonatype の 2024 年レポートでは、悪意あるパッケージは前年比 156% 増（**512,847 件**を観測）。アプリの **約 90%** が OSS で構成され、平均で **180 個**の OSS コンポーネントを取り込んでいる ([Sonatype 2024](https://www.sonatype.com/state-of-the-software-supply-chain/2024/introduction))。代表的な実インシデントを念頭に置くと、レビュー観点が腑に落ちる:

- **Log4Shell / CVE-2021-44228 (2021)**: JNDI ルックアップ経由の RCE、CVSS 10。多くの組織が「自分が log4j を使っているかすら分からなかった」=トランジティブ依存の可視化欠落が露呈 ([GitHub Blog](https://github.blog/open-source/inside-the-breach-that-broke-the-internet-the-untold-story-of-log4shell/))。
- **xz-utils / CVE-2024-3094 (2024)**: 2 年以上かけて maintainer 権限を取得した攻撃者 "Jia Tan" が `liblzma` に sshd への RCE backdoor を注入。ソース GitHub には載せず、リリース tarball にのみ仕込んだ ([Wikipedia](https://en.wikipedia.org/wiki/XZ_Utils_backdoor), [arXiv 2504.17473](https://arxiv.org/html/2504.17473v1))。
- **event-stream (2018) / ua-parser-js (2021) / eslint-scope (2018)**: メンテナ譲渡や認証情報漏洩を起点に、`postinstall` script で資格情報・暗号通貨を奪取 ([Datadog Labs](https://securitylabs.datadoghq.com/articles/mut-8964-an-npm-and-pypi-malicious-campaign-targeting-windows-users/))。
- **Codecov bash uploader (2021)**: CI で実行されるシェルスクリプトに環境変数 exfiltration コードが混入。CI に渡された全シークレットが漏洩。
- **axios npm compromise (2026-03)**: 偽の `plain-crypto-js@4.2.1` を `postinstall` で投下し、OS 別 RAT を配布。`npm install` 完了から **2 秒**で C2 通信 ([Microsoft Security Blog](https://www.microsoft.com/en-us/security/blog/2026/04/01/mitigating-the-axios-npm-supply-chain-compromise/))。

レビューは「動くか」だけでなく「**信頼できる出所からきているか / 必要以上の権能を持たないか**」を falsifiable に確認する作業。

## Review checklist

### 1. 新規依存の必要性と代替検討
- **What to look for**: PR で `package.json` / `pyproject.toml` / `go.mod` / `Cargo.toml` / `pom.xml` などに新規追加されたパッケージ。`require()`/`import` 1 行で済む小機能、または標準ライブラリで代替可能なもの。
- **Why**: 依存はアタックサーフェスそのもの。`left-pad`/`is-odd` 級の薄いラッパは攻撃者が乗っ取った際の被害対効果が最悪 ([OWASP NPM Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html))。
- **How to apply in a diff**: manifest の `dependencies` 差分を見て新規追加を抽出。「なぜ自前実装でないか」「標準ライブラリにないか」を PR description に書かせる。
- **Source**: [OWASP NPM Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html)

### 2. メンテナンス健全性シグナル (Scorecard)
- **What to look for**: OpenSSF Scorecard スコア。特に `Maintained`, `Code-Review`, `Branch-Protection`, `Dangerous-Workflow`, `Token-Permissions`, `Signed-Releases`。総合スコア < 5 は要警戒。
- **Why**: Scorecard は automated heuristic で「単独 maintainer」「2FA 無効」「CI 無し」のような赤旗を機械的に検出。xz-utils は単独 maintainer + 低トラフィックという典型条件下で乗っ取られた ([CrowdStrike](https://www.crowdstrike.com/en-us/blog/cve-2024-3094-xz-upstream-supply-chain-attack/))。
- **How to apply in a diff**: GitHub の `dependency-review-action` で `show-openssf-scorecard-levels: true` を有効化。`scorecard.dev/viewer/?uri=github.com/<org>/<repo>` で目視確認。
- **Source**: [OpenSSF Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md), [GitHub Changelog 2024-03-20](https://github.blog/changelog/2024-03-20-openssf-scorecard-info-is-now-available-in-the-dependency-review-action/)

### 3. Typosquatting / Dependency Confusion チェック
- **What to look for**: 既存 popular package と Levenshtein 距離 1〜2 の名前 (`requets`, `python-dateutil` vs `python-datetime`, `lodahs`, `colour` vs `colors`)。private scope なしの新規パッケージで、社内パッケージ名と被るもの。
- **Why**: Ohm らの調査では悪意あるパッケージの **64%** が typosquatting 経由 ([SecurityScientist](https://www.securityscientist.net/blog/12-questions-and-answers-about-typosquatting-pypi-npm-supply-chain/))。PyPI では 2023 年に 1 週間で 10,000+ typosquat が削除された。
- **How to apply in a diff**: 新規依存名を npmjs.com / pypi.org で検索し、ダウンロード数、初回公開日、リポジトリリンクの妥当性を確認。**初回公開から 30 日未満かつ DL 数が極端に少ない**ものはブロック検討。
- **Source**: [Check Point: PyPI Typosquatting Campaign](https://blog.checkpoint.com/securing-the-cloud/pypi-inundated-by-malicious-typosquatting-campaign/), [OSSF malicious-packages DB](https://github.com/ossf/malicious-packages)

### 4. install / post-install / build スクリプトの存在
- **What to look for**: `package.json` の `scripts` セクションに `preinstall`/`install`/`postinstall`/`prepare`、`pyproject.toml` の `[build-system]` カスタムバックエンド、`setup.py` 内の任意コード、`Cargo.toml` の `build = "build.rs"`、`pom.xml` の任意 maven plugin。
- **Why**: axios incident, eslint-scope incident は全て `postinstall` で実行された。`npm install` 完了から数秒で RAT 起動 ([Microsoft 2026-04-01](https://www.microsoft.com/en-us/security/blog/2026/04/01/mitigating-the-axios-npm-supply-chain-compromise/))。`npm ci` も `--ignore-scripts` を渡さない限り script を走らせる点に注意。
- **How to apply in a diff**: 新規依存のソースを `npm view <pkg> scripts` / `npm pack` 後 manifest 確認。**新規依存 + コード上で import されない + install script あり = 高 signal**（リリースブロッカ扱い）。
- **Source**: [Nodejs Security: ignore-scripts](https://www.nodejs-security.com/blog/npm-ignore-scripts-best-practices-as-security-mitigation-for-malicious-packages), [pnpm supply chain security](https://pnpm.io/supply-chain-security)

### 5. lockfile の存在・更新整合性
- **What to look for**: `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`/`Pipfile.lock`/`poetry.lock`/`uv.lock`/`Cargo.lock`/`go.sum` がコミットされているか。`package.json` の変更とロックファイルの差分スコープが乖離していないか（例: 1 個追加なのに 200 行変動）。
- **Why**: lockfile が無いと semver range 解決の度に別バージョンが入る。**lockfile injection** 攻撃では `resolved` URL を攻撃者の registry に書き換える事例あり ([OWASP NPM Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html))。
- **How to apply in a diff**: CI で `npm ci` / `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile` を使用しているか workflow を確認。lockfile の `resolved` フィールドが registry.npmjs.org など信頼できるホストを指しているか確認。
- **Source**: [pnpm install docs](https://pnpm.io/cli/install), [Nesbitt: Lockfile Format Tradeoffs](https://nesbitt.io/2026/01/17/lockfile-format-design-and-tradeoffs.html)

### 6. integrity hash / checksum の存在
- **What to look for**: lockfile の `integrity: sha512-...` (npm/pnpm/yarn)、`hashes` (Pipfile.lock)、`checksum` (Cargo.lock)、`h1:` ハッシュ (go.sum)。空 / 欠損エントリ無し。
- **Why**: integrity hash は registry でのパッケージ差し替えを検知する最後の砦。これが無いと攻撃者が公開後にパッケージ内容を差し替えても気付けない。
- **How to apply in a diff**: lockfile diff で `integrity` フィールドの増減を確認。`pip install --require-hashes` 利用が望ましい。
- **Source**: [cyberphinix: lockfile basics](https://cyberphinix.de/blog/package-lock-json-vs-yarn-lock-vs-pnpm-lock-yaml-basics/)

### 7. バージョン pin 戦略 (exact vs range)
- **What to look for**: アプリケーションでの `^1.2.3` / `~1.2.3` / `>=1.0` などの range 指定。逆にライブラリで `1.2.3` のような完全 pin は依存解決を破壊。
- **Why**: アプリは lockfile + exact pin で再現性を、ライブラリは適切な range で消費側との衝突回避を狙う ([nesbitt.io](https://nesbitt.io/2026/01/17/lockfile-format-design-and-tradeoffs.html))。
- **How to apply in a diff**: package type (application/library) を確認した上で manifest のバージョン演算子を見る。アプリで `latest` / `*` / `>=x` のみは要修正。
- **Source**: [npm semver](https://docs.npmjs.com/about-semantic-versioning), [cyberphinix](https://cyberphinix.de/blog/package-lock-json-vs-yarn-lock-vs-pnpm-lock-yaml-basics/)

### 8. 既知 CVE / Advisory の有無
- **What to look for**: GitHub Advisory Database / OSV / NVD で当該パッケージ・バージョンに既知脆弱性があるか。`fail-on-severity: moderate` 以上で CI ブロック。
- **Why**: Log4Shell 時、99% のパッケージで修正版が存在したが **80% の依存が 1 年以上更新されていなかった** ([Sonatype 2024](https://www.sonatype.com/state-of-the-software-supply-chain/2024/risk))。
- **How to apply in a diff**: 言語別スキャナを CI に組み込む。
  - npm: `npm audit` / `dependency-review-action`
  - Python: `pip-audit` ([pypa/pip-audit](https://github.com/pypa/pip-audit))
  - Go: `govulncheck` ([go.dev/doc/security/vuln](https://go.dev/doc/security/vuln/editor))
  - Rust: `cargo audit`
  - 横断: `osv-scanner` / `trivy fs .` ([Trivy](https://trivy.dev/))
- **Source**: [GitHub dependency-review-action](https://github.com/actions/dependency-review-action), [Trivy](https://trivy.dev/), [pip-audit](https://github.com/pypa/pip-audit)

### 9. トランジティブ依存の把握
- **What to look for**: 直接依存 1 個追加で、indirect で 50+ 個増える PR。深い依存ツリー（npm の `node_modules` が 200MB 超など）。
- **Why**: Log4Shell 時に多くの組織が「自分が log4j を使っているか不明」だった原因はトランジティブ依存の不可視化 ([Red Hat Developer](https://developers.redhat.com/articles/2024/10/23/log4shell-vulnerability-shook-world-software-development))。平均アプリは 180 OSS 部品を持つ ([Sonatype 2024](https://www.sonatype.com/state-of-the-software-supply-chain/2024/scale))。
- **How to apply in a diff**: `npm ls --all` / `pnpm why <pkg>` / `cargo tree` / `mvn dependency:tree` でツリー化。新規追加 PR で追加されたトランジティブ依存を列挙させる。
- **Source**: [Tidelift on log4shell](https://github.blog/open-source/inside-the-breach-that-broke-the-internet-the-untold-story-of-log4shell/)

### 10. ライセンス互換性 (copyleft contamination)
- **What to look for**: GPL-2.0 / GPL-3.0 / AGPL-3.0 / LGPL の新規導入。プロプライエタリ製品のリンク形態（static link / dynamic link / network use）。
- **Why**: AGPL は「SaaS でも source 公開義務」を発動。M&A や IP 評価で致命傷になる ([MindCTO](https://mindcto.com/insights/copyleft-threat-agpl-risk))。`dependency-review-action` の `deny-licenses` で防御可能。
- **How to apply in a diff**: 新規依存の SPDX license id を確認 (`npm view <pkg> license` / `pip show <pkg>`)。`deny-licenses: GPL-2.0, GPL-3.0, AGPL-3.0` を workflow に設定。`UNKNOWN`/`SEE LICENSE IN ...` は手動チェック必須。
- **Source**: [Wiz: Copyleft](https://www.wiz.io/academy/compliance/copyleft), [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)

### 11. ネイティブコード / FFI / バイナリアーティファクトの存在
- **What to look for**: `.node`/`.so`/`.dylib`/`.dll` を同梱する npm パッケージ、`node-gyp` ビルド、Python の wheel に同梱される compiled extension、Rust の `*-sys` crate、prebuilt binary を取りに行く installer。
- **Why**: xz backdoor はソース GitHub にはなく、tarball 内の "テストデータ" に偽装されたオブジェクトファイルが injection 元だった ([Datadog Labs](https://securitylabs.datadoghq.com/articles/xz-backdoor-cve-2024-3094/))。バイナリは静的解析が困難。
- **How to apply in a diff**: Scorecard の `Binary-Artifacts` check スコア確認。新規依存が prebuilt binary を post-install で取りに行くなら、URL / 署名 / 再現性ビルドの有無を確認。
- **Source**: [Scorecard: Binary-Artifacts](https://github.com/ossf/scorecard/blob/main/docs/checks.md#binary-artifacts), [arXiv: Wolves in the Repository](https://arxiv.org/html/2504.17473v1)

### 12. パッケージ署名 / Provenance 検証 (Sigstore, npm provenance)
- **What to look for**: パッケージが Sigstore / cosign / npm provenance / Maven Central GPG 署名で署名されているか。npm の `--provenance` で publish された OIDC バインドが付いているか。
- **Why**: SLSA Build L2 以上では署名済み provenance が要件。署名検証で「誰が・どの CI で・どのソースコミットから」ビルドしたか証明できる ([SLSA v1.0 levels](https://slsa.dev/spec/v1.0/levels))。
- **How to apply in a diff**: コンテナ依存なら `cosign verify --certificate-identity-regexp ... --certificate-oidc-issuer https://token.actions.githubusercontent.com <image>`。npm なら `npm audit signatures`。
- **Source**: [Sigstore: Verifying Signatures](https://docs.sigstore.dev/cosign/verifying/verify/), [SLSA levels](https://slsa.dev/spec/v1.0/levels)

### 13. SBOM 生成 / 更新の有無
- **What to look for**: PR が依存を変更しているのに、リポジトリの SBOM (CycloneDX `bom.json` / SPDX `*.spdx.json`) が更新されていない / そもそも生成 pipeline がない。
- **Why**: CISA 2025 SBOM Minimum Elements は SPDX / CycloneDX を推奨、deprecated SWID を非推奨化。Component Hash / License / Tool Name / Generation Context が新規必須項目に格上げ ([CISA 2025](https://www.cisa.gov/resources-tools/resources/2025-minimum-elements-software-bill-materials-sbom))。
- **How to apply in a diff**: CI で `syft .` / `trivy sbom .` / `cyclonedx-bom` を実行し artifact 添付。OWASP Dependency-Track にアップロードして VEX 連携。
- **Source**: [CISA 2025 SBOM Minimum Elements](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf), [Trivy SBOM](https://trivy.dev/docs/latest/scanner/vulnerability/)

### 14. 依存元 registry / source URL の正当性
- **What to look for**: `package.json` で `"foo": "github:attacker/foo"` / `"foo": "git+ssh://..."` / `"foo": "file:../../../etc/..."` / `"foo": "https://gist.github.com/..."` のような非標準 source。lockfile の `resolved` で registry が `registry.npmjs.org` 以外。
- **Why**: 攻撃者は lockfile 内の `resolved` URL を自分の registry に書き換え、`integrity` も合わせて再計算することで気付かれずに malicious code を流す ([OWASP NPM Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html))。
- **How to apply in a diff**: lockfile diff で `resolved` URL の host 部を grep。社内 internal registry / 公式 registry 以外は要レビュー。
- **Source**: [OWASP NPM Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html)

### 15. 能力過剰 (capability creep) / scope creep
- **What to look for**: ロギングライブラリなのに `child_process` / `net` / `fs` / `os.system` / `subprocess` / cryptocurrency wallet path / env var dump コードを含む。マイナーバージョンアップで全く無関係な機能（telemetry, analytics endpoint）が追加されている。
- **Why**: Cerebro / GuardDog 系の検知器は「ライブラリの宣言用途と実際の振る舞いの乖離」を malicious behavior sequence として学習している ([ACM TOSEM Cerebro](https://dl.acm.org/doi/10.1145/3705304))。"telemetry" を装った exfiltration は実例多数。
- **How to apply in a diff**: `npm diff <pkg>@<old> <pkg>@<new>` でバージョン間差分を見る。新規 import ステートメントが `node:net`/`http`/`crypto` を含むなら理由を確認。Datadog GuardDog (`guarddog pypi scan <pkg>`) で機械チェック。
- **Source**: [ACM TOSEM: Cerebro](https://dl.acm.org/doi/10.1145/3705304), [Datadog GuardDog](https://securitylabs.datadoghq.com/articles/mut-8964-an-npm-and-pypi-malicious-campaign-targeting-windows-users/)

### 16. メンテナ譲渡 / オーナーシップ変更
- **What to look for**: 短期間でメンテナが交代しているパッケージ、新メンテナの GitHub アカウント作成日が最近、過去の commit と style が著しく異なる、`package.json` の `author`/`maintainers` が変わっている。
- **Why**: xz は 2 年かけてメンテナ権限を奪取された ([SentinelOne](https://www.sentinelone.com/blog/xz-utils-backdoor-threat-actor-planned-to-inject-further-vulnerabilities/))。event-stream はオリジナル作者が無関係な第三者にメンテナ譲渡 → 直後に悪意コード混入。
- **How to apply in a diff**: 新規 / 重要依存を導入する際、`npm view <pkg> maintainers` / GitHub の contributors history を確認。新規 maintainer の他リポでの活動量を見る。
- **Source**: [arXiv: Wolves in the Repository](https://arxiv.org/html/2504.17473v1), [Wikipedia: XZ backdoor](https://en.wikipedia.org/wiki/XZ_Utils_backdoor)

### 17. リリース新鮮度 / cooldown
- **What to look for**: 公開から 24〜72 時間以内の最新バージョンを直接導入する PR。`npx <name>@latest` のような pinned 無し実行。
- **Why**: malicious version は通常 24〜48 時間以内に検出・unpublish される。pnpm v11 ではデフォルト `minimumReleaseAge: 1440` (1 日) を導入 ([pnpm supply chain](https://pnpm.io/supply-chain-security))。
- **How to apply in a diff**: `.npmrc` で `minimumReleaseAge` 設定、または Renovate/Dependabot の stability days を 3〜7 日設定。CI で `npm view <pkg>@<ver> time` をチェックし、24h 未満はマージ保留。
- **Source**: [pnpm supply chain security](https://pnpm.io/supply-chain-security)

### 18. CI / build pipeline 内での secret 露出
- **What to look for**: 新規依存が CI で実行され、その CI job が high-privilege secret (`GITHUB_TOKEN: write`, AWS credentials, npm publish token) に触れる構成。`pull_request_target` で第三者 PR を自動実行している workflow。
- **Why**: Codecov bash uploader incident は CI 内で実行されるツールがシークレットを流出させた典型例。SLSA L3 は build platform の isolation を要件化 ([SLSA levels](https://slsa.dev/spec/v1.0/levels))。
- **How to apply in a diff**: workflow YAML を Scorecard の `Dangerous-Workflow` / `Token-Permissions` check で評価。`permissions: read-all` をデフォルトに、必要 job だけ昇格。
- **Source**: [Scorecard: Dangerous-Workflow](https://github.com/ossf/scorecard/blob/main/docs/checks.md#dangerous-workflow), [SLSA levels](https://slsa.dev/spec/v1.0/levels)

### 19. 依存削除時の dead code / 未参照確認
- **What to look for**: 削除されたパッケージがコードベース内でまだ import されていないか。逆に、`package.json` に残っているが import されていない unused 依存。
- **Why**: 未使用依存は SBOM ノイズと攻撃面を増やす。`depcheck` / `knip` / `pip-check` で検出可能。
- **How to apply in a diff**: 削除 PR で grep して残存参照無しを確認。CI に `depcheck` を組み込む。
- **Source**: [OWASP NPM Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html)

### 20. ベンダー固定 / mirror / private registry 戦略
- **What to look for**: 重要本番依存を upstream registry に直接依存しているか、自社 mirror (Sonatype Nexus, JFrog Artifactory, GitHub Packages, AWS CodeArtifact) 経由か。
- **Why**: upstream unpublish や registry 障害時に build 不能になる。mirror があれば malicious version の流入を allowlist で防げる ([Sonatype 2024](https://www.sonatype.com/state-of-the-software-supply-chain/2024/introduction))。
- **How to apply in a diff**: `.npmrc` / `pip.conf` / `settings.xml` の registry URL を確認。public registry を直接叩く設定は本番リポでは要修正。
- **Source**: [Sonatype 2024 Report](https://www.sonatype.com/state-of-the-software-supply-chain/2024/introduction)

### 21. CVE トリアージと VEX
- **What to look for**: scanner が CVE を検出した時、`fail-on-severity` で機械的にブロックされている / 例外管理されていない。誤検知に対して VEX (Vulnerability Exploitability eXchange) document が無い。
- **Why**: scanner はリーチャビリティを見ないため false positive 多い。VEX で `not_affected` を宣言すれば下流の consumer が無駄なアラートに振り回されずに済む ([CISA SBOM 2025](https://www.cisa.gov/sbom))。
- **How to apply in a diff**: 抑制した CVE には VEX エントリ (`status: not_affected`, `justification: vulnerable_code_not_in_execute_path` 等) を添付。OWASP Dependency-Track で管理。
- **Source**: [CISA SBOM Minimum Elements 2025](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf)

## Anti-patterns to avoid in review

レビュアが過剰反応しがちなパターン:

1. **すべての patch bump を「リスク」と扱う**: `1.2.3 → 1.2.4` のような security patch を機械的に block するとセキュリティ修正が滞る。`fail-on-severity` は moderate 以上に絞り、patch は許容する。
2. **lockfile の大量差分 = 即マルウェア、と判断する**: メジャー依存 1 個更新でも transitive 数百行動くのは正常。**`resolved` URL / `integrity` の変化**に絞って見る。
3. **GPL = 即拒否**: GPL ライブラリでも CLI ツールとして単独実行 / IPC 越し利用なら contamination 起きない。利用形態（static link / network use）で判断する ([Wiz: Copyleft](https://www.wiz.io/academy/compliance/copyleft))。
4. **「人気ある = 安全」と短絡する**: event-stream / ua-parser-js / xz-utils はいずれも極めて人気が高かった。DL 数だけでなく maintainer health, signature, scorecard を合わせて見る。
5. **scanner の出力をそのまま全部潰そうとする**: CVE の中には実行パスに到達しない false positive が多い (Log4Shell でも shaded jar / 未使用 class で affected 判定された事例多数)。VEX で `not_affected` を明示する。
6. **Renovate / Dependabot PR を機械承認**: 自動 PR でも依存更新内容は人の目で確認する。bot 自体が悪意ある依存を引っ張ってきた事例あり。
7. **`npm audit fix --force` のような破壊的修正を許容**: メジャーバージョン強制アップで API 破壊 → build 失敗 → revert で結局元の脆弱版に戻る、というアンチパターン。

## Gap analysis

`prompts/dependencies.md` は現状**存在しない**。推奨される作成方針:

```
# Recommended skeleton for prompts/dependencies.md
You are reviewing a PR that changes third-party dependencies.

Inputs:
- diff of manifest files (package.json / pyproject.toml / go.mod / Cargo.toml / pom.xml)
- diff of lockfiles
- diff of CI workflow files
- (optional) SBOM diff

Mandatory checks (cite the section number from 06-dependencies.md):
1. New dependency justification (§1)
2. Maintainer health / Scorecard (§2)
3. Typosquatting probability (§3)
4. Install/postinstall scripts (§4)
5. Lockfile presence & integrity hash (§5, §6)
6. Version pinning strategy (§7)
7. Known CVE / advisory (§8)
8. Transitive blast radius (§9)
9. License compatibility (§10)
10. Native code / binary artifacts (§11)
11. Signature / provenance (§12)
12. SBOM update (§13)
13. Source URL / registry origin (§14)
14. Capability creep diff (§15)
15. Maintainer transfer signals (§16)
16. Release freshness / cooldown (§17)

Output format:
- For each check: PASS / WARN / FAIL with one-line evidence.
- Final verdict: APPROVE / REQUEST_CHANGES / BLOCK.
- For BLOCK: cite the specific lockfile/manifest hunk.
```

このプロンプトに従う reviewer agent を CI に組み込めば、上記 21 項目を falsifiable に評価できる。

## References

- [SLSA v1.0 Security Levels](https://slsa.dev/spec/v1.0/levels)
- [SLSA framework on slsa.dev](https://slsa.dev/)
- [OpenSSF Scorecard checks documentation](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [OpenSSF Scorecard project page](https://openssf.org/projects/scorecard/)
- [GitHub dependency-review-action](https://github.com/actions/dependency-review-action)
- [Configuring the dependency review action — GitHub Docs](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/configuring-the-dependency-review-action)
- [Scorecard info in dependency review action (GitHub Changelog 2024-03-20)](https://github.blog/changelog/2024-03-20-openssf-scorecard-info-is-now-available-in-the-dependency-review-action/)
- [CISA SBOM landing page](https://www.cisa.gov/sbom)
- [CISA 2025 SBOM Minimum Elements (PDF)](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf)
- [Sigstore Verifying Signatures](https://docs.sigstore.dev/cosign/verifying/verify/)
- [sigstore/cosign GitHub](https://github.com/sigstore/cosign)
- [OWASP NPM Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html)
- [pnpm Supply Chain Security](https://pnpm.io/supply-chain-security)
- [Nodejs Security: NPM ignore-scripts](https://www.nodejs-security.com/blog/npm-ignore-scripts-best-practices-as-security-mitigation-for-malicious-packages)
- [Microsoft Security Blog: Axios npm compromise (2026-04)](https://www.microsoft.com/en-us/security/blog/2026/04/01/mitigating-the-axios-npm-supply-chain-compromise/)
- [StepSecurity: axios compromised on npm](https://www.stepsecurity.io/blog/axios-compromised-on-npm-malicious-versions-drop-remote-access-trojan)
- [Wikipedia: XZ Utils backdoor (CVE-2024-3094)](https://en.wikipedia.org/wiki/XZ_Utils_backdoor)
- [CrowdStrike: CVE-2024-3094 XZ Upstream Supply Chain Attack](https://www.crowdstrike.com/en-us/blog/cve-2024-3094-xz-upstream-supply-chain-attack/)
- [Datadog Security Labs: XZ backdoor deep dive](https://securitylabs.datadoghq.com/articles/xz-backdoor-cve-2024-3094/)
- [arXiv 2504.17473: Wolves in the Repository (XZ analysis)](https://arxiv.org/html/2504.17473v1)
- [SentinelOne: XZ Utils threat actor analysis](https://www.sentinelone.com/blog/xz-utils-backdoor-threat-actor-planned-to-inject-further-vulnerabilities/)
- [GitHub Blog: Inside the breach that broke the internet (Log4Shell)](https://github.blog/open-source/inside-the-breach-that-broke-the-internet-the-untold-story-of-log4shell/)
- [Red Hat Developer: Log4Shell retrospective](https://developers.redhat.com/articles/2024/10/23/log4shell-vulnerability-shook-world-software-development)
- [Sonatype 2024 State of the Software Supply Chain](https://www.sonatype.com/state-of-the-software-supply-chain/2024/introduction)
- [Sonatype 2024 Scale of Open Source](https://www.sonatype.com/state-of-the-software-supply-chain/2024/scale)
- [Sonatype 2024 Open Source Risk](https://www.sonatype.com/state-of-the-software-supply-chain/2024/risk)
- [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)
- [Wiz: What is Copyleft?](https://www.wiz.io/academy/compliance/copyleft)
- [MindCTO: AGPL risk for startups](https://mindcto.com/insights/copyleft-threat-agpl-risk)
- [SecurityScientist: 12 Questions on Typosquatting](https://www.securityscientist.net/blog/12-questions-and-answers-about-typosquatting-pypi-npm-supply-chain/)
- [Check Point: PyPI inundated by typosquatting](https://blog.checkpoint.com/securing-the-cloud/pypi-inundated-by-malicious-typosquatting-campaign/)
- [OSSF malicious-packages database](https://github.com/ossf/malicious-packages)
- [Datadog Labs: MUT-8694 npm/PyPI campaign](https://securitylabs.datadoghq.com/articles/mut-8964-an-npm-and-pypi-malicious-campaign-targeting-windows-users/)
- [ACM TOSEM: Cerebro malicious behavior sequence model](https://dl.acm.org/doi/10.1145/3705304)
- [USENIX Security 2023: Package Confusion](https://www.usenix.org/system/files/usenixsecurity23-neupane.pdf)
- [Trivy by Aqua Security](https://trivy.dev/)
- [pypa/pip-audit](https://github.com/pypa/pip-audit)
- [Go vulnerability scanning in editors (govulncheck)](https://go.dev/doc/security/vuln/editor)
- [Lockfile format design and tradeoffs (Nesbitt 2026)](https://nesbitt.io/2026/01/17/lockfile-format-design-and-tradeoffs.html)
- [cyberphinix: package-lock.json vs yarn.lock vs pnpm-lock.yaml](https://cyberphinix.de/blog/package-lock-json-vs-yarn-lock-vs-pnpm-lock-yaml-basics/)
- [pnpm install CLI docs](https://pnpm.io/cli/install)
