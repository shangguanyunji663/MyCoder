# -*- coding: utf-8 -*-
"""Performance test using giant_test.py to stress-test MyCoder components"""
import os
import sys
import time
import statistics
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mycoder.tools import Workspace, build_registry, ToolContext
from mycoder.memory import StructuredMemory
from mycoder.context import ContextManager, estimate_tokens, estimate_messages
from mycoder.state import Message
from mycoder.checkpoint import CheckpointStore
from mycoder.config import Config

GIGANTIC_FILE = "examples/giant_test.py"
RESULTS = {}

def measure(name, func, *args, **kwargs):
    """Measure execution time of a function"""
    times = []
    for _ in range(3):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg = statistics.mean(times)
    min_t = min(times)
    max_t = max(times)
    RESULTS[name] = {"avg": avg, "min": min_t, "max": max_t, "runs": 3}
    print(f"  [{name}] avg={avg:.4f}s  min={min_t:.4f}s  max={max_t:.4f}s")
    return result

def test_file_read_performance():
    """Test file reading performance on giant file"""
    print("\n[1] File Read Performance")
    print("-" * 40)
    
    workspace = Workspace(Path(GIGANTIC_FILE).parent)
    registry = build_registry()
    ctx = ToolContext(workspace=workspace, memory=None, config=Config())
    
    # Read entire giant file
    read_tool = registry.get("file_read")
    measure("read_giant_file", read_tool.execute, ctx, path=GIGANTIC_FILE)
    
    # Read partial file (first 100 lines)
    measure("read_partial_file", read_tool.execute, ctx, path=GIGANTIC_FILE, limit=100)
    
    # Multiple reads (simulate repeated access)
    def multi_read():
        for _ in range(10):
            read_tool.execute(ctx, path=GIGANTIC_FILE, limit=50)
    measure("10x_partial_reads", multi_read)

def test_file_list_performance():
    """Test file listing performance"""
    print("\n[2] File List Performance")
    print("-" * 40)
    
    workspace = Workspace(Path(GIGANTIC_FILE).parent)
    registry = build_registry()
    ctx = ToolContext(workspace=workspace, memory=None, config=Config())
    
    list_tool = registry.get("file_list")
    measure("list_examples_dir", list_tool.execute, ctx, pattern="examples")
    measure("list_project_root", list_tool.execute, ctx, pattern=".")

def test_grep_performance():
    """Test grep search performance on giant file"""
    print("\n[3] Grep Search Performance")
    print("-" * 40)
    
    workspace = Workspace(Path(GIGANTIC_FILE).parent)
    registry = build_registry()
    ctx = ToolContext(workspace=workspace, memory=None, config=Config())
    
    grep_tool = registry.get("grep_search")
    
    # Search for common patterns
    measure("grep_class_def", grep_tool.execute, ctx, path=GIGANTIC_FILE, pattern="^class ")
    measure("grep_func_def", grep_tool.execute, ctx, path=GIGANTIC_FILE, pattern="^def func_")
    measure("grep_sort_algo", grep_tool.execute, ctx, path=GIGANTIC_FILE, pattern="def .*_sort_")
    measure("grep_design_pattern", grep_tool.execute, ctx, path=GIGANTIC_FILE, pattern="class (Singleton|Factory|Builder|Observer|Strategy|Decorator|Adapter|Proxy|Command|StateMachine|ChainOfResponsibility)")
    measure("grep_data_structure", grep_tool.execute, ctx, path=GIGANTIC_FILE, pattern="class (ListNode|LinkedList|TreeNode|BinaryTree|TrieNode|Trie|Graph)")

def test_memory_performance():
    """Test memory store performance with large content"""
    print("\n[4] Memory Store Performance")
    print("-" * 40)
    
    mem_dir = Path(".mycoder/perf_test_memory")
    if mem_dir.exists():
        import shutil
        shutil.rmtree(mem_dir)
    mem_dir.mkdir(parents=True, exist_ok=True)
    
    memory = StructuredMemory(mem_dir)
    
    # Read giant file content
    giant_content = Path(GIGANTIC_FILE).read_text(encoding="utf-8")
    
    # Store large file record
    def store_giant_record():
        memory.remember_file(
            path=GIGANTIC_FILE,
            content=giant_content,
            task_id="perf-test",
            summary="Giant test file with 4669 lines"
        )
    measure("store_giant_file_record", store_giant_record)
    
    # Query memory
    def query_memory():
        return memory.search("func", kind="all")
    measure("memory_search_func", query_memory)
    
    def query_class():
        return memory.search("class", kind="all")
    measure("memory_search_class", query_memory)
    
    def query_sort():
        return memory.search("sort", kind="all")
    measure("memory_search_sort", query_memory)

def test_context_performance():
    """Test context management performance with large messages"""
    print("\n[5] Context Management Performance")
    print("-" * 40)
    
    # Create large messages
    giant_content = Path(GIGANTIC_FILE).read_text(encoding="utf-8")
    
    # Token estimation
    def estimate_giant_tokens():
        return estimate_tokens(giant_content)
    measure("estimate_giant_tokens", estimate_giant_tokens)
    
    # Create multiple large messages
    messages = [
        Message(role="user", content=f"Part {i}: {giant_content[:5000]}")
        for i in range(5)
    ]
    
    def estimate_multi_messages():
        return estimate_messages(messages)
    measure("estimate_5x_large_messages", estimate_multi_messages)
    
    # Context manager with large content
    config = Config()
    config.set("context.budget_tokens", 8000)
    ctx_mgr = ContextManager(config=config)
    
    def assemble_context():
        ctx_mgr2 = ContextManager(config=config)
        for msg in messages:
            ctx_mgr2.append_turn(msg, [])
        return ctx_mgr2.assemble()
    measure("assemble_large_context", assemble_context)

