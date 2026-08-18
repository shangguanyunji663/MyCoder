"""向量记忆检索(可选增强)。

为什么需要它:原 StructuredMemory.search 是子串匹配(substring),对"同义改写"
查询无能为力 —— 查询词与记忆文本没有完全相同的子串时就检索不到。本模块提供
可插拔的语义/混合检索:

  * EmbeddingProvider 接口 + HashingEmbedder(零依赖、确定性、字符 n-gram 哈希,
    默认实现,不引入任何外部依赖,保证离线 CI 与既有测试不回归);
  * FastEmbedEmbedder(可选依赖 fastembed,默认 bge-small;README 注明升级路径);
  * VectorIndex:余弦相似度 + 增量更新 + 持久化;
  * BM25:纯 Python 实现(词/字级分词,兼容中英文);
  * HybridRetriever:score = α·cosine + (1-α)·bm25,结合稠密向量与稀疏词频。

设计原则:默认仍是 substring(向后兼容),只有显式开启 retrieval.mode ∈
{vector, hybrid} 时才走向量/混合路径;核心零依赖,fastembed 缺失时优雅降级。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """中英文统一分词:ASCII 连续字母数字作为一个 token,每个汉字单独成 token。"""
    return _TOKEN_RE.findall(text.lower())


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度(输入为 L2 归一化向量时即点积)。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------
# 嵌入器(EmbeddingProvider)
# --------------------------------------------------------------------------
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """返回定长浮点向量。"""

    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""


class HashingEmbedder(EmbeddingProvider):
    """零依赖、确定性字符 n-gram 哈希嵌入器(默认)。

    把文本切成字符 n-gram,对每段做稳定哈希(MD5,避免 Python hash 随机化)落入
    dim 个桶,累加后 L2 归一化。同一文本必得同一向量(确定性),且共享字符片段的
    文本会有较高余弦相似度 —— 因此同义改写(共享汉字)也能被部分召回。
    """

    def __init__(self, dim: int = 256, ngram: int = 2, include_unigram: bool = True):
        self._dim = dim
        self._ngram = ngram
        self._include_unigram = include_unigram

    def dim(self) -> int:
        return self._dim

    @staticmethod
    def _grams(text: str, n: int) -> list[str]:
        if not text:
            return []
        if len(text) <= n:
            return [text]
        return [text[i:i + n] for i in range(len(text) - n + 1)]

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        norm_text = (text or "").lower().strip()
        grams: list[str] = []
        if self._include_unigram:
            grams += list(norm_text)
        grams += self._grams(norm_text, self._ngram)
        if not grams:
            return vec
        for g in grams:
            digest = hashlib.md5(g.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            vec[idx] += 1.0
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class FastEmbedEmbedder(EmbeddingProvider):
    """可选依赖 fastembed 的真实语义嵌入器(默认 bge-small)。

    仅在显式选用时导入 fastembed;未安装时抛清晰错误,不污染核心零依赖运行。
    升级路径见 README:pip install "mycoder-harness[vector]"。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", cache_dir: str | None = None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None

    def _ensure(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore
            except ImportError as e:  # pragma: no cover - 可选依赖
                raise RuntimeError(
                    "使用 FastEmbedEmbedder 需要先安装 fastembed:"
                    " pip install 'mycoder-harness[vector]'") from e
            self._model = TextEmbedding(model_name=self.model_name,
                                        cache_dir=self.cache_dir)

    def dim(self) -> int:
        # bge-small 系列均为 384 维
        return 384

    def embed(self, text: str) -> list[float]:
        self._ensure()
        vec = list(self._model.embed([text or ""]))[0]  # pragma: no cover - 需真实模型
        return [float(x) for x in vec]


# --------------------------------------------------------------------------
# 向量索引
# --------------------------------------------------------------------------
class VectorIndex:
    """余弦相似度向量索引:增量 add + 持久化 + top-k 检索。"""

    def __init__(self, embedder: EmbeddingProvider):
        self.embedder = embedder
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.vectors: list[list[float]] = []

    def add(self, doc_id: str, text: str, vector: list[float] | None = None) -> None:
        vec = vector if vector is not None else self.embedder.embed(text)
        # 同 id 去重:覆盖旧向量
        if doc_id in self.ids:
            i = self.ids.index(doc_id)
            self.vectors[i] = vec
            self.texts[i] = text
            return
        self.ids.append(doc_id)
        self.texts.append(text)
        self.vectors.append(vec)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        scored = [(i, cosine(query_vector, v)) for i, v in enumerate(self.vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(self.ids[i], float(s)) for i, s in scored[:top_k]]

    def save(self, path: str | Path) -> None:
        payload = {
            "model": type(self.embedder).__name__,
            "dim": self.embedder.dim(),
            "docs": [{"id": i, "text": t} for i, t in zip(self.ids, self.texts)],
            "vectors": self.vectors,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, embedder: EmbeddingProvider) -> VectorIndex:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        idx = cls(embedder)
        idx.ids = [d["id"] for d in data["docs"]]
        idx.texts = [d["text"] for d in data["docs"]]
        idx.vectors = [list(v) for v in data["vectors"]]
        return idx

    def __len__(self) -> int:
        return len(self.ids)


# --------------------------------------------------------------------------
# BM25(纯 Python,兼容中英文)
# --------------------------------------------------------------------------
class BM25:
    """经典 BM25 实现(词/字级分词,无外部依赖)。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_freqs: list[dict[str, int]] = []
        self.doc_len: list[int] = []
        self.idf: dict[str, float] = {}
        self.avgdl: float = 0.0

    def add(self, doc_id: str, tokens: list[str]) -> None:
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        self.doc_ids.append(doc_id)
        self.doc_freqs.append(freq)
        self.doc_len.append(len(tokens))

    def _compute_idf(self) -> None:
        n = len(self.doc_ids)
        df: dict[str, int] = {}
        for freq in self.doc_freqs:
            for t in freq:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.avgdl = (sum(self.doc_len) / n) if n else 0.0

    def search(self, query_tokens: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        if not self.doc_ids:
            return []
        if not self.idf:
            self._compute_idf()
        scored: list[tuple[str, float]] = []
        for i, freq in enumerate(self.doc_freqs):
            score = 0.0
            dl = self.doc_len[i]
            for t in query_tokens:
                if t not in freq:
                    continue
                idf = self.idf.get(t, 0.0)
                tf = freq[t]
                denom = tf + self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1.0)))
                score += idf * (tf * (self.k1 + 1)) / denom
            scored.append((self.doc_ids[i], float(score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# --------------------------------------------------------------------------
# 混合检索器
# --------------------------------------------------------------------------
class HybridRetriever:
    """稠密向量 + 稀疏 BM25 的混合检索:score = α·cosine + (1-α)·bm25。"""

    def __init__(self, index: VectorIndex, bm25: BM25, embedder: EmbeddingProvider,
                 alpha: float = 0.5):
        self.index = index
        self.bm25 = bm25
        self.embedder = embedder
        self.alpha = alpha

    @staticmethod
    def _normalize(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        mx = max(scores.values())
        if mx <= 0:
            return {k: 0.0 for k in scores}
        return {k: v / mx for k, v in scores.items()}

    def rank(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        q_vec = self.embedder.embed(query)
        q_tokens = tokenize(query)
        dense = dict(self.index.search(q_vec, top_k=max(top_k, len(self.index) or 1)))
        sparse = dict(self.bm25.search(q_tokens, top_k=max(top_k, len(self.bm25.doc_ids) or 1)))
        d_n = self._normalize(dense)
        s_n = self._normalize(sparse)
        ids = set(d_n) | set(s_n)
        hybrid = {i: self.alpha * d_n.get(i, 0.0) + (1 - self.alpha) * s_n.get(i, 0.0)
                  for i in ids}
        ranked = sorted(hybrid.items(), key=lambda x: x[1], reverse=True)
        return [(i, float(s)) for i, s in ranked[:top_k]]

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        return self.rank(query, top_k=top_k)
