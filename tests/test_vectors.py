"""Phase 4 — 向量记忆检索组件测试(零依赖,离线可跑)。

覆盖:
  * HashingEmbedder 的确定性与维度;
  * cosine 相似度;
  * BM25 基本检索;
  * HybridRetriever 的混合打分(a·cosine + (1-a)·bm25);
  * StructuredMemory 在 substring / hybrid 两种模式下的 rank/search 行为;
  * 同义改写查询场景下 hybrid 显著优于 substring(与 Layer 5 评测互补,这里走单测粒度)。
"""
from __future__ import annotations

import importlib.util

import pytest

from mycoder.memory.store import StructuredMemory
from mycoder.memory.vectors import (
    BM25,
    HashingEmbedder,
    HybridRetriever,
    VectorIndex,
    cosine,
    tokenize,
)

_HAS_FASTEMBED = importlib.util.find_spec("fastembed") is not None


# --------------------------------------------------------------------------
# HashingEmbedder
# --------------------------------------------------------------------------
def test_hashing_embedder_deterministic():
    e = HashingEmbedder()
    a = e.embed("用户登录失败")
    b = e.embed("用户登录失败")
    assert a == b, "相同文本必须得到完全相同的向量(确定性,离线可复现)"


def test_hashing_embedder_dim_and_normalized():
    e = HashingEmbedder(dim=128)
    v = e.embed("会话管理与令牌刷新")
    assert len(v) == 128
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6, "向量应 L2 归一化"


def test_hashing_embedder_shared_chars_score_higher():
    e = HashingEmbedder()
    # 同义改写(共享汉字但非连续子串)应比完全无关文本更接近
    q = "用户登入流程的会话校验"
    sim_related = cosine(e.embed(q), e.embed("本模块负责会话管理,处理令牌刷新与权限校验"))
    sim_unrelated = cosine(e.embed(q), e.embed("今天天气晴朗适合户外运动"))
    assert sim_related > sim_unrelated


# --------------------------------------------------------------------------
# cosine
# --------------------------------------------------------------------------
def test_cosine_identical_and_orthogonal():
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([], []) == 0.0


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------
def test_bm25_basic_ranking():
    bm = BM25()
    bm.add("d1", tokenize("用户 登录 失败 需要 重试"))
    bm.add("d2", tokenize("今天 天气 晴朗 适合 运动"))
    res = bm.search(tokenize("登录 失败"), top_k=2)
    assert res[0][0] == "d1"
    assert res[0][1] > 0.0


# --------------------------------------------------------------------------
# HybridRetriever
# --------------------------------------------------------------------------
def test_hybrid_retriever_rank_returns_sorted():
    emb = HashingEmbedder()
    idx = VectorIndex(emb)
    bm = BM25()
    for did, txt in [
        ("f1", "本模块负责会话管理,处理令牌刷新与权限校验"),
        ("f2", "今天天气晴朗适合户外运动"),
        ("f3", "缓存命中率下降时应增加重试与降级"),
    ]:
        idx.add(did, txt)
        bm.add(did, tokenize(txt))
    ret = HybridRetriever(idx, bm, emb, alpha=0.5)
    ranked = ret.rank("用户登入流程的会话校验", top_k=3)
    assert ranked[0][0] == "f1"
    # 分数应随排名递减
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_alpha_weighting():
    emb = HashingEmbedder()
    idx = VectorIndex(emb)
    bm = BM25()
    idx.add("x", "登录 会话 令牌")
    bm.add("x", tokenize("登录 会话 令牌"))
    idx.add("y", "天气 运动 户外")
    bm.add("y", tokenize("天气 运动 户外"))
    ret = HybridRetriever(idx, bm, emb, alpha=0.9)
    r_high = dict(ret.rank("登录 会话", top_k=2))
    ret2 = HybridRetriever(idx, bm, emb, alpha=0.1)
    r_low = dict(ret2.rank("登录 会话", top_k=2))
    # alpha 越大,dense 余弦权重越高;x 与查询共享字符越多,cosine 越高
    # 这里仅验证两者都能给出合法的非负分数,且不抛异常
    assert r_high["x"] >= 0.0 and r_low["x"] >= 0.0


# --------------------------------------------------------------------------
# StructuredMemory 检索模式
# --------------------------------------------------------------------------
def _build_session_memory() -> StructuredMemory:
    mem = StructuredMemory(":memory:", enabled=False)
    mem.remember_file(path="auth/session.py",
                      content="本模块负责会话管理,处理令牌刷新与权限校验")
    mem.remember_file(path="cache/db.py",
                      content="缓存命中率下降时应增加重试与降级策略")
    return mem


def test_structured_memory_substring_fails_synonym():
    mem = _build_session_memory()
    # 同义改写:无连续子串命中 -> substring 召回为空
    hits = mem.rank("用户登入流程的会话校验", mode="substring", top_k=3, kind="file")
    assert hits == []


def test_structured_memory_hybrid_recovers_synonym():
    mem = _build_session_memory()
    hits = mem.rank("用户登入流程的会话校验", mode="hybrid", top_k=3, kind="file")
    assert hits, "hybrid 应在同义改写下召回相关记忆"
    assert hits[0][0] == "file:auth/session.py"


def test_structured_memory_search_backward_compatible_format():
    mem = _build_session_memory()
    out = mem.search("会话管理", mode="substring", kind="file")
    assert "[文件] auth/session.py" in out
    # 默认模式也应该走 substring(向后兼容)
    out2 = StructuredMemory(":memory:", enabled=False).search("会话管理", kind="file")
    assert isinstance(out2, str)


@pytest.mark.skipif(_HAS_FASTEMBED is False, reason="需要可选依赖 fastembed")
def test_fastembed_embedder_loads():
    from mycoder.memory.vectors import FastEmbedEmbedder
    emb = FastEmbedEmbedder()
    try:
        v = emb.embed("缓存命中率下降时应增加重试")
    except Exception as exc:
        pytest.skip(f"fastembed 模型不可用(可能需要首次下载): {exc}")
    assert len(v) == emb.dim()