def test_checkpoint_performance():
    """Test checkpoint save/load performance"""
    print("\n[6] Checkpoint Performance")
    print("-" * 40)
    
    cp_dir = Path(".mycoder/perf_test_checkpoints")
    if cp_dir.exists():
        import shutil
        shutil.rmtree(cp_dir)
    cp_dir.mkdir(parents=True, exist_ok=True)
    
    checkpoint = CheckpointStore(str(cp_dir))
    
    # Create large state
    giant_content = Path(GIGANTIC_FILE).read_text(encoding="utf-8")
    state = {
        "task_id": "perf-test",
        "messages": [
            {"role": "user", "content": giant_content[:10000]},
            {"role": "assistant", "content": giant_content[:5000]},
        ],
        "metrics": {"steps": 100, "tool_calls": 50},
        "workspace_files": {GIGANTIC_FILE: giant_content[:20000]}
    }
    
    def save_checkpoint():
        checkpoint.save("perf-task", state)
    measure("save_large_checkpoint", save_checkpoint)
    
    def load_checkpoint():
        return checkpoint.load("perf-task")
    measure("load_large_checkpoint", load_checkpoint)

def test_workspace_operations():
    """Test workspace operations with large files"""
    print("\n[7] Workspace Operations Performance")
    print("-" * 40)
    
    ws_dir = Path(".mycoder/perf_test_workspace")
    if ws_dir.exists():
        import shutil
        shutil.rmtree(ws_dir)
    ws_dir.mkdir(parents=True, exist_ok=True)
    
    workspace = Workspace(ws_dir)
    
    # Write large content
    giant_content = Path(GIGANTIC_FILE).read_text(encoding="utf-8")
    
    def write_large_file():
        workspace.write_text("large_output.py", giant_content)
    measure("write_large_file", write_large_file)
    
    def read_large_file():
        return workspace.read_text("large_output.py")
    measure("read_large_file", read_large_file)
    
    # Multiple small writes
    def write_many_small():
        for i in range(100):
            workspace.write_text(f"small_{i:03d}.py", f"# Small file {i}\ndef func_{i}(): pass\n")
    measure("write_100_small_files", write_many_small)
    
    def list_many_files():
        return workspace.list_files()
    measure("list_100_plus_files", list_many_files)

def test_tool_registry_performance():
    """Test tool registry operations"""
    print("\n[8] Tool Registry Performance")
    print("-" * 40)
    
    def build_registry_many():
        for _ in range(100):
            build_registry()
    measure("build_registry_100x", build_registry_many)
    
    registry = build_registry()
    
    def get_all_tools():
        tools = []
        for name in ["file_read", "file_write", "file_edit", "file_list", 
                     "grep_search", "shell_exec", "memory_query"]:
            tools.append(registry.get(name))
        return tools
    measure("get_all_7_tools", get_all_tools)
    
    def get_tool_schemas():
        return registry.schemas()
    measure("get_all_tool_schemas", get_tool_schemas)

def print_summary():
    """Print performance summary"""
    print("\n" + "=" * 60)
    print("PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"{'Test':<35} {'Avg(s)':<10} {'Min(s)':<10} {'Max(s)':<10}")
    print("-" * 65)
    
    for name, data in RESULTS.items():
        print(f"{name:<35} {data['avg']:<10.4f} {data['min']:<10.4f} {data['max']:<10.4f}")
    
    print("\n" + "=" * 60)
    total_tests = len(RESULTS)
    total_time = sum(d["avg"] for d in RESULTS.values())
    print(f"Total tests: {total_tests}")
    print(f"Total time: {total_time:.2f}s")
    print("=" * 60)

def main():
    print("=" * 60)
    print("MyCoder Performance Test Suite")
    print(f"Test file: {GIGANTIC_FILE}")
    
    # Check if test file exists
    if not Path(GIGANTIC_FILE).exists():
        print(f"ERROR: Test file {GIGANTIC_FILE} not found!")
        print("Run generate_test_file.py first.")
        return
    
    file_size = Path(GIGANTIC_FILE).stat().st_size / 1024
    line_count = sum(1 for _ in open(GIGANTIC_FILE, 'r', encoding='utf-8'))
    print(f"File size: {file_size:.1f} KB, Lines: {line_count}")
    print("=" * 60)
    
    start_total = time.perf_counter()
    
    test_file_read_performance()
    test_file_list_performance()
    test_grep_performance()
    test_memory_performance()
    test_context_performance()
    test_checkpoint_performance()
    test_workspace_operations()
    test_tool_registry_performance()
    
    elapsed_total = time.perf_counter() - start_total
    
    print_summary()
    print(f"\nTotal execution time: {elapsed_total:.2f}s")
    
    # Cleanup
    for d in [".mycoder/perf_test_memory", ".mycoder/perf_test_checkpoints", 
              ".mycoder/perf_test_workspace"]:
        p = Path(d)
        if p.exists():
            import shutil
            shutil.rmtree(p)

if __name__ == "__main__":
    main()