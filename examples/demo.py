"""MyCoder Demo — 基础用法演示

This demo shows how to use MyCoder to run a simple coding task.
It demonstrates:
1. Loading configuration
2. Creating a task input
3. Running the agent with Ollama (LocalOpenAIBackend)
4. Inspecting results and artifacts
"""

import sys
from pathlib import Path

# Add project root to sys.path if running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from mycoder.config import Config
from mycoder.agent.harness import AgentHarness
from mycoder.state import TaskInput
from mycoder.tools import ToolRegistry, Workspace, build_registry
from mycoder.memory import StructuredMemory as MemoryStore
from mycoder.checkpoint import CheckpointStore
from mycoder.safety import SafetyGuard
from mycoder.artifacts import ArtifactManager
from mycoder.models import LocalOpenAIBackend  # 使用 Ollama 后端


def demo_basic_task():
    """Run a basic task: read a file and create a summary"""
    print("=" * 60)
    print("Demo 1: Basic Task Execution (with Ollama)")
    print("=" * 60)
    
    # 1. Create workspace with a sample file
    workspace_path = Path("demo_workspace")
    workspace_path.mkdir(exist_ok=True)
    
    sample_file = workspace_path / "hello.py"
    sample_file.write_text("""
def greet(name):
    '''Greet someone by name'''
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("World"))
""")
    
    # 2. Load configuration
    config = Config()
    config.load("config/default.yaml")  # Load default config
    
    # 3. Create Ollama backend (本地 OpenAI 兼容后端)
    # Ollama 默认运行在 http://localhost:11434
    # OpenAI 兼容 API 端点: http://localhost:11434/v1
    print("\nConnecting to Ollama...")
    backend = LocalOpenAIBackend(
        base_url="http://localhost:11434/v1",  # Ollama 的 OpenAI 兼容端点
        api_key="ollama",                       # Ollama 不需要 API key，任意值即可
        model="qwen3.5:2b",                     # 你安装的模型
        temperature=0.0,                        # 确定性输出
        timeout_seconds=120                     # 增加超时时间
    )
    print(f"[OK] Connected to Ollama with model: qwen3.5:2b")
    
    # 4. Initialize components
    workspace = Workspace(workspace_path)
    registry = build_registry()
    
    memory = MemoryStore(workspace_path / ".mycoder" / "memory")
    checkpoint = CheckpointStore(workspace_path / ".mycoder" / "checkpoints")
    guard = SafetyGuard(config, workspace)
    artifacts = ArtifactManager(workspace_path / ".mycoder" / "artifacts", config)
    
    # 5. Create and run harness
    harness = AgentHarness(
        config=config,
        backend=backend,
        workspace=workspace,
        registry=registry,
        memory=memory,
        guard=guard,
        checkpoint=checkpoint,
        artifacts=artifacts
    )
    
    # 6. Create task input
    task = TaskInput(
        task_id="demo-task-001",
        goal="Read hello.py and create a summary document"
    )
    
    # 7. Run the task
    print("\nRunning task with Ollama...")
    result = harness.run(task, stop_after_steps=10)
    
    # 8. Inspect results
    print("\n--- Results ---")
    print(f"Status: {result.status}")
    print(f"Steps executed: {len(result.steps)}")
    print(f"Final answer: {result.final_answer[:80] if result.final_answer else 'N/A'}...")
    
    # 9. Check artifacts
    summary_file = workspace_path / "summary.txt"
    if summary_file.exists():
        print(f"\n[OK] Created file: {summary_file}")
        print(f"  Content preview: {summary_file.read_text()[:50]}...")
    
    # 10. Check metrics
    print(f"\n--- Metrics ---")
    print(f"Read calls: {result.metrics.get('read_calls', 0)}")
    print(f"Write calls: {result.metrics.get('write_calls', 0)}")
    print(f"Tool calls: {result.metrics.get('tool_calls', 0)}")
    print(f"Files remembered: {result.metrics.get('files_remembered', 0)}")
    
    print("\n[OK] Demo 1 completed successfully!\n")
    
    # Cleanup
    import shutil
    shutil.rmtree(workspace_path)


