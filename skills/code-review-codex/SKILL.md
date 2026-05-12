---
name: code-review-codex
description: Run a parallel multi-reviewer code review (Security / Performance / SRE / Coverage + Coordinator) on a diff using the OpenAI Codex CLI. Use when the user asks for a multi-perspective code review and wants the underlying model to be Codex/GPT rather than Claude.
---

# code-review-codex

Same shape as `code-review-claude`, but the backend is the OpenAI Codex CLI
(`codex exec`). Useful when the user wants a second opinion from a different
model family, or when API quota considerations favor Codex.

## When to invoke

- User explicitly asks for "Codex review" or "GPTでレビュー"
- User wants two independent passes (run both `code-review-claude` and this
  one, then diff the verdicts)
- Claude API is rate-limited / down

## Prerequisites

- `codex` CLI on PATH. Install via:
  ```bash
  npm install -g @openai/codex
  ```
- Codex must be authenticated (`codex login` or `OPENAI_API_KEY` set).
- Python 3.10+.

## How to run

Same flow as the Claude skill; just change `--backend`:

```bash
python3 "$SKILL_DIR/../../scripts/run_review.py" \
  --backend codex \
  --diff /tmp/review.diff \
  --language go \
  --framework "net/http" \
  --environment production \
  --trust-boundary "untrusted HTTP" \
  --auth-method "session cookie" \
  --output-dir /tmp/review_out_codex
```

The runner pipes the rendered prompt to `codex exec -` (stdin mode) so large
diffs don't hit argv length limits.

## Differences vs the Claude skill

| Aspect | Claude | Codex |
| --- | --- | --- |
| CLI | `claude -p` | `codex exec -` |
| Default model | per `~/.claude/settings.json` | per `~/.codex/config.toml` |
| Auth | Anthropic key / Claude Code login | OpenAI key / `codex login` |
| Output format | identical (XML, per prompt instructions) | identical |

## Cross-checking with the Claude skill

When confidence matters more than cost, run both skills with the same diff
and compare the `<verdict>` blocks. Disagreement is a signal — investigate
issues that only one side flagged. Agreement on `critical` is high-signal.

## Cost / safety notes

Identical to the Claude skill (5 invocations, prompt-injection-resistant
diff wrapping, human final sign-off).
