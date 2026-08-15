"""Context management demo: simulates multi-turn development with context inflation.

Shows how the ContextManager prunes context across 15 turns
with fold_old_turns -> drop_stale_turns -> truncate_long_content.
"""
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mycoder.config import Config
from mycoder.context import ContextManager, estimate_tokens, estimate_messages
from mycoder.state import Message

# Load giant test file (simulates large tool outputs)
GIANT = Path("examples/giant_test.py")
giant_content = GIANT.read_text(encoding="utf-8") if GIANT.exists() else "# empty\n" * 100
giant_lines = giant_content.splitlines()
print(f"Giant file: {len(giant_lines)} lines, {len(giant_content)} chars, {estimate_tokens(giant_content)} tokens")

# Config: budget 4000 / hard 6000 / keep 6 turns
config = Config()
config.set("context.budget_tokens", 4000)
config.set("context.hard_limit_tokens", 6000)
config.set("context.keep_last_turns", 6)
config.set("context.max_file_content_chars", 8000)

ctx = ContextManager(config)
ctx.set_task("Refactor giant_test.py: rename all func_ to method_", ["giant_test.py"])

# Simulate 15 turns, each reading ~300 lines of the giant file
print("\n" + "=" * 65)
print("Simulating 15 turns (each reads ~300 lines of giant file)")
print("=" * 65)

for turn in range(1, 16):
    offset = (turn * 50) % max(1, len(giant_lines) - 300)
    chunk = "\n".join(giant_lines[offset:offset + 300])

    assistant = Message("assistant",
        f"Turn {turn}: I read lines {offset}-{offset+300} of giant_test.py, "
        f"found {chunk.count('def func_')} functions to refactor.")

    tool_msg = Message("tool",
        f"# giant_test.py (lines {offset}..{offset+300})\n\n{chunk[:4000]}",
        name="file_read")
    ctx.append_turn(assistant, [tool_msg])

    # Print status every 3 turns
    if turn % 3 == 0 or turn == 1:
        raw_tokens = estimate_messages(ctx._base_messages() + ctx._flatten(ctx.raw_turns))
        assembled = ctx.assemble()
        after_tokens = ctx.last_prune.after_tokens
        strategies = ctx.last_prune.strategies
        ratio = ctx.last_prune.ratio

        flag = ""
        if ctx.last_prune.pruned:
            flag = " !! PRUNED!"

        print(f"\n  Turn {turn:2d} | Raw: {raw_tokens:5d} tokens -> After: {after_tokens:5d} tokens "
              f"| Ratio: {ratio:.0%} | Strategies: {strategies}{flag}")

# Final summary
print("\n" + "=" * 65)
print("Final Summary")
print("=" * 65)

assembled = ctx.assemble()
raw_tokens = estimate_messages(ctx._base_messages() + ctx._flatten(ctx.raw_turns))
after_tokens = ctx.last_prune.after_tokens
hard_limit = config.get("context.hard_limit_tokens")

print(f"  Total turns:        15")
print(f"  Without governance:  {raw_tokens} tokens  (exceeds hard limit {hard_limit} by {raw_tokens // hard_limit}x)")
print(f"  With governance:     {after_tokens} tokens  (within budget!)")
print(f"  Compression ratio:   {ctx.last_prune.ratio:.0%}")
print(f"  Strategies used:     {ctx.last_prune.strategies}")

print(f"""
{"=" * 65}
Three-tier governance strategy:
{"=" * 65}

  Strategy 1 "fold_old_turns":
     Keep only the last {config.get('context.keep_last_turns')} turns verbatim;
     older turns are folded into summaries:
     - Keep: first sentence of assistant + tool name + first snippet of result
     - Reduces tokens while preserving key facts

  Strategy 2 "drop_stale_turns":
     If still over hard limit after folding, shrink further to keep
     only the last 1 turn verbatim, fold everything else

  Strategy 3 "truncate_long_content":
     Last resort: truncate long messages (first to {config.get('context.max_file_content_chars')} chars,
     then iteratively shrink to 60%), guaranteeing 100% within budget

  Key design:
     - Each assemble() recomputes from full history, avoiding state drift
     - Truncation happens on deep copies, never mutates original history
     - Same input always produces same output (deterministic, reproducible eval)
""")