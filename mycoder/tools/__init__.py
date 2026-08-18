"""工具包:组装 7 类工具并暴露工厂函数。

7 类工具:
  1 file_read    读文件
  2 file_write   写文件
  3 file_edit    编辑器式替换
  4 file_list    列文件
  5 grep_search  内容搜索
  6 shell_exec   受控命令执行
  7 memory_query 记忆查询
"""
from .base import Tool, ToolContext, ToolRegistry, ToolResult
from .file_tools import EditFileTool, GrepTool, ListFilesTool, ReadFileTool, WriteFileTool
from .memory_tool import MemoryQueryTool
from .sandbox import PathEscapeError, Workspace
from .shell_tool import ShellExecTool

__all__ = [
    "EditFileTool",
    "GrepTool",
    "ListFilesTool",
    "MemoryQueryTool",
    "PathEscapeError",
    "ReadFileTool",
    "ShellExecTool",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "Workspace",
    "WriteFileTool",
]


def build_registry(memory=None) -> ToolRegistry:
    """构建标准 7 工具注册表(工具自身无状态,memory 经 ToolContext 注入)。"""
    return ToolRegistry([
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        ListFilesTool(),
        GrepTool(),
        ShellExecTool(),
        MemoryQueryTool(),
    ])
