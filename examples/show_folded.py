"""Show what the assembled/folded messages look like."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mycoder.config import Config
from mycoder.context import ContextManager, estimate_messages
from mycoder.state import Message

giant = Path("examples/giant_test.py").read_text(encoding="utf-8")
lines = giant.splitlines()

config = Config()
config.set("context.hard_limit_tokens", 6000)
config.set("context.keep_last_turns", 6)
config.set("context.max_file_content_chars", 8000)

ctx = ContextManager(config)
ctx.set_task("Refactor giant_test.py", ["giant_test.py"])

for turn in range(1, 16):
    offset = (turn * 50) % max(1, len(lines) - 300)
    chunk = "\n".join(lines[offset:offset + 300])
    a = Message("assistant",
        f"Turn {turn}: read lines {offset}-{offset+300}, "
        f"found {chunk.count('def func_')} funcs.")
    t = Message("tool",
        f"# lines {offset}..{offset+300}\n\n{chunk[:4000]}",
        name="file_read")
    ctx.append_turn(a, [t])

assembled = ctx.assemble()

print("=== ASSEMBLED MESSAGES (sent to model) ===")
print()
for i, m in enumerate(assembled):
    print(f"--- Message {i} | role={m.role} | ({len(m.content)} chars) ---")
    content = m.content[:500]
    if len(m.content) > 500:
        content += "\n...[truncated]"
    print(content)
    print()

print(f"Total: {ctx.last_prune.after_tokens} tokens")
print(f"Raw:   {estimate_messages(ctx._base_messages() + ctx._flatten(ctx.raw_turns))} tokens")
print(f"Compression: {ctx.last_prune.ratio:.0%}")
print(f"Strategies:  {ctx.last_prune.strategies}")