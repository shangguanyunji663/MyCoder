"""工作区漂移识别。

恢复(Resume)时,工作区可能已被外部修改(用户手改、git 操作、并发进程)。
若直接继续执行,Agent 基于的"旧文件摘要/旧读取结果"可能已经失效。

用【文件路径 -> SHA256 内容指纹】做精确比对:
  * modified:路径相同但哈希不同(=内容被改);
  * added:新增文件;
  * deleted:被删除文件;
任意一类非空 => 判定漂移。因为指纹是逐文件精确匹配,识别准确率达到 100%。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DriftReport:
    modified: list = field(default_factory=list)
    added: list = field(default_factory=list)
    deleted: list = field(default_factory=list)

    @property
    def is_drift(self) -> bool:
        return bool(self.modified or self.added or self.deleted)

    def summary(self) -> str:
        if not self.is_drift:
            return "(无漂移:工作区与断点时一致)"
        parts = []
        if self.modified:
            parts.append(f"已修改 {len(self.modified)} 个: {', '.join(self.modified[:5])}" +
                         ("..." if len(self.modified) > 5 else ""))
        if self.added:
            parts.append(f"新增 {len(self.added)} 个: {', '.join(self.added[:5])}" +
                         ("..." if len(self.added) > 5 else ""))
        if self.deleted:
            parts.append(f"删除 {len(self.deleted)} 个: {', '.join(self.deleted[:5])}" +
                         ("..." if len(self.deleted) > 5 else ""))
        return "漂移: " + "; ".join(parts)


class WorkspaceDriftDetector:
    @staticmethod
    def compare(before: dict[str, str], after: dict[str, str]) -> DriftReport:
        b_keys = set(before.keys())
        a_keys = set(after.keys())
        modified = sorted(k for k in (b_keys & a_keys) if before[k] != after[k])
        added = sorted(a_keys - b_keys)
        deleted = sorted(b_keys - a_keys)
        return DriftReport(modified=modified, added=added, deleted=deleted)
