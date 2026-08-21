"""企业知识库 SFT 数据生成器(从文档 -> 问答对)。

为什么需要它
------------
"企业知识库 LoRA" 的训练数据本质是大量 (问题, 检索资料, 答案) 三元组。
MyCoder 的轨迹本身不含检索上下文,因此这里单独提供"造数据"环节:

  1. 读取企业文档(md/txt/json),按段落/标题切块;
  2. 为每个块生成若干"基于该块"的问题与答案;
  3. 输出 MyCoder 可直接消费、再由 export_sft.py 清洗的格式
     (sft_samples.jsonl 同构:instruction=问题, output=答案, context=资料块)。

生成方式(两种,可切换)
----------------------
- offline(默认):用模板从每个块抽取"要点式"问答,**无需 GPU / 无需模型**,
  立刻能跑,适合冷启动积累首批数据。
- teacher:调用本地 OpenAI 兼容服务(与 MyCoder 的 local_openai 同构)让
  更强模型出题,质量更高。需要你先起一个推理服务(如 Ollama / vLLM)。

用法
----
  # 离线模板,处理 docs/ 下所有 .md/.txt,写出到 .mycoder/artifacts/_kb/sft_samples.jsonl
  python build_kb_dataset.py --docs ./kb_docs --out .mycoder/artifacts/_kb/sft_samples.jsonl

  # 用本地教师模型出题(需先起服务)
  python build_kb_dataset.py --docs ./kb_docs --mode teacher \
      --base-url http://127.0.0.1:8080/v1 --model qwen3.5:2b
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CHUNK_CHARS = 1200
OVERLAP_CHARS = 200


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += size - overlap
    return chunks


def read_docs(docs_dir: str) -> list[tuple[str, str]]:
    out = []
    p = Path(docs_dir)
    for ext in ("*.md", "*.txt", "*.json"):
        for f in sorted(p.rglob(ext)):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if f.suffix == ".json":
                try:
                    obj = json.loads(text)
                    text = json.dumps(obj, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            out.append((f.name, text))
    return out


# -------- 离线模板出题 ------------------------------------------------------
def offline_qa(chunk: str, source: str) -> list[dict]:
    """从块状文本抽取要点,构造(问题,答案,资料)。简单但 zero-cost。"""
    # 以句号/换行切句,取信息密度高的句子作为答案候选
    sentences = [s.strip() for s in re.split(r"[。\n！？!?]", chunk) if len(s.strip()) >= 12]
    samples = []
    for s in sentences[:4]:
        ans = s
        # 把答案句改写成"是什么/如何"类问题
        if "：" in ans or ":" in ans:
            parts = re.split(r"[:：]", ans, maxsplit=1)
            head = parts[0] if parts else ans
            q = f"关于「{head.strip()}」,制度/资料中是如何规定的?"
        else:
            q = f"请根据资料说明:{ans[:30]}… 这指的是什么?"
        samples.append({
            "instruction": q,
            "output": ans,
            "context": chunk,
            "source": source,
        })
    return samples


# -------- 教师模型出题(本地 OpenAI 兼容) -----------------------------------
def teacher_qa(chunk: str, source: str, base_url: str, model: str) -> list[dict]:
    import urllib.request
    prompt = (
        "你是企业知识库的数据标注员。下面是一段企业资料,请基于它生成 "
        "2~3 个真实员工可能问的问题及准确答案。只输出 JSON 数组,每个元素含 "
        "question / answer 字段,不要编造资料外的内容。\n\n资料:\n" + chunk
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except Exception as e:  # 失败则回退离线
        print(f"  [warn] teacher 调用失败({e}),回退离线出题")
        return offline_qa(chunk, source)
    # 解析模型返回的 JSON(容错:截取首个 [ .. ] )
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    return [{"instruction": a.get("question", ""), "output": a.get("answer", ""),
             "context": chunk, "source": source} for a in arr
            if a.get("question") and a.get("answer")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", required=True, help="企业文档目录(md/txt/json)")
    ap.add_argument("--out", required=True, help="输出 sft_samples.jsonl 路径")
    ap.add_argument("--mode", choices=["offline", "teacher"], default="offline")
    ap.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    ap.add_argument("--model", default="qwen3.5:2b")
    args = ap.parse_args()

    docs = read_docs(args.docs)
    if not docs:
        print(f"[ERROR] 在 {args.docs} 未找到任何 md/txt/json 文档")
        return
    print(f"[INFO] 读取文档 {len(docs)} 份")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for name, text in docs:
            for chunk in chunk_text(text):
                if args.mode == "teacher":
                    samples = teacher_qa(chunk, name, args.base_url, args.model)
                else:
                    samples = offline_qa(chunk, name)
                for s in samples:
                    rec = {"task_id": f"kb:{name}", "status": "completed",
                           "instruction": s["instruction"], "output": s["output"],
                           "context": s["context"]}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    total += 1
    print(f"[DONE] 生成 {total} 条 KB SFT 样本 -> {out_path}")
    print("下一步: python kb_lora/export_sft.py --mode kb --artifacts-root "
          "<含该文件的工件根目录>")


if __name__ == "__main__":
    main()
