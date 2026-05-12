---
title: Security Code Review — Best Practices Reference
last_reviewed: 2026-05-13
primary_sources:
  - https://owasp.org/www-project-code-review-guide/
  - https://cheatsheetseries.owasp.org/cheatsheets/Secure_Code_Review_Cheat_Sheet.html
  - https://owasp.org/Top10/2021/
  - https://cwe.mitre.org/top25/archive/2024/2024_cwe_top25.html
  - https://csrc.nist.gov/pubs/sp/800/218/final
  - https://owasp.org/www-project-application-security-verification-standard/
  - https://genai.owasp.org/llm-top-10/
---

# Security Code Review Best Practices

## Why this matters
セキュアコードレビューはデプロイ前に脆弱性を発見できる最後の人間中心の防御層であり、OWASP Code Review Guide v2 はこれを SDLC に不可欠なプロセスとして位置付けている [1]。CISA/MITRE の 2024 CWE Top 25 では XSS・Out-of-Bounds Write・SQLi が依然として最多であり [2]、NIST SP 800-218 (SSDF) PW.7 もコードレビューと静的解析を「Produce Well-Secured Software」の必須実践として要求している [3]。レビュー時は理論上の弱点ではなく、攻撃者が実際に到達できる経路に絞って報告することがシグナル対ノイズ比を保つ鍵 [1][4]。

## Review checklist

各項目は diff から検証可能なシグナルに限定している。「考慮すべき」「念のため」のような曖昧な指摘は除外している。

### 1. SQL 構築における文字列連結／フォーマット
- **What to look for**: ユーザ入力を含む変数を `+`, `%`, f-string, `.format()`, `String.format`, テンプレートリテラル等で SQL 文に組み立てているコード。`cursor.execute(f"SELECT ... {user_input}")`, `db.query("... " + req.body.id)` 等。ORM の生 SQL (`raw()`, `text()`, `db.exec`) も対象。
- **Why**: CWE-89 (SQL Injection)。2024 CWE Top 25 第3位 [2]、OWASP Top 10 A03:2021 Injection に含まれる [4]。
- **How to apply in a diff**: SQL クエリの隣で input source を遡り、parameterized query (`?`, `:name`, `$1`, `@param`) に置換されているかを確認。bind variable が使えない箇所 (table 名・ORDER BY) ではコード由来の固定値かを確認 [5][6]。
- **Source**: [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html), [OWASP Query Parameterization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html)

