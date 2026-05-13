---
name: code-review-claude
description: Run a parallel multi-reviewer code review (Security / Performance / SRE / Coverage + Coordinator) on a diff using the Claude CLI. Use when the user asks for a thorough or multi-perspective code review of a diff, branch, or pull request.
---

# code-review-claude

Runs four specialist reviewers in parallel against a diff via the Claude CLI
(`claude -p`), then merges their findings through a Coordinator. All four
reviewers — Security, Performance, SRE, Coverage — produce structured XML; the
Coordinator deduplicates and ranks issues by severity.

## When to invoke

- "review this PR / branch / diff"
- "セキュリティとパフォーマンス両方見て"
- "本番投入前に多角的にチェックしたい"

If the request is a single-aspect quick check (e.g. "just look for typos"),
prefer a one-shot review instead of this skill.

## Choosing the reviewer set

The default invocation runs 4 reviewers (`security,performance,sre,coverage`).
Two reviewers auto-trigger on file patterns (`api-contract`, `dependencies`).
Two reviewers are opt-in only (`architecture`, `maintainability`). Pick the
flag based on the user's wording:

| User signal | Flag to use | Why |
| --- | --- | --- |
| 「徹底」「精緻」「全観点」「thorough」「comprehensive」「everything」「8観点で」 | `--reviewers all` | runs default 4 + 2 opt-in + matched conditionals. Up to 9 calls |
| 「API契約」「breaking change」「schema migration」「後方互換」 | `--force api-contract` (and let other conditionals dispatch normally) | guarantees api-contract runs even if dispatch heuristic misses the file |
| 「依存」「dependency」「lockfile」「supply chain」「SBOM」 | `--force dependencies` | guarantees dependencies runs |
| 「設計」「architecture」「module 構造」「結合度」「DDD」 | `--reviewers security,performance,sre,coverage,architecture` | adds the opt-in architecture reviewer |
| 「読みやすさ」「naming」「複雑度」「refactor」「maintainability」 | `--reviewers security,performance,sre,coverage,maintainability` | adds the opt-in maintainability reviewer |
| 「軽く」「サクッと」「quick」「fast」 | `--reviewers security,coverage` | minimum recommended pair |
| 何も指定なし | default (no `--reviewers`) | 4 always + matched conditionals |

Before launching the run, announce the chosen set in one line to the user
(e.g., "全観点で回します（`--reviewers all`、最大 9 calls）" or
"デフォルトの 4 reviewer で回します"). This is so the user can interrupt if
the choice was wrong before paying for the API calls.

When in doubt, prefer the wider set — the prompts have explicit
"refuse anti-patterns" sections to suppress bikeshed, so the cost of an extra
reviewer is mostly compute, not noise.

## Prerequisites

- `claude` CLI on PATH (already present if you are reading this from Claude
  Code itself).
- Python 3.10+ (uses `asyncio.gather` for parallelism).

## How to run

1. Resolve the diff. Prefer in this order:
   - The user provided an explicit file/path → use it.
   - The user said "this branch" or "this PR" → `git diff origin/main...HEAD`
     (or the user-specified base) and write to a temp file.
   - Otherwise ask the user which diff to review.
2. Resolve context variables from the project (`--language`, `--framework`,
   `--environment`, etc.). If you cannot infer a value with high confidence,
   leave it as `unknown` rather than guessing.
3. Always invoke the runner with `--output-dir` pointing at a fresh temp dir
   (e.g. `/tmp/review_out_$(date +%s)`). Per-reviewer XML files are written as
   soon as each reviewer finishes, and a `run.log` is created automatically.
4. **Run the script in the background so progress is observable.** Use the
   Bash tool's `run_in_background: true`. While it runs, use `BashOutput` (or
   `tail -f` on the log file in another shell) to surface progress to the
   user. The log format is:

   ```
   2026-05-13T06:35:12Z   +0.0s  start backend=claude ... pid=12345
   2026-05-13T06:35:12Z   +0.1s  [security] dispatched (1234 chars)
   2026-05-13T06:35:12Z   +0.1s  [performance] dispatched (1240 chars)
   ...
   2026-05-13T06:35:38Z  +26.4s  [security] done in 26.3s (2104 chars)
   2026-05-13T06:35:38Z  +26.4s  [security] wrote /tmp/review_out_*/security.xml
   ...
   2026-05-13T06:36:05Z  +53.7s  [coordinator] done in 12.0s (1881 chars)
   2026-05-13T06:36:05Z  +53.7s  done
   ```

