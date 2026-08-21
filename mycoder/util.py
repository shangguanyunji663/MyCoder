"""通用工具函数。

集中放置小但被多处复用的纯函数:哈希、原子写、时间戳、ID 生成。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path


def now_iso() -> str:
    """本地时间 ISO8601 字符串(精确到毫秒)。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time()*1000)%1000:03d}"


def short_id(prefix: str = "") -> str:
    """短 ID:前缀 + 8 位随机十六进制,便于人类阅读轨迹。"""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def sha256_text(text: str) -> str:
    """文本内容 SHA-256(用于文件摘要指纹与脱敏前一致性)。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    """文件内容 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在并返回其 Path。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write(path: str | Path, content: str) -> None:
    """原子写文本文件:先写临时文件再替换,避免中途崩溃留下半截文件。

    Windows 上病毒扫描或索引服务可能在刚写入后短暂占用目标文件,因此对
    PermissionError 做有界重试;其他 I/O 异常仍立即向调用方报告。
    """
    p = Path(path)
    ensure_dir(p.parent)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        for attempt in range(8):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.025 * (attempt + 1))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def json_dump(obj, path: str | Path, indent: int = 2, redactor=None) -> None:
    """序列化为 JSON 落盘;支持传入 redactor 做敏感信息脱敏。"""
    text = json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
    if redactor is not None:
        text = redactor.redact(text)
    atomic_write(path, text + "\n")


def truncate(text: str, max_chars: int, head_ratio: float = 0.6) -> str:
    """保守截断长文本:保留 head_ratio 比例的头部 + 尾部,便于保留关键信息。"""
    if len(text) <= max_chars:
        return text
    head = int(max_chars * head_ratio)
    tail = max_chars - head - 30
    if tail < 0:
        return text[:max_chars]
    return text[:head] + f"\n…[截断 {len(text) - max_chars} 字符]…\n" + text[-tail:]