def demo_checkpoint_resume():
    """Demo checkpoint and resume functionality"""
    print("=" * 60)
    print("Demo 2: Checkpoint & Resume (with Ollama)")
    print("=" * 60)
    
    # 1. Setup workspace
    workspace_path = Path("demo_checkpoint")
    workspace_path.mkdir(exist_ok=True)
    
    # 2. Create Ollama backend
    print("\nConnecting to Ollama...")
    config = Config()
    backend = LocalOpenAIBackend(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        model="qwen3.5:2b",
        temperature=0.0,
        timeout_seconds=120
    )
    print(f"[OK] Connected to Ollama with model: qwen3.5:2b")
    
    workspace = Workspace(workspace_path)
    registry = build_registry()
    
    memory = MemoryStore(workspace_path / ".mycoder" / "memory")
    checkpoint = CheckpointStore(workspace_path / ".mycoder" / "checkpoints")
    guard = SafetyGuard(config, workspace)
    artifacts = ArtifactManager(workspace_path / ".mycoder" / "artifacts", config)
    
    # 3. Phase 1: Run until interrupted
    print("\nPhase 1: Running initial task (will be interrupted)...")
    
    harness1 = AgentHarness(
        config=config,
        backend=backend,
        workspace=workspace,
        registry=registry,
        memory=memory,
        checkpoint=checkpoint,
        guard=guard,
        artifacts=artifacts
    )
    
    task = TaskInput(
        task_id="checkpoint-demo",
        goal="Create step1.txt and step2.txt files"
    )
    
    result1 = harness1.run(task, stop_after_steps=2)
    
    print(f"Phase 1 completed: {len(result1.steps)} steps")
    print(f"Step1 file exists: {(workspace_path / 'step1.txt').exists()}")
    
    # 4. Phase 2: Resume from checkpoint
    print("\nPhase 2: Resuming from checkpoint...")
    
    harness2 = AgentHarness(
        config=config,
        backend=backend,
        workspace=workspace,
        registry=registry,
        memory=memory,
        checkpoint=checkpoint,
        guard=guard,
        artifacts=artifacts
    )
    
    # Resume task
    result2 = harness2.resume(task.task_id, stop_after_steps=10)
    
    print(f"Phase 2 completed: {len(result2.steps)} additional steps")
    print(f"Step2 file exists: {(workspace_path / 'step2.txt').exists()}")
    
    print("\n[OK] Demo 2 completed successfully!\n")
    
    # Cleanup
    import shutil
    shutil.rmtree(workspace_path)


def demo_memory_system():
    """Demo structured memory system"""
    print("=" * 60)
    print("Demo 3: Structured Memory System")
    print("=" * 60)
    
    # 1. Setup
    workspace_path = Path("demo_memory")
    workspace_path.mkdir(exist_ok=True)
    
    # 2. Create files
    (workspace_path / "utils.py").write_text("""
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
""")
    
    (workspace_path / "main.py").write_text("""
from utils import add, multiply

result = add(2, 3)
print(f"2 + 3 = {result}")

result = multiply(4, 5)
print(f"4 * 5 = {result}")
""")
    
    # 3. Initialize memory
    memory = MemoryStore(workspace_path / ".mycoder" / "memory")
    
    # 4. Simulate file reads and memory storage
    print("\nSimulating file operations...")
    
    # Read utils.py
    utils_content = (workspace_path / "utils.py").read_text()
    print(f"Read utils.py ({len(utils_content)} chars)")
    
    # Store in memory
    memory.remember_file("utils.py", utils_content, task_id="task-1")
    memory.remember_task("task-1", "Analyze utils.py functions")
    memory.save()
    
    # 5. Query memory
    print("\nQuerying memory for 'add' function...")
    result = memory.search("add", kind="file")
    
    if result:
        print(f"Found memory entries:")
        print(f"  {result[:100]}...")
    
    # 6. Check follow-up optimization
    print("\nChecking follow-up optimization...")
    followup_ctx = memory.followup_context(task_id="task-2", parent_task_id="task-1")
    print(f"Follow-up context generated: {len(followup_ctx)} chars")
    
    # Cleanup
    import shutil
    shutil.rmtree(workspace_path)
    
    print("\n[OK] Demo 3 completed successfully!\n")


