"""工作区沙箱(工具调用的隔离边界)。

安全关键点(路径逃逸防护):
  1. 拒绝绝对路径(由 config.workspace.allow_absolute 控制);
  2. 相对路径先拼到 root 再 resolve() —— resolve 会展开 `..` 与符号链接;
  3. 再用 commonpath 断言"最终绝对路径真的在 root 之内",双保险拦截 `../` 逃逸;
  4. 提供 snapshot() 文件指纹(路径->SHA256),供 checkpoint 漂移识别使用。

Workspace 不直接对业务开放裸文件句柄,只暴露受控的文件读写原语。
"""
from __future__ import annotations

import os
from pathlib import Path

from ..util import ensure_dir, sha256_file


class PathEscapeError(Exception):
    """路径逃逸:目标路径落在工作区之外。"""


class Workspace:
    def __init__(self, root: str | Path, allow_absolute: bool = False):
        self.root = Path(root).expanduser().resolve()
        self.allow_absolute = allow_absolute
        ensure_dir(self.root)

    # ------------------------------------------------------------------
    def resolve(self, path: str | Path) -> Path:
        """把用户给出的路径安全解析到工作区内部,否则抛 PathEscapeError。"""
        raw = str(path)
        if "\x00" in raw:
            raise PathEscapeError("路径含空字节,已拒绝")
        p = Path(path)
        if p.is_absolute():
            if not self.allow_absolute:
                raise PathEscapeError(f"绝对路径被拒绝(工作区隔离): {path}")
            candidate = p.resolve()
        else:
            # 归一化:去掉前导 './'、正常化分隔符
            candidate = (self.root / p).resolve()
        # commonpath 校验(比 startswith 更稳,规避 /root_evil 前缀混淆)
        try:
            common = os.path.commonpath([str(self.root), str(candidate)])
        except ValueError:
            raise PathEscapeError(f"路径逃逸被拦截: {path}") from None
        if common != str(self.root):
            raise PathEscapeError(f"路径逃逸被拦截(超出工作区): {path}")
        return candidate

    def rel(self, path: str | Path) -> str:
        """返回相对工作区的规范化相对路径(兼容传入已解析的绝对路径)。"""
        p = Path(path)
        if p.is_absolute():
            candidate = p.resolve()
            try:
                common = os.path.commonpath([str(self.root), str(candidate)])
            except ValueError:
                raise PathEscapeError(f"路径逃逸被拦截: {path}") from None
            if common != str(self.root):
                raise PathEscapeError(f"路径逃逸被拦截(超出工作区): {path}")
            return str(candidate.relative_to(self.root))
        return str(self.resolve(path).relative_to(self.root))

    # ------------------------------------------------------------------
    # 受控读/写/列目录
    def exists(self, path: str | Path) -> bool:
        return self.resolve(path).exists()

    def read_text(self, path: str | Path, default: str | None = None) -> str | None:
        p = self.resolve(path)
        if not p.exists():
            return default
        return p.read_text(encoding="utf-8", errors="replace")

    def write_text(self, path: str | Path, content: str) -> Path:
        p = self.resolve(path)
        ensure_dir(p.parent)
        p.write_text(content, encoding="utf-8")
        return p

    # ------------------------------------------------------------------
    # 指纹(供漂移识别)
    def snapshot(self) -> dict[str, str]:
        """返回 {相对路径: sha256},排除隐藏目录与 __pycache__。"""
        out: dict[str, str] = {}
        for f in self._iter_safe():
            try:
                out[str(f.relative_to(self.root))] = sha256_file(f)
            except OSError:
                continue
        return out

    def _iter_safe(self):
        for f in sorted(self.root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(self.root)
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            yield f

    def list_files(self, pattern: str = "*") -> list[str]:
        """glob 列出文件(相对路径,排除隐藏/缓存)。"""

        results: set[str] = set()
        for f in self.root.rglob(pattern):
            if f.is_file():
                rel = f.relative_to(self.root)
                if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                    continue
                results.add(rel.as_posix())
        return sorted(results)