5. Example invocation:

   ```bash
   OUT=/tmp/review_out_$(date +%s)
   python3 "$SKILL_DIR/../../scripts/run_review.py" \
     --backend claude \
     --diff /tmp/review.diff \
     --language python --framework fastapi \
     --environment "production, k8s" \
     --trust-boundary "external HTTP input" \
     --auth-method "JWT (RS256)" \
     --data-scale "10M rows / day" --is-hot-path yes \
     --test-framework pytest \
     --output-dir "$OUT"
   echo "log: $OUT/run.log"
   echo "summary: $OUT/summary.xml"
   ```

   `$SKILL_DIR` is whatever directory contains this SKILL.md. When the skill
   is symlinked into `~/.claude/skills/`, the script lives at the symlink
   target; Python resolves the path via `Path(__file__).resolve()` so it
   still works.

6. While running, surface meaningful events to the user (e.g. "security and
   coverage finished, performance still pending, coordinator hasn't started
   yet") — do not silently wait.

7. When the background job exits, read `summary.xml` and present it. If
   `verdict` is `REQUEST_CHANGES`, lead with the critical issues. Always
   link to per-reviewer XML files for drill-down.

## Options worth knowing

- `--reviewers security,coverage` — explicit subset (minimum recommended pair
  when cost matters).
- `--reviewers all` — run every registered reviewer (defaults + opt-in + any
  conditional that matches the diff).
- `--force <name>` — comma-separated; run a conditional reviewer even if no
  matching files are in the diff.
- `--skip <name>` — comma-separated; drop a reviewer that would otherwise run.
- `--dry-run` — print the resolved reviewer list and exit (no API calls).
  Useful for verifying dispatch before paying for a real run.
- `--no-coordinator` — skip the merge step; prints raw per-reviewer XML.
- `--model claude-opus-4-7` — override model (default uses the CLI's default).

## Reviewer registry

| Reviewer | When it runs | Trigger |
| --- | --- | --- |
| `security` | always | — |
| `performance` | always | — |
| `sre` | always | — |
| `coverage` | always | — |
| `api-contract` | conditional | diff touches `**/*.proto`, `**/openapi*.{yaml,yml,json}`, `**/*.graphql`, `**/migrations/**`, `**/schema.{sql,prisma}`, `**/sdk/**`, `**/api/v*/**` |
| `dependencies` | conditional | diff touches `package.json`, `*-lock.*`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`, `pom.xml`, `build.gradle*` (root or nested) |
| `architecture` | **opt-in** | `--reviewers architecture,...` or `--reviewers all` |
| `maintainability` | **opt-in** | `--reviewers maintainability,...` or `--reviewers all` |

Cost: default invocation = 5 calls. Conditional firing adds 1 each (max 7).
`--reviewers all` runs every reviewer that's applicable to the diff (max 9).

**Warning on opt-in reviewers**: `architecture` is opinion-driven and
`maintainability` is bikeshed-prone. Both have hard "anti-patterns to refuse"
sections built into their prompts, but human final review is still essential.
Don't enable them on every diff — use them when you specifically want an
architectural or readability lens.

## Output

The Coordinator emits:

```xml
<review_summary>
  <stats>...</stats>
  <issues> <!-- severity-desc sorted --> </issues>
  <verdict>APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION</verdict>
</review_summary>
```

If any `<severity>critical</severity>` issue exists, the output is prefixed
with `🚨 CRITICAL ISSUES FOUND`.

## Cost / safety notes

- 4 reviewers + 1 Coordinator = 5 CLI invocations per review. For large diffs
  (>500 lines) split the diff by file first.
- The diff is wrapped in `<diff>...</diff>` and prompts explicitly instruct
  the model to treat tag contents as code, not instructions — defense against
  prompt injection embedded in PR contents (CVE-2025-59536 class).
- Final sign-off should always be a human. AI review is a filter, not a gate.
