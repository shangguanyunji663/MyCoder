"""结构化记忆系统:分层存储 + 持久化 + 检索。

三层结构:
  * 任务摘要(task):每个任务的 目标/状态/结论/关键决策/涉及文件;
  * 文件摘要(file):每个文件的 哈希指纹/摘要/符号(函数类导入)/最近访问;
  * 关联记忆(relation):任务↔文件、任务↔父任务(follow-up)、文件↔文件(依赖)。

关键收益路径:follow-up 任务只需要【任务摘要 + 相关文件摘要】就能继续推进,
不必再打开文件重读 —— 这正是"重复读文件 -> 0"的机制来源。文件摘要以
哈希指纹为一致性依据:内容未变则摘要仍有效,内容变了会自动作废重记。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..util import ensure_dir, json_dump, now_iso, sha256_text, truncate
from .vectors import BM25, EmbeddingProvider, HashingEmbedder, HybridRetriever, VectorIndex, tokenize

_SYMBOL_RE = re.compile(r"^\s*(def |class |async def |import |from )")

RelationsDict = dict[str, dict[str, Any]]


def summarize_file_content(content: str, max_chars: int = 600) -> tuple[str, list[str]]:
    """确定性文件摘要:头部片段 + 关键符号(函数/类/导入行),不依赖模型。"""
    lines = content.splitlines()
    head = "\n".join(lines[:8])
    summary = truncate(head, max_chars)
    symbols = [ln.strip() for ln in lines if _SYMBOL_RE.match(ln)][:20]
    return summary, symbols


@dataclass
class TaskRecord:
    task_id: str
    goal: str = ""
    status: str = "running"          # running | completed | error
    summary: str = ""
    key_decisions: list = field(default_factory=list)
    files: list = field(default_factory=list)   # 关联文件相对路径
    parent_task_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class FileRecord:
    path: str
    sha256: str = ""
    size: int = 0
    summary: str = ""
    symbols: list = field(default_factory=list)
    acquired_from: list = field(default_factory=list)   # 产生该摘要的任务
    last_read_at: str = ""
    updated_at: str = ""

    def valid(self) -> bool:
        return bool(self.sha256)


class StructuredMemory:
    """三层记忆的容器 + 磁盘持久化 + 检索。"""

    def __init__(self, root: str | Path, enabled: bool = True, load: bool = True,
                 retrieval_mode: str = "substring", embedder: EmbeddingProvider | None = None,
                 hybrid_alpha: float = 0.5):
        self.root = Path(root)
        self.enabled = enabled
        self.tasks: dict[str, TaskRecord] = {}
        self.files: dict[str, FileRecord] = {}
        # 关联:task->files, task->parent
        self.relations: RelationsDict = {"task_files": {}, "task_parent": {}}
        # 检索模式:substring(默认,向后兼容) | vector | hybrid
        self.retrieval_mode = retrieval_mode
        self.embedder = embedder or HashingEmbedder()
        self.hybrid_alpha = hybrid_alpha
        self._retrievers: dict[str, HybridRetriever] = {}  # 按 kind 缓存
        if enabled and load:
            self.load()

    # ------------------------------------------------------------------
    # 任务摘要
    def remember_task(self, task_id: str, goal: str = "", status: str = "running",
                      summary: str = "", key_decisions: list | None = None,
                      files: list | None = None, parent_task_id: str | None = None) -> TaskRecord:
        rec = self.tasks.get(task_id)
        now = now_iso()
        if rec is None:
            rec = TaskRecord(task_id=task_id, created_at=now, updated_at=now)
            self.tasks[task_id] = rec
        if goal:
            rec.goal = goal
        if status:
            rec.status = status
        if summary:
            rec.summary = summary
        if key_decisions:
            rec.key_decisions = list(key_decisions)
        if files is not None:
            rec.files = sorted(set(rec.files) | set(files))
            for f in files:
                self.link_task_file(task_id, f)
        if parent_task_id is not None:
            rec.parent_task_id = parent_task_id
            self.relations["task_parent"][task_id] = parent_task_id
        rec.updated_at = now
        if self.enabled:
            self.save()
        return rec

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self.tasks.get(task_id)

    # ------------------------------------------------------------------
    # 文件摘要
    def remember_file(self, path: str, content: str = "", sha256: str = "",
                      task_id: str | None = None, content_hash: str = "",
                      summary: str = "", symbols: list | None = None) -> tuple[bool, FileRecord]:
        """记录/更新文件摘要。返回 (是否真正更新, 记录)。内容哈希一致则跳过(去重关键)。"""
        digest = sha256 or content_hash or (sha256_text(content) if content else "")
        rec = self.files.get(path)
        now = now_iso()
        if rec is not None and rec.sha256 == digest and digest:
            # 内容未变:摘要仍有效,不重算、不计为一次"重读"
            rec.last_read_at = now
            if task_id and task_id not in rec.acquired_from:
                rec.acquired_from.append(task_id)
            return False, rec
        if summary or symbols is not None:
            summary_text = summary
            symb = list(symbols or [])
        elif content:
            summary_text, symb = summarize_file_content(content)
        else:
            summary_text, symb = "", []
        updated = True
        if rec is None:
            rec = FileRecord(path=path, updated_at=now, last_read_at=now)
            self.files[path] = rec
        rec.sha256 = digest
        rec.size = len(content) if content else rec.size
        rec.summary = summary_text or rec.summary
        if symb:
            rec.symbols = symb
        if task_id and task_id not in rec.acquired_from:
            rec.acquired_from.append(task_id)
        rec.updated_at = now
        rec.last_read_at = now
        if task_id:
            self.link_task_file(task_id, path)
        if self.enabled:
            self.save()
        return updated, rec

    def get_file(self, path: str) -> FileRecord | None:
        return self.files.get(path)

    def has_fresh_summary(self, path: str, digest: str) -> bool:
        """判断某文件是否有与给定哈希一致的摘要(一致=>无需重读)。"""
        rec = self.files.get(path)
        return rec is not None and rec.sha256 == digest and bool(digest)

    # ------------------------------------------------------------------
    # 关联记忆
    def link_task_file(self, task_id: str, path: str) -> None:
        lst = self.relations.setdefault("task_files", {}).setdefault(task_id, [])
        if path not in lst:
            lst.append(path)

    def files_for_task(self, task_id: str) -> list[str]:
        return list(self.relations.get("task_files", {}).get(task_id, []))

    def parent_of(self, task_id: str) -> str | None:
        return self.relations.get("task_parent", {}).get(task_id)

    # ------------------------------------------------------------------
    # 检索 / follow-up 上下文(检索实现见下方 search / rank / _search_substring_legacy)
    def followup_context(self, task_id: str | None = None,
                         parent_task_id: str | None = None, max_files: int = 12) -> str:
        """生成注入 follow-up 任务的记忆块(任务摘要 + 文件摘要)。"""
        blocks: list[str] = ["# 结构化记忆(来自之前的任务)"]
        pid = parent_task_id or (self.parent_of(task_id) if task_id else None)
        if pid and pid in self.tasks:
            t = self.tasks[pid]
            blocks.append(f"- 父任务 {pid}: {truncate(t.summary or t.goal, 200)}")
            for f in self.relations["task_files"].get(pid, [])[:max_files]:
                rec = self.files.get(f)
                if rec:
                    blocks.append(f"- 文件 {f}: {truncate(rec.summary, 160)}")
        return "\n".join(blocks)

    # ------------------------------------------------------------------
    # 检索(子串 / 向量 / 混合)
    def _corpus_map(self, kind: str = "all") -> dict[str, dict]:
        """把三层记忆编译为 {doc_id: {kind, text, record}},供检索打分。"""
        docs: dict[str, dict] = {}
        if kind in ("task", "all"):
            for tid, rec in self.tasks.items():
                text = f"{tid} {rec.goal} {rec.summary} {' '.join(rec.key_decisions)}"
                docs[f"task:{tid}"] = {"kind": "task", "text": text, "record": rec}
        if kind in ("file", "all"):
            for path, frec in self.files.items():
                text = f"{path} {frec.summary} {' '.join(frec.symbols)}"
                docs[f"file:{path}"] = {"kind": "file", "text": text, "record": frec}
        return docs

    def _build_retriever(self, kind: str) -> HybridRetriever:
        if kind not in self._retrievers:
            docs = self._corpus_map(kind)
            index = VectorIndex(self.embedder)
            bm25 = BM25()
            for doc_id, d in docs.items():
                index.add(doc_id, d["text"])
                bm25.add(doc_id, tokenize(d["text"]))
            self._retrievers[kind] = HybridRetriever(index, bm25, self.embedder,
                                                     alpha=self.hybrid_alpha)
        return self._retrievers[kind]

    def rank(self, query: str, mode: str | None = None, top_k: int = 5,
             kind: str = "all") -> list[tuple[str, float]]:
        """返回 [(doc_id, score)] 降序。mode 默认取 self.retrieval_mode。

        - substring:查询作为子串命中得 1.0 分(向后兼容原语义);
        - vector   :仅稠密余弦;
        - hybrid   :α·cosine + (1-α)·bm25。
        """
        mode = mode or self.retrieval_mode
        docs = self._corpus_map(kind)
        if not docs:
            return []
        if mode == "substring":
            scored = [(did, 1.0) for did, d in docs.items()
                      if query.lower() in d["text"].lower()]
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
        retriever = self._build_retriever(kind)
        if mode == "vector":
            q_vec = self.embedder.embed(query)
            return retriever.index.search(q_vec, top_k)
        # hybrid
        return retriever.rank(query, top_k)

    def _format_doc(self, doc: dict) -> str:
        rec = doc["record"]
        if doc["kind"] == "task":
            t = rec
            files = ", ".join(t.files) or "(无)"
            return (f"[任务] {t.task_id} 状态={t.status}\n  目标: {truncate(t.goal, 200)}"
                    f"\n  结论: {truncate(t.summary, 200)}\n  关联文件: {files}")
        f = rec
        sym = ", ".join(f.symbols[:12]) or "(无符号)"
        return f"[文件] {f.path}\n  摘要: {truncate(f.summary, 200)}\n  符号: {sym}"

    def search(self, query: str, kind: str = "all", mode: str | None = None) -> str:
        """面向 memory_query 工具的检索接口,返回可读文本片段。

        与原实现向后兼容:默认 substring 模式输出格式一致;开启 vector/hybrid
        后按相关度排序返回同样的块结构。
        """
        if mode is None:
            mode = self.retrieval_mode
        if mode == "substring" and not self._retrievers:
            # 向后兼容:沿用原逐条子串匹配输出格式(含 relation 层)
            return self._search_substring_legacy(query, kind)
        ranked = self.rank(query, mode=mode, top_k=5, kind=kind)
        docs = self._corpus_map(kind)
        blocks = [self._format_doc(docs[did]) for did, _ in ranked if did in docs]
        return "\n\n".join(blocks)

    def _search_substring_legacy(self, query: str, kind: str = "all") -> str:
        """原版子串匹配(relation 层也参与),仅在默认 substring 且未启用向量时。"""
        parts: list[str] = []
        q = query.lower()
        if kind in ("task", "all"):
            for tid, rec in self.tasks.items():
                if q in tid.lower() or q in rec.goal.lower() or q in rec.summary.lower():
                    files = ", ".join(rec.files) or "(无)"
                    parts.append(f"[任务] {tid} 状态={rec.status}\n  目标: {truncate(rec.goal, 200)}"
                                 f"\n  结论: {truncate(rec.summary, 200)}\n  关联文件: {files}")
        if kind in ("file", "all"):
            for path, frec in self.files.items():
                if q in path.lower() or q in frec.summary.lower():
                    sym = ", ".join(frec.symbols[:12]) or "(无符号)"
                    parts.append(f"[文件] {path}\n  摘要: {truncate(frec.summary, 200)}\n  符号: {sym}")
        if kind in ("relation", "all"):
            for tid, files in self.relations["task_files"].items():
                if q in tid.lower() or any(q in f.lower() for f in files):
                    parts.append(f"[关联] 任务 {tid} -> {', '.join(files)}")
            for tid, parent in self.relations["task_parent"].items():
                if q in tid.lower() or q in str(parent).lower():
                    parts.append(f"[关联] follow-up {tid} -> 父任务 {parent}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # 持久化
    def save(self) -> None:
        if not self.enabled:
            return
        ensure_dir(self.root)
        json_dump({k: asdict(v) for k, v in self.tasks.items()}, self.root / "tasks.json")
        json_dump({k: asdict(v) for k, v in self.files.items()}, self.root / "files.json")
        json_dump(self.relations, self.root / "relations.json")

    def load(self) -> None:
        def _read(name):
            p = self.root / name
            return p.read_text(encoding="utf-8") if p.exists() else "{}"

        try:
            tasks = json.loads(_read("tasks.json"))
            self.tasks = {k: TaskRecord(**v) for k, v in tasks.items()}
        except Exception:
            self.tasks = {}
        try:
            files = json.loads(_read("files.json"))
            self.files = {k: FileRecord(**v) for k, v in files.items()}
        except Exception:
            self.files = {}
        try:
            loaded = json.loads(_read("relations.json"))
            # 归一化:保证三层结构键始终存在,避免旧文件缺键导致 KeyError
            if isinstance(loaded, dict):
                self.relations["task_files"] = loaded.get("task_files", {})
                self.relations["task_parent"] = loaded.get("task_parent", {})
            else:
                self.relations["task_files"] = {}
                self.relations["task_parent"] = {}
        except Exception:
            self.relations["task_files"] = {}
            self.relations["task_parent"] = {}

    def stats(self) -> dict:
        return {"tasks": len(self.tasks), "files": len(self.files),
                "relations": sum(len(v) for v in self.relations["task_files"].values())}
