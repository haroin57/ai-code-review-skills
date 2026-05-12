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
3. Run the runner script. It's two directories up from this SKILL.md:

```bash
python3 "$SKILL_DIR/../../scripts/run_review.py" \
  --backend claude \
  --diff /tmp/review.diff \
  --language python \
  --framework fastapi \
  --environment "production, k8s" \
  --trust-boundary "external HTTP input" \
  --auth-method "JWT (RS256)" \
  --data-scale "10M rows / day" \
  --is-hot-path yes \
  --test-framework pytest \
  --output-dir /tmp/review_out
```

`$SKILL_DIR` is whatever directory contains this SKILL.md. When the skill is
symlinked into `~/.claude/skills/`, the script lives at the symlink target;
Python resolves the path via `Path(__file__).resolve()` so it still works.

4. Read the Coordinator output (`/tmp/review_out/summary.xml`) and present it
   to the user. If `verdict` is `REQUEST_CHANGES`, lead with the critical
   issues. Always link to per-reviewer XML files for drill-down.

## Options worth knowing

- `--reviewers security,coverage` — minimum recommended subset when cost is a
  concern (the template's "最低でもSecurity + Coverageは回すこと" rule).
- `--no-coordinator` — skip the merge step; prints raw per-reviewer XML.
- `--model claude-opus-4-7` — override model (default uses the CLI's default).

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