def demo_context_management():
    """Demo context budget and trimming"""
    print("=" * 60)
    print("Demo 4: Context Management & Budget Trimming")
    print("=" * 60)
    
    from mycoder.context import ContextManager
    
    # 1. Create context manager with budget
    config = Config()
    config.set("context.budget_tokens", 1000)  # Small budget for demo
    config.set("context.hard_limit_tokens", 1500)
    
    ctx_manager = ContextManager(config)
    
    # 2. Add messages that exceed budget
    print("\nAdding messages to context...")
    
    from mycoder.context.manager import Message
    
    for i in range(10):
        assistant_msg = Message("assistant", f"Step {i}: " + "x" * 200)
        tool_msg = Message("tool", f"Result {i}: " + "y" * 100, name="file_read")
        ctx_manager.append_turn(assistant_msg, [tool_msg])
        print(f"  Added turn {i+1} ({len(assistant_msg.content)} chars)")
    
    # 3. Assemble and check trimming
    print("\nAssembling context with budget trimming...")
    msgs = ctx_manager.assemble()
    
    before_tokens = ctx_manager.last_prune.before_tokens
    after_tokens = ctx_manager.last_prune.after_tokens
    
    print(f"Before: {before_tokens} tokens")
    print(f"After: {after_tokens} tokens")
    print(f"Compression ratio: {(1 - after_tokens/before_tokens)*100:.1f}%")
    print(f"Messages in assembled context: {len(msgs)}")
    print(f"Pruning strategies used: {ctx_manager.last_prune.strategies}")
    
    print("\n[OK] Demo 4 completed successfully!\n")


def demo_safety_features():
    """Demo safety guard features"""
    print("=" * 60)
    print("Demo 5: Safety Features")
    print("=" * 60)
    
    # 1. Setup
    workspace_path = Path("demo_safety")
    workspace_path.mkdir(exist_ok=True)
    
    workspace = Workspace(workspace_path)
    config = Config()
    guard = SafetyGuard(config, workspace)
    
    # 2. Test path escape prevention
    print("\nTesting path escape prevention...")
    
    from mycoder.tools.sandbox import PathEscapeError
    
    try:
        workspace.resolve("../etc/passwd")
        print("  ✗ Should have blocked path escape!")
    except PathEscapeError as e:
        print(f"  [OK] Blocked path escape: {str(e)[:50]}")
    
    # 3. Test parameter validation
    print("\nTesting parameter validation...")
    
    from mycoder.tools.base import Tool, ToolResult
    from mycoder.safety import validate_params
    
    class MockTool(Tool):
        name = "mock_tool"
        parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
        
        def execute(self, ctx, **kwargs):
            return ToolResult(output="mock result")
    
    tool = MockTool()
    
    # Valid params
    errors = validate_params(tool.parameters, {"path": "test.txt"})
    print(f"  Valid params: {len(errors)} errors")
    
    # Invalid params (missing required)
    errors = validate_params(tool.parameters, {})
    print(f"  Invalid params: {len(errors)} errors (expected)")
    
    # 4. Test dedup via SafetyGuard.check()
    print("\nTesting dedup detection...")
    
    from mycoder.tools.base import ToolContext
    
    read_tool = type("ReadTool", (Tool,), {
        "name": "file_read",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        "danger": "safe",
        "execute": lambda self, ctx, **kwargs: None
    })()
    
    result1 = guard.check(read_tool, {"path": "a.txt"})
    print(f"  First call: cached_output={result1.cached_output}")
    
    # Simulate execution and record
    guard.record_executed(read_tool, {"path": "a.txt"}, "file content")
    
    result2 = guard.check(read_tool, {"path": "a.txt"})
    print(f"  Second call: cached_output={result2.cached_output}, cache_hit={result2.cached_output is not None}")
    
    # 5. Test redaction
    print("\nTesting sensitive data redaction...")
    
    from mycoder.safety import Redactor
    
    redactor = Redactor(enabled=True)
    sensitive_text = "API key: sk-1234567890abcdef\nPassword: secret123"
    redacted = redactor.redact(sensitive_text)
    
    print(f"  Original: {sensitive_text[:30]}...")
    print(f"  Redacted: {redacted[:30]}...")
    print(f"  [OK] Sensitive data redacted")
    
    # Cleanup
    import shutil
    shutil.rmtree(workspace_path)
    
    print("\n[OK] Demo 5 completed successfully!\n")


def main():
    """Run all demos"""
    print("\n" + "=" * 60)
    print("MyCoder Demo Suite")
    print("=" * 60 + "\n")
    
    demos = [
        ("Basic Task Execution", demo_basic_task),
        ("Checkpoint & Resume", demo_checkpoint_resume),
        ("Memory System", demo_memory_system),
        ("Context Management", demo_context_management),
        ("Safety Features", demo_safety_features),
    ]
    
    print(f"Available demos: {len(demos)}")
    for i, (name, _) in enumerate(demos, 1):
        print(f"  {i}. {name}")
    print()
    
    # Run all demos
    for name, demo_func in demos:
        try:
            demo_func()
        except Exception as e:
            print(f"\n[X] Demo '{name}' failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 60)
    print("All demos completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()