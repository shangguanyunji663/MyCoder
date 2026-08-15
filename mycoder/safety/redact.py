"""敏感信息脱敏。

对运行轨迹、工件、报告里可能出现的密钥/口令做正则替换,防止把
API Key、AWS AKIA、GitHub Token、私钥等写进本地磁盘与复盘材料。
"""
from __future__ import annotations

import re

# (正则, 替换片段):顺序匹配,靠前的优先
DEFAULT_PATTERNS: list[tuple[str, str]] = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----(.*?)-----END [A-Z ]*PRIVATE KEY-----",
     "[REDACTED_PRIVATE_KEY]"),
    (r"(?i)\bsk-[A-Za-z0-9]{16,}\b", "[REDACTED_API_KEY]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    (r"\bghp_[0-9A-Za-z]{20,}\b", "[REDACTED_GITHUB_TOKEN]"),
    (r"(?i)\b(api[_-]?key|secret|token|passwd|password)\s*([:=])\s*[^\s\"']+",
     r"\1\2 [REDACTED]"),
    (r"(?i)Bearer\s+[A-Za-z0-9._-]{6,}", "Bearer [REDACTED]"),
]


class Redactor:
    def __init__(self, patterns: list[tuple[str, str]] | None = None, enabled: bool = True):
        self.enabled = enabled
        self.patterns = [(re.compile(p, re.DOTALL), r) for p, r in (patterns or DEFAULT_PATTERNS)]

    def redact(self, text: str) -> str:
        if not self.enabled or not text:
            return text
        for regex, repl in self.patterns:
            text = regex.sub(repl, text)
        return text

    def __call__(self, text: str) -> str:
        return self.redact(text)