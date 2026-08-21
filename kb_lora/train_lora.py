"""企业知识库 LoRA 微调脚本(面向 RTX 4060 / 8GB)。

基座模型
--------
用户本地标签为 Ollama 格式 "qwen3.5:2b"(模型名:标签)。注意区分两种 id:
- Ollama 服务标签(推理用):  qwen3.5:2b   -> MyCoder 的 local_openai.model 填这个
- HuggingFace 仓库 id(训练用): Qwen/Qwen3.5-2B-Instruct -> from_pretrained 填这个
两者指向同一份权重,只是调用入口不同。脚本已把训练用 id 做成 --model-id 参数,
默认值见下;若你的 HF 仓库名不同,直接 --model-id 覆盖即可。

4060(8GB)关键约束与对策
-----------------------
- 2B 模型 bf16 约 4GB,4-bit 量化后约 1.6GB;LoRA 适配器仅几十 MB。
- 采用 QLoRA(4-bit NF4 + 双量化),显存占用 < 6GB,留有余量。
- 关闭模型本身 bf16 权重(用 4-bit),但计算用 bf16;梯度检查点省显存。
- 批大小保守(per_device=2 + grad Accumulation=8),序列长度 2048。
- 若仍 OOM,把 MAX_SEQ_LEN 降到 1536 或 per_device_batch_size 降到 1。

训练数据
--------
由 kb_lora/export_sft.py 产出:
  - kb_lora/data/sft_chatml.jsonl  (推荐, ChatML 多轮格式)
  - kb_lora/data/sft_alpaca.jsonl
也可直接用自己的 (instruction, input, output) / messages 数据。

运行(请在自备 torch 环境执行,不要装进 MyCoder 的零依赖 venv)
-----------------------------------------------------------
  pip install -r kb_lora/requirements.txt
  python kb_lora/train_lora.py \
      --data kb_lora/data/sft_chatml.jsonl \
      --output kb_lora/output/qwen3-2b-kb-lora

产出:LoRA 适配器(adapter_*.safetensors + 配置)。训练完用 merge 或
PEFT 加载,再通过 MyCoder 的 local_openai 后端(localhost)接入验证。
"""
from __future__ import annotations

import argparse

import torch
from datasets import Dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTTrainer

# ---- 可改参数 -------------------------------------------------------------
# 训练用 HF 仓库 id(默认指向 Qwen3.5-2B 指令版;若你的仓库名不同请用
# --model-id 覆盖,或直接传本地权重目录路径)。Ollama 标签 qwen3.5:2b 仅用于推理。
MODEL_ID = "Qwen/Qwen3.5-2B-Instruct"
MAX_SEQ_LEN = 2048
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
# Qwen3 全线性层都挂 LoRA,收益更稳;若想更省可只留 q_proj,v_proj
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]
# --------------------------------------------------------------------------


def build_dataset(path: str, tokenizer):
    """读取 jsonl,支持两种格式:
    - ChatML: {"messages":[{"role","content"}, ...]}
    - Alpaca: {"instruction","input","output"}
    """
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = __import__("json").loads(line)
            if "messages" in obj:
                text = tokenizer.apply_chat_template(
                    obj["messages"], tokenize=False, add_generation_prompt=False)
            else:
                instr = obj.get("instruction", "")
                inp = obj.get("input", "")
                out = obj.get("output", "")
                user = instr + (("\n\n" + inp) if inp else "")
                text = tokenizer.apply_chat_template(
                    [{"role": "user", "content": user},
                     {"role": "assistant", "content": out}],
                    tokenize=False, add_generation_prompt=False)
            rows.append({"text": text})
    return Dataset.from_list(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="sft jsonl 路径")
    ap.add_argument("--output", default="kb_lora/output/qwen3-2b-kb-lora")
    ap.add_argument("--model-id", default=MODEL_ID,
                    help="HuggingFace 仓库 id 或本地权重目录(训练用,非 Ollama 标签)")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    args = ap.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model_id, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=bnb,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    lora = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=TARGET_MODULES,
        bias="none",
        task_type="CAUSAL_LM",
    )

    ds = build_dataset(args.data, tokenizer)
    print(f"[INFO] 训练样本数: {len(ds)}")

    training_args = TrainingArguments(
        output_dir=args.output,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        bf16=True,
        fp16=False,
        logging_steps=5,
        save_strategy="epoch",
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_grad_norm=0.3,
        report_to="none",
        seed=42,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=ds,
        processing_class=tokenizer,
        peft_config=lora,
        max_seq_length=MAX_SEQ_LEN,
    )
    trainer.train()
    trainer.save_model(args.output)
    print(f"[DONE] LoRA 适配器已保存至: {args.output}")
    print(f"[NEXT] 把适配器合并/挂载到 Ollama 的 qwen3.5:2b 后,在 "
          f"config/default.yaml 设 model.local_openai.model: \"qwen3.5:2b\" 即可接回 MyCoder。")


if __name__ == "__main__":
    main()