### 2. OS コマンド組み立てでのシェル呼び出し
- **What to look for**: `os.system`, `subprocess.run(..., shell=True)`, `exec`, `child_process.exec`, `Runtime.exec(String)`, バックティック等にユーザ入力を渡しているコード。
- **Why**: CWE-78 (OS Command Injection)。2024 CWE Top 25 上位常連、RCE に直結する [2]。
- **How to apply in a diff**: `shell=True` の使用や文字列結合をフラグし、`subprocess.run([...], shell=False)` のような配列引数形式・`execFile` への置換を要求 [7]。
- **Source**: [CWE-78](https://cwe.mitre.org/data/definitions/78.html), [OWASP Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html)

### 3. HTML 出力での文脈別エンコーディング欠如
- **What to look for**: テンプレートで `{{ user_input | safe }}`, `v-html`, `dangerouslySetInnerHTML`, `innerHTML = ...`, 自前の文字列連結による HTML 生成。属性値・JS・CSS・URL の各文脈で正しいエンコーディングが行われているか。
- **Why**: CWE-79 (XSS) — 2024 CWE Top 25 第1位 [2]。HTML エンティティエンコードだけでは `<script>` 内・`onclick` 等のイベントハンドラ・CSS・URL 文脈で防御にならない [8]。
- **How to apply in a diff**: sink 種別 (HTML body / attribute / JS / CSS / URL) を特定し、それに対応した encoder (OWASP Java Encoder, DOMPurify など) が直前で適用されているかを確認。DOM 系では `textContent` / `innerText` への置換が望ましい。
- **Source**: [OWASP XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html), [DOM-based XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html)

### 4. 認可チェックを伴わない直接オブジェクト参照 (IDOR)
- **What to look for**: `GET /orders/:id` のようにパス・クエリパラメータの ID を直接 DB lookup に使い、所有権チェック (`WHERE user_id = :current_user`) が無い。`Order.find(params[:id])` 等の素直な find が controller レベルで露出している。
- **Why**: CWE-639, CWE-284。OWASP Top 10 A01:2021 Broken Access Control — 最頻出カテゴリで CWE 検出件数 318k 超 [4][9][10]。
- **How to apply in a diff**: ID パラメータの直後で current user の認可述語が WHERE 句または明示的 `authorize!` 呼び出しで適用されているかを確認。UUID への変更だけで満足しない (defense-in-depth に過ぎない) [10]。
- **Source**: [OWASP IDOR Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html), [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)

### 5. クライアント側の認可チェックへの依存
- **What to look for**: フロントエンド (React/Vue/Angular) で `if (user.isAdmin)` してエンドポイントを表示／非表示にしているが、対応するサーバ側ハンドラに `requireRole('admin')` 等が無いケース。
- **Why**: Access Control はサーバ側でのみ強制可能 [4]。クライアントを攻撃者は自由に書き換えられる。
- **How to apply in a diff**: 新規・変更ルートに対し middleware / decorator (Spring `@PreAuthorize`, Flask `@login_required`, Rails `before_action`) が付与されているかを確認。
- **Source**: [OWASP Top 10 A01:2021 — Broken Access Control](https://owasp.org/Top10/2021/A01_2021-Broken_Access_Control/)

### 6. ハードコードされた認証情報・秘密鍵
- **What to look for**: ソース・config・テストファイル中の API key, password, AWS access key, JWT secret, private key (PEM block), DB connection string with password。エントロピーの高い長い文字列、`password = "..."`, `API_KEY = "AKIA..."` 等のパターン。
- **Why**: CWE-798 — OWASP Top 10 A07 (Authentication Failures) に含まれ、Uber 2016 のような大規模漏洩の典型原因 [11][12]。
- **How to apply in a diff**: 文字列リテラルが credential 名 (`secret`, `token`, `password`, `key`) を含む変数に代入されている箇所、または `-----BEGIN ` を含む箇所をフラグ。env var / secrets manager 経由への置換を要求。
- **Source**: [CWE-798](https://cwe.mitre.org/data/definitions/798.html), [OWASP Top 10 A07:2025 Authentication Failures](https://owasp.org/Top10/2025/A07_2025-Authentication_Failures/)

### 7. パスワード保存への高速ハッシュ・暗号化の使用
- **What to look for**: パスワード保存に `md5`, `sha1`, `sha256`, `sha512` を直接使う、または可逆な対称暗号 (`AES.encrypt(password)`) を使う実装。
- **Why**: CWE-916, CWE-327。OWASP Password Storage Cheat Sheet は Argon2id (memory ≥19 MiB, iterations ≥2, parallelism 1) を第一選択、次点で scrypt, bcrypt (cost ≥10), FIPS なら PBKDF2 (≥600k iterations, HMAC-SHA-256) を要求 [13]。
- **How to apply in a diff**: パスワードフィールドが渡されている関数を辿り、上記いずれかへの置換を確認。`pbkdf2(..., iterations=1000)` のような弱いパラメータも指摘対象。
- **Source**: [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

### 8. 弱い／非推奨の暗号アルゴリズム
- **What to look for**: `DES`, `3DES`, `RC4`, ECB モード、MD5/SHA-1 をデジタル署名・MAC・パスワードハッシュ用途で使用。`Random` (非 CSPRNG) で鍵・トークン・nonce を生成。RSA <2048bit。
- **Why**: CWE-327, CWE-330, CWE-338。OWASP Top 10 A02:2021 Cryptographic Failures [4]。
- **How to apply in a diff**: 暗号 API 呼び出しのアルゴリズム識別子をチェック。AES-GCM/CBC+HMAC、SHA-256+、`secrets.token_bytes` / `crypto.randomBytes` / `SecureRandom` を要求。
- **Source**: [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html), [OWASP Top 10 A02:2021](https://owasp.org/Top10/2021/A02_2021-Cryptographic_Failures/)

### 9. TLS 証明書検証の無効化
- **What to look for**: `verify=False` (requests), `rejectUnauthorized: false` (Node), `InsecureSkipVerify: true` (Go), `NSURLSessionDelegate` で常に accept、`HostnameVerifier` を `ALLOW_ALL` に設定。
- **Why**: CWE-295, CWE-297。MITM 攻撃に直結 [14]。
- **How to apply in a diff**: HTTPS クライアント生成箇所で TLS 検証を無効化／カスタムハンドラで素通しにしている箇所をフラグ。テストでは許容するがプロダクションコードでは禁止。
- **Source**: [CWE-295](https://cwe.mitre.org/data/definitions/295.html), [CWE-297](https://cwe.mitre.org/data/definitions/297.html)

### 10. 信頼できないデータの安全でないデシリアライズ
- **What to look for**: `pickle.loads`, `cPickle.load`, `yaml.load` (without `SafeLoader`), `ObjectInputStream.readObject`, PHP `unserialize`, .NET `BinaryFormatter`, Ruby `Marshal.load`, `jsonpickle`, `numpy.load(..., allow_pickle=True)`, `torch.load` without `weights_only=True`。
- **Why**: CWE-502 — OWASP Top 10 A08:2021 Software and Data Integrity Failures。RCE に直結する gadget chain を許す [15]。
- **How to apply in a diff**: ネットワーク／ファイル入力が上記関数に渡る経路をフラグ。`yaml.safe_load`, JSON, Protobuf への置換を要求。署名 (HMAC) または allowlist 型フィルタも代替手段として可。
- **Source**: [CWE-502](https://cwe.mitre.org/data/definitions/502.html), [OWASP Insecure Deserialization](https://owasp.org/www-community/vulnerabilities/Insecure_Deserialization)

### 11. SSRF — 外部 URL の取得におけるバリデーション欠如
- **What to look for**: ユーザ提供 URL を `requests.get`, `fetch`, `curl`, `HttpClient.GetAsync`, image fetcher, webhook, RSS リーダ等に直接渡す。`urllib.request.urlopen(user_url)`。
- **Why**: CWE-918。OWASP Top 10 A10:2021 SSRF。AWS metadata `169.254.169.254`, 内部サービス (`localhost`, RFC1918) への到達でクレデンシャル窃取・内部スキャンが可能 [16]。
- **How to apply in a diff**: 取得対象 URL の scheme/host を allowlist で制限しているか、private IP range (RFC1918, link-local, loopback) を拒否しているか、redirect follow を無効化しているかを確認。
- **Source**: [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html), [OWASP Top 10 A10:2021](https://owasp.org/Top10/2021/A10_2021-Server-Side_Request_Forgery_(SSRF)/)

### 12. パストラバーサル
- **What to look for**: ユーザ入力をファイルパスに連結 (`open(BASE_DIR + user_filename)`), `path.join(uploads, req.params.file)`, `File.new("./data/#{params[:name]}")`。`../`, encoded `%2e%2e%2f`, null byte injection の許容。
- **Why**: CWE-22 — 2024 CWE Top 25 入り、A01:2021 配下 [2][17]。CISA Secure by Design の重点根絶対象 [18]。
- **How to apply in a diff**: 連結後に `os.path.realpath` / `Path.resolve` で正規化し、許可ベースディレクトリの prefix チェックがされているかを確認。理想形はユーザ入力をファイル名に使わず内部 ID から取得 [18]。
- **Source**: [CWE-22](https://cwe.mitre.org/data/definitions/22.html), [CISA Secure-by-Design Directory Traversal Alert](https://www.cisa.gov/sites/default/files/2024-05/Secure_by_Design_Alert_Eliminating_Directory_Traversal_Vulnerabilities_in_Software_508c%20(3).pdf)

### 13. 状態変更エンドポイントでの CSRF 防御欠如
- **What to look for**: POST/PUT/DELETE/PATCH を受けるルートで、CSRF token middleware (`csurf`, Rails `protect_from_forgery`, Django `@csrf_protect`) が無効化されている。`SameSite=None` でかつ token も無いセッションクッキー。
- **Why**: CWE-352。SameSite クッキー単独では bypass 経路があるため、token と併用が推奨される [19]。
- **How to apply in a diff**: 新規 mutating エンドポイント・API ルートで synchronizer token / double-submit / custom header (`X-CSRF-Token`) のいずれかが実装されているかを確認。
- **Source**: [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

### 14. 機微データのログ出力
- **What to look for**: パスワード・トークン・credit card・SSN・JWT raw 値・session ID・request body 全体を logger に流す `logger.info(f"login {user} password={password}")`, `console.log(req)`, スタックトレース内の secret。
- **Why**: CWE-532 (Insertion of Sensitive Information into Log File), CWE-117 (Improper Output Neutralization for Logs)。OWASP Top 10 A09 [20][21]。
- **How to apply in a diff**: ログ呼び出しの引数を確認し、credential / PII / 完全な request object をマスク・トークン化・除外しているかを検証。CRLF injection (`\r\n`) を許す concat ロギングも指摘。
- **Source**: [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html), [CWE-532](https://cwe.mitre.org/data/definitions/532.html)

### 15. オープンリダイレクト
- **What to look for**: `redirect(request.args.get('next'))`, `res.redirect(req.query.url)` のようにユーザ入力で完全な URL にリダイレクト。
- **Why**: CWE-601。フィッシング・OAuth code 窃取の足掛かりとして悪用される。OWASP A01 配下に含まれる [4]。
- **How to apply in a diff**: redirect target がアプリの allowlist (相対パスのみ／ホスト allowlist) で検証されているかを確認。
- **Source**: [CWE-601](https://cwe.mitre.org/data/definitions/601.html), [OWASP Unvalidated Redirects and Forwards Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html)

### 16. XXE — XML 外部実体
- **What to look for**: XML パーサ初期化時に外部実体を無効化していない。Java `DocumentBuilderFactory` で `disallow-doctype-decl` を設定していない、Python `lxml.etree.parse(..., resolve_entities=True)`、.NET `XmlReader` で `DtdProcessing=Parse` 等。
- **Why**: CWE-611 — 任意ファイル読み取り・SSRF・DoS に発展。A05:2021 Security Misconfiguration に統合 [4]。
- **How to apply in a diff**: 新規 XML パーサ初期化で external entity / DTD 解決を無効化しているかを確認。可能なら JSON への移行を提案。
- **Source**: [OWASP XXE Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html)

### 17. JWT — `alg: none` と弱い鍵
- **What to look for**: JWT 検証時に `verify=False`, `algorithms=None`, alg として `HS256` と `RS256` の両方を許容しているコード、HS256 with short / hardcoded secret。
- **Why**: CWE-347 (Improper Verification of Cryptographic Signature)。alg confusion 攻撃で署名検証バイパスが可能。
- **How to apply in a diff**: 検証関数に明示的 `algorithms=['RS256']` (single algo) が指定されているか、秘密鍵が十分なエントロピーを持つか確認。
- **Source**: [OWASP JWT Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)

### 18. ReDoS — 破滅的バックトラッキングを持つ正規表現
- **What to look for**: ユーザ入力をマッチさせる正規表現に `(a+)+`, `(.*)*`, `(a|aa)*` のようなネストされた量化子。
- **Why**: CWE-1333 — GitHub が CodeQL で Fluentd, Zulip 等で繰り返し検出 [22]。1 リクエストで CPU を枯渇させ DoS。
- **How to apply in a diff**: 新規 regex でネスト量化子・重複代替を含むものをフラグし、`re2` 系エンジン or 入力長制限を提案。
- **Source**: [OWASP ReDoS](https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS), [GitHub CodeQL: Inefficient regular expression](https://codeql.github.com/codeql-query-help/javascript/js-redos/)

### 19. GitHub Actions / CI における式注入
- **What to look for**: workflow YAML で `${{ github.event.issue.title }}`, `${{ github.event.pull_request.body }}` 等の untrusted context を `run:` の中で直接展開。`pull_request_target` + checkout of PR head SHA + secret 露出の組み合わせ。
- **Why**: CWE-94。GitHub Security Lab は数ヶ月で 90+ 件の OSS workflow 脆弱性を開示 [22]。secrets 流出・リポジトリ乗っ取りに発展。
- **How to apply in a diff**: untrusted context は env var 経由 (`env: TITLE: ${{ ... }}` + `run: echo "$TITLE"`) で受ける、`pull_request_target` は最小権限・PR head の checkout 禁止になっているかを確認。
- **Source**: [GitHub Blog — Securing GitHub Actions with CodeQL](https://github.blog/security/application-security/how-to-secure-your-github-actions-workflows-with-codeql/), [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)

### 20. 詳細エラー応答による情報漏洩
- **What to look for**: `app.run(debug=True)` 本番デプロイ、スタックトレースを HTTP 応答に含める、SQL エラーメッセージをクライアントに返す。
- **Why**: CWE-209, CWE-200。A05:2021 Security Misconfiguration / A04 Insecure Design。
- **How to apply in a diff**: 例外ハンドラがクライアント向け汎用メッセージとサーバ向け詳細ログを分離しているか、デバッグフラグが本番 config で false かを確認。
- **Source**: [OWASP Error Handling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html)

### 21. LLM プロンプト注入と信頼境界の混同
- **What to look for**: LLM 呼び出しで system prompt とユーザ入力・RAG で取得したドキュメント・ツール出力を区別せず単一プロンプトに連結している。LLM 出力をそのまま `eval` / shell / DB / send_email 等の特権操作に渡している。
- **Why**: OWASP LLM01:2025 Prompt Injection — LLM Top 10 第1位 [23]。直接／間接プロンプト注入により権限濫用・情報窃取が発生。
- **How to apply in a diff**: 外部由来コンテンツがプロンプト内で明示的に区切られているか、LLM がトリガする tool call に対して human-in-the-loop / 最小権限 API token / 出力 validation が実装されているかを確認。
- **Source**: [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/), [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)

### 22. レート制限・認証回数制限の欠如
- **What to look for**: ログイン・パスワードリセット・API 呼び出しエンドポイントにレート制限 middleware が無い。OTP/MFA の試行回数制限が無い。
- **Why**: CWE-307 (Improper Restriction of Excessive Authentication Attempts)。Credential stuffing / brute force に対する第一防御。OWASP Top 10 A07 [4]。
- **How to apply in a diff**: 新規認証系エンドポイントに rate limiter (Express `express-rate-limit`, Django `ratelimit`, nginx limit_req) が適用されているかを確認。
- **Source**: [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)

### 23. 依存性に既知 CVE のある脆弱版が固定されている
- **What to look for**: `package.json` / `requirements.txt` / `go.mod` / `pom.xml` で CVE データベースに該当する版に固定／追加されている。Log4j 2.x <2.17, lodash <4.17.21, Spring Cloud Function <3.1.7 等。
- **Why**: OWASP Top 10 A06:2021 Vulnerable and Outdated Components [4]。NIST SSDF PW.4 が依存性検証を要求 [3]。
- **How to apply in a diff**: 依存性追加・更新行に対し、その版が既知 CVE 該当でないかを Advisory DB (GHSA, OSV) と突き合わせて検証。古いだけで CVE が無い場合は指摘しない。
- **Source**: [OWASP Top 10 A06:2021](https://owasp.org/Top10/2021/A06_2021-Vulnerable_and_Outdated_Components/), [GitHub Advisory Database](https://github.com/advisories)

### 24. クッキーセキュリティ属性の欠如
- **What to look for**: セッション／認証クッキーに `Secure`, `HttpOnly`, `SameSite` 属性が付与されていない。または `SameSite=None` なのに `Secure` が無い。
- **Why**: CWE-1004, CWE-614。XSS によるトークン窃取と CSRF の両方に効く [19]。
- **How to apply in a diff**: クッキー設定箇所で 3 属性が明示されているか、認証系では `__Host-` prefix の利用も検討対象。
- **Source**: [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

### 25. マスアサインメント
- **What to look for**: Rails `Model.update(params)`, Express `User.assign(req.body)`, Django `Model(**request.POST)` のように request body を ORM オブジェクトに丸ごとマージ。`is_admin`, `role`, `balance` 等の特権フィールドを攻撃者が上書き可能。
- **Why**: CWE-915。API security 文脈で OWASP API Security Top 10 (API6) に対応。
- **How to apply in a diff**: 明示的 allowlist (Rails strong parameters, DTO + validator, Pydantic schema) でフィールドが絞られているかを確認。
- **Source**: [OWASP Mass Assignment Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html), [OWASP API Security Top 10](https://owasp.org/API-Security/)

## Anti-patterns to avoid in review
AI レビュアーが過剰検出しがちな項目。これらを「critical」「warning」で報告すると S/N が下がるため、エビデンスがある場合のみ「suggestion」に留めるか、報告しない。

1. **非暗号用途の MD5/SHA-1 を脆弱性として報告する**: キャッシュキー・チェックサム・ETag・bloom filter・shard 選択など、衝突耐性が不要な用途では脆弱性ではない。CWE-327 はあくまでセキュリティ目的での使用が対象 [13]。
2. **古いだけで CVE が無い依存性を critical 扱いする**: A06:2021 はあくまで「Vulnerable and Outdated」。CVE/GHSA が紐付かない場合は指摘禁止 (現在のレビュー prompt にも明記) [4]。
3. **テストコードのハードコードクレデンシャルを critical 扱いする**: テストフィクスチャ内の `password = "test"` は本番に到達しない限り脆弱性ではない。CI/CD で本番環境に流れる経路があるときのみ指摘。
4. **すべての `eval` / `exec` を一律 RCE 扱いする**: 入力が定数・コンパイル時定数・信頼境界内ならリスクなし。データフロー上 untrusted source に到達することを確認してから報告。
5. **HTTPS 上での平文パスワード送信を critical 扱いする**: TLS が機能している限り wire 上は暗号化されている。`Authorization: Basic` over HTTPS 自体は仕様通り。
6. **`Math.random()` を一律 CWE-338 扱いする**: 抽選表示・UI アニメーション seed 等、セキュリティ判断に使われない用途では問題ない。トークン・鍵・nonce 生成に使われている場合のみ critical。
7. **存在しない攻撃シナリオに対する「念のため」の指摘**: 「もし将来このメソッドが外部公開されたら…」は OWASP Code Review Guide が明示的に避けるよう述べる「理論上の問題」[1]。現状の信頼境界で到達可能なパスがあるときのみ報告する。

## Gap analysis vs current prompt
`/home/ubuntu/ai-code-review-skills/prompts/security.md` のレビュー結果。

### Already covered
- データフロー トレーシング (Task 1)
- 入力サニタイズ／バリデーション検証 (Task 2)
- 認証・認可チェック漏れ (Task 3)
- ハードコードシークレット (Task 4)
- 「悪用可能か」を基準にする攻撃者視点
- 「コードから検証可能な根拠が無い指摘禁止」(本ドキュメントの Anti-patterns と整合)
- Severity 三段階 (critical/warning/suggestion) + category (injection/auth/crypto/exposure/config/other)
- Prompt injection 防御 (`<diff>` タグ内指示無視ルール)

### Missing / under-specified
- **暗号アルゴリズム選定** (項目 7, 8): 現 prompt の `crypto` カテゴリは抽象的で、Argon2id / TLS 検証無効化 / 弱い RNG 等の具体パターンの言及が無い。
- **SSRF** (項目 11): A10:2021 として独立した最頻出クラスだが現 prompt に明示が無い。
- **デシリアライズ** (項目 10): pickle/yaml/Java native 等を `injection` に含めるのか不明瞭。
- **CSRF / セッションクッキー属性** (項目 13, 24): 現 prompt の `auth` カテゴリで暗黙的に含むが具体性に欠ける。
- **ログへの機微情報出力** (項目 14): `exposure` カテゴリで暗黙的だが CWE-532 の具体例が無い。
- **LLM プロンプト注入** (項目 21): bot/agent コードベースでは重要だが現 prompt に該当カテゴリが無い。
- **CI/CD ワークフロー脆弱性** (項目 19): YAML レビュー時の判断基準が無い。
- **マスアサインメント・オープンリダイレクト・JWT alg confusion** (項目 25, 15, 17): いずれも実例多数だが現 prompt から欠落。
- **データフロー分析の sink リスト**: 「1ステップずつトレース」とあるが具体的な dangerous sink (`subprocess`, `pickle.loads`, `requests.get` with user URL, …) が示されていない。

### Suggested additions for the prompt
1. **`category` を拡張**: `injection | auth | crypto | exposure | config | other` →  `injection | authn | authz | crypto | secrets | ssrf | deserialization | csrf | logging | redirect | dependency | llm | ci | other` に細分化。レビュー結果の triage 効率を上げる。
2. **`Task` に sink リストを明示**: "以下の sink にユーザ入力が到達するパスを優先的に追え" として `exec/eval/subprocess/Runtime.exec`, `pickle.loads/yaml.load/ObjectInputStream`, `open/Path/File`, HTTP client with user-controlled URL, SQL execute, HTML/JS template insertion を列挙。
3. **「やるな」リストに追加**:
   - 非暗号用途の MD5/SHA-1 を critical 扱いするな
   - テストフィクスチャ内のダミークレデンシャルを本番リスク扱いするな
   - HTTPS 上の Basic 認証を「平文」扱いするな
   - `Math.random()` がセキュリティ判断に使われていない場合は指摘するな
4. **LLM 系コードベース向け branch**: `{{language}}` に Python があり、かつコード中に `openai|anthropic|llm|prompt|agent` 等が含まれる場合、LLM01–LLM10 (特に Prompt Injection, Excessive Agency, Sensitive Information Disclosure) を追加で確認するよう指示。
5. **CWE 番号を `evidence` に必須化**: 出力 schema に `<cwe>CWE-XXX</cwe>` フィールドを追加し、対応 CWE が無い指摘は出力させない。誤検知の自然な抑制になる。
6. **Severity の閾値を再定義**: `critical` の条件として「untrusted source → dangerous sink への到達可能パスがコード上で示せること」を明示。これにより理論上のリスクを critical で報告するパターンを排除。

## References

1. [OWASP Code Review Guide v2 (PDF)](https://owasp.org/www-project-code-review-guide/assets/OWASP_Code_Review_Guide_v2.pdf) / [Project page](https://owasp.org/www-project-code-review-guide/) / [Secure Code Review Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Code_Review_Cheat_Sheet.html)
2. [2024 CWE Top 25 Most Dangerous Software Weaknesses (MITRE)](https://cwe.mitre.org/top25/archive/2024/2024_cwe_top25.html) / [CISA announcement](https://www.cisa.gov/news-events/alerts/2024/11/20/2024-cwe-top-25-most-dangerous-software-weaknesses)
3. [NIST SP 800-218 Secure Software Development Framework (SSDF) v1.1](https://csrc.nist.gov/pubs/sp/800/218/final) / [PDF](https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-218.pdf)
4. [OWASP Top 10:2021](https://owasp.org/Top10/2021/) (Introduction, A01–A10)
5. [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
6. [OWASP Query Parameterization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html)
7. [OWASP Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html) / [CWE-78](https://cwe.mitre.org/data/definitions/78.html)
8. [OWASP Cross Site Scripting Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html) / [DOM Based XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html)
9. [OWASP Top 10 A01:2021 — Broken Access Control](https://owasp.org/Top10/2021/A01_2021-Broken_Access_Control/)
10. [OWASP IDOR Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html) / [Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
11. [CWE-798: Use of Hard-coded Credentials](https://cwe.mitre.org/data/definitions/798.html)
12. [OWASP Top 10:2025 A07 — Authentication Failures](https://owasp.org/Top10/2025/A07_2025-Authentication_Failures/)
13. [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) / [Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
14. [CWE-295: Improper Certificate Validation](https://cwe.mitre.org/data/definitions/295.html) / [CWE-297: Host Mismatch](https://cwe.mitre.org/data/definitions/297.html)
15. [CWE-502: Deserialization of Untrusted Data](https://cwe.mitre.org/data/definitions/502.html) / [OWASP Insecure Deserialization](https://owasp.org/www-community/vulnerabilities/Insecure_Deserialization)
16. [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) / [Top 10 A10:2021 SSRF](https://owasp.org/Top10/2021/A10_2021-Server-Side_Request_Forgery_(SSRF)/)
17. [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html) / [OWASP Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
18. [CISA Secure-by-Design Alert: Eliminating Directory Traversal (May 2024)](https://www.cisa.gov/sites/default/files/2024-05/Secure_by_Design_Alert_Eliminating_Directory_Traversal_Vulnerabilities_in_Software_508c%20(3).pdf)
19. [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
20. [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
21. [CWE-532: Insertion of Sensitive Information into Log File](https://cwe.mitre.org/data/definitions/532.html) / [Top 10 A09:2021 Logging Failures](https://owasp.org/Top10/2021/A09_2021-Security_Logging_and_Monitoring_Failures/)
22. [How GitHub uses CodeQL to secure GitHub](https://github.blog/engineering/how-github-uses-codeql-to-secure-github/) / [Securing GitHub Actions Workflows with CodeQL](https://github.blog/security/application-security/how-to-secure-your-github-actions-workflows-with-codeql/)
23. [OWASP Top 10 for LLM Applications 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/) / [LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
24. [OWASP Application Security Verification Standard (ASVS)](https://owasp.org/www-project-application-security-verification-standard/) / [ASVS GitHub](https://github.com/OWASP/ASVS)
25. [Google Engineering Practices — Code Review](https://google.github.io/eng-practices/review/) / [google/eng-practices on GitHub](https://github.com/google/eng-practices)
26. [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) / [Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) / [Mass Assignment Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html)
27. [OWASP Unvalidated Redirects and Forwards Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html) / [CWE-601](https://cwe.mitre.org/data/definitions/601.html)
28. [OWASP XXE Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html)
29. [OWASP JWT Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
30. [OWASP Error Handling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html) / [OWASP ReDoS](https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS) / [CodeQL ReDoS query](https://codeql.github.com/codeql-query-help/javascript/js-redos/)
