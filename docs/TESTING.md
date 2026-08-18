# MyCoder 娴嬭瘯鏂规硶

## 娴嬭瘯鏋舵瀯

MyCoder 閲囩敤**浜斿眰璇勬祴浣撶郴** + **鎬ц兘娴嬭瘯濂椾欢**,鍒绘剰鍖哄垎"妯″瀷鑳藉姏"涓?绯荤粺鑳藉姏":

```
Layer 1: Harness 鍥炲綊娴嬭瘯
  鈹斺攢 楠岃瘉杩愯鏃剁ǔ瀹氭€?鑳藉畬鎴愩€佸伐浠堕綈鍏ㄣ€佹柇瑷€婊¤冻)

Layer 2: 涓婁笅鏂囨不鐞嗚瘎娴?  鈹斺攢 楠岃瘉棰勭畻瑁佸壀鏀剁泭(娌荤悊 vs 涓嶆不鐞嗙殑 prompt 闀垮害宸?

Layer 3: 璁板繂鏀剁泭璇勬祴
  鈹斺攢 楠岃瘉 follow-up 闃舵閲嶅璇绘枃浠跺綊闆躲€佹纭巼

Layer 4: 鎭㈠姝ｇ‘鎬ц瘎娴?  鈹斺攢 楠岃瘉 checkpoint/resume + 宸ヤ綔鍖烘紓绉昏瘑鍒竟鐣?
Layer 5: 妫€绱㈠彫鍥炶瘎娴?  鈹斺攢 楠岃瘉鍚屼箟鏀瑰啓鏌ヨ涓?substring / vector / hybrid 鐨?recall@1/3/5

鎬ц兘娴嬭瘯:
  鈹斺攢 浣跨敤宸ㄥ瀷鏂囦欢(~4669琛?瀵?8 涓淮搴﹁繘琛屽帇鍔涙祴璇?```

## 娴嬭瘯鏁版嵁

### Benchmark 浠诲姟 (benchmarks/tasks.json)
12 涓浐瀹氫换鍔?鎸夎瘎娴嬪眰鎵撴爣绛?
- **Regression (4)**: t01_create_file, t02_read_file, t03_edit_file, t04_list_grep
- **Context (3)**: t05_long_refactor, t06_long_search, t07_long_multifile
- **Memory (4)**: t08_build_utils, t09_followup_use_utils, t10_build_config, t11_followup_use_config
- **Resume (1)**: t12_resume_scenario

姣忎釜浠诲姟鍖呭惈:
- `task_id`: 鍞竴鏍囪瘑
- `layer`: 鎵€灞炶瘎娴嬪眰
- `goal`: 浠诲姟鐩爣
- `script`: MockBackend 鑴氭湰(纭畾鎬ц建杩?
- `expect`: 鏂█(files_created, file_contains, final_contains)
- `setup_files`: 棰勭疆鏂囦欢
- `generate_files`: 鐢熸垚澶ф枃浠?鐢ㄤ簬 context 灞?
- `follow_up_of`: 鐖朵换鍔?ID(鐢ㄤ簬 memory 灞?
- `control_script`: 瀵圭収缁勮剼鏈?鐢ㄤ簬 memory 灞?

### 宸ㄥ瀷娴嬭瘯鏂囦欢 (examples/giant_test.py)
鐢ㄤ簬鎬ц兘娴嬭瘯鍜屼笂涓嬫枃娌荤悊婕旂ず鐨勮嚜鍔ㄧ敓鎴愭枃浠?
- **琛屾暟**: ~4669 琛?- **鍐呭**: 100 涓嚱鏁?+ 鎺掑簭绠楁硶(8绫? + 璁捐妯″紡(10绫? + 鏁版嵁缁撴瀯(6绫? + 8 涓€氱敤瀹瑰櫒绫?- **鐢熸垚鏂瑰紡**: `python generate_test_file.py`

## 杩愯娴嬭瘯

### 浣跨敤 ML2 鐜(鎺ㄨ崘)

```bash
# 婵€娲?ML2 鐜(宸查瑁?pytest)
# 使用你的 Python 环境(需 pip install -e . 及 pytest)

# 杩愯瀹屾暣娴嬭瘯濂椾欢(162 椤?
python -m pytest tests/ -v

# 杩愯鐗瑰畾娴嬭瘯鏂囦欢
python -m pytest tests/test_models.py -v

# 杩愯鐗瑰畾娴嬭瘯绫?python -m pytest tests/test_eval.py::TestEvalLayers -v

# 杩愯鐗瑰畾娴嬭瘯鏂规硶
python -m pytest tests/test_eval.py::TestEvalLayers::test_regression_layer -v

# 杩愯鎬ц兘娴嬭瘯
python -m pytest tests/test_performance.py -v
```

## 鍥涘眰璇勬祴璇﹁В

### Layer 1: Harness 鍥炲綊娴嬭瘯

**鐩爣**: 楠岃瘉杩愯鏃剁ǔ瀹氭€?
**娴嬭瘯鍐呭**:
- 浠诲姟鑳藉畬鎴?status == "completed")
- 涓夌被宸ヤ欢榻愬叏(trajectory.jsonl, metrics.json, report.md)
- 鏂█婊¤冻(files_created, file_contains, final_contains)

**娴嬭瘯鐢ㄤ緥**:
- `test_completes`: 浠诲姟瀹屾垚
- `test_produces_three_artifacts`: 宸ヤ欢榻愬叏
- `test_metrics_recorded`: 鎸囨爣璁板綍
- `test_max_steps`: 鏈€澶ф鏁扮粓姝?- `test_unknown_tool_intercepted`: 鏈煡宸ュ叿鎷︽埅
- `test_invalid_params_intercepted`: 闈炴硶鍙傛暟鎷︽埅

**楠岃瘉鏂规硶**:
```bash
python -m pytest tests/test_harness.py::TestRunFlow -v
```

### Layer 2: 涓婁笅鏂囨不鐞嗚瘎娴?
**鐩爣**: 楠岃瘉棰勭畻瑁佸壀鏀剁泭

**娴嬭瘯鍐呭**:
- 娌荤悊鍚?prompt 闀垮害 < 涓嶆不鐞?prompt 闀垮害
- 骞冲潎鍘嬬缉鐜?> 0
- 棰勭畻鍐呭畬鎴愮巼 == 100%

**娴嬭瘯鐢ㄤ緥**:
- `test_fold_old_turns`: 鎶樺彔鏃ц疆娆?- `test_hard_limit_enforced`: 纭檺棰濆己鍒?- `test_ratio_magnitude`: 鍘嬬缉鐜囧箙搴?- `test_does_not_mutate_history`: 涓嶆薄鏌撳師濮嬪巻鍙?- `test_deterministic_replay`: 纭畾鎬ч噸鏀?
**楠岃瘉鏂规硶**:
```bash
python -m pytest tests/test_context.py -v
```

**璇勬祴鎸囨爣**:
- 骞冲潎鍘嬬缉鐜? ~80%
- 鏈€楂樺帇缂╃巼: ~81%
- 棰勭畻鍐呭畬鎴愮巼: 100%

### Layer 3: 璁板繂鏀剁泭璇勬祴

**鐩爣**: 楠岃瘉 follow-up 闃舵閲嶅璇绘枃浠跺綊闆?
**娴嬭瘯鍐呭**:
- 鐖朵换鍔″垱寤烘枃浠?娌夋穩鎽樿
- follow-up 浠诲姟浣跨敤 memory_query(涓嶉噸璇绘枃浠?
- 瀵圭収缁勪娇鐢?file_read(閲嶈鏂囦欢)
- 姣旇緝: 閲嶈娆℃暟銆佹纭巼

**娴嬭瘯鐢ㄤ緥**:
- `test_remember_file_symbols`: 鏂囦欢鎽樿鎻愬彇
- `test_same_hash_skip`: 鍐呭鍝堝笇涓€鑷磋烦杩?- `test_followup_injects_memory`: follow-up 娉ㄥ叆璁板繂
- `test_includes_parent_files`: 鍖呭惈鐖朵换鍔℃枃浠?
**楠岃瘉鏂规硶**:
```bash
python -m pytest tests/test_memory.py -v
```

**璇勬祴鎸囨爣**:
- follow-up 閲嶅璇绘枃浠? 2 鈫?0 娆?- 浠诲姟姝ｇ‘鐜? 100%

### Layer 4: 鎭㈠姝ｇ‘鎬ц瘎娴?
**鐩爣**: 楠岃瘉 checkpoint/resume + 宸ヤ綔鍖烘紓绉昏瘑鍒?
**娴嬭瘯鍐呭**:
- 涓柇浠诲姟(stop_after_steps)
- 鍙€?澶栭儴淇敼宸ヤ綔鍖?妯℃嫙婕傜Щ)
- 鎭㈠浠诲姟(resume)
- 楠岃瘉: 婕傜Щ妫€娴嬨€佺画璺戝畬鎴愩€佹枃浠跺瓨鍦?
**娴嬭瘯鐢ㄤ緥**:
- `test_interrupt_resume_continues`: 涓柇鎭㈠缁窇
- `test_resume_detects_drift`: 鎭㈠妫€娴嬫紓绉?- `test_resume_missing_checkpoint`: 缂哄け鏂偣

**楠岃瘉鏂规硶**:
```bash
python -m pytest tests/test_harness.py::TestResumeFlow -v
```

**璇勬祴鎸囨爣**:
- 婕傜Щ璇嗗埆鍑嗙‘鐜? 100%(5/5 婕傜Щ妫€鍑? 5/5 鏃犳紓绉绘纭?
- 鎭㈠鍚庡畬鎴愮巼: 100%

## 鎬ц兘娴嬭瘯 (Layer 5)

### 姒傝堪

`tests/test_performance.py` 浣跨敤 `examples/giant_test.py` (~4669 琛? 瀵?MyCoder 鍚勭粍浠惰繘琛屽帇鍔涙祴璇曘€傛瘡椤规祴璇曡繘琛?3 杞彇骞冲潎,杈撳嚭 avg/min/max 鑰楁椂銆?
### 宸ㄥ瀷娴嬭瘯鏂囦欢

`examples/giant_test.py` 鐢?`generate_test_file.py` 鑷姩鐢熸垚,鍖呭惈:
- **100 涓嚱鏁?*: func_0001 鍒?func_0100,姣忎釜鎵ц妯′箻璁＄畻
- **鎺掑簭绠楁硶 (8 绉?**: bubble/quick/merge/heap/insertion/selection/counting/radix sort
- **璁捐妯″紡 (10 绉?**: Singleton/Factory/Builder/Observer/Strategy/Decorator/Adapter/Proxy/Command/StateMachine/Chain of Responsibility
- **鏁版嵁缁撴瀯 (6 绉?**: ListNode/LinkedList/TreeNode/BinaryTree/TrieNode/Trie/Graph (鍚?BFS/DFS/Dijkstra/鐜娴?
- **8 涓€氱敤瀹瑰櫒绫?*: 甯︽暟鎹瓨鍌?鍘嗗彶璁板綍/缁熻/__repr__

```bash
# 鐢熸垚宸ㄥ瀷娴嬭瘯鏂囦欢
python generate_test_file.py

# 鐢熸垚鍚庣害 4669 琛? ~200KB
```

### 鎬ц兘娴嬭瘯妯″潡璇﹁В

| 娴嬭瘯妯″潡 | 娴嬭瘯鍑芥暟 | 璇存槑 | 娴嬮噺鎸囨爣 |
|----------|----------|------|----------|
| [1] 鏂囦欢璇诲彇 | `test_file_read_performance()` | 璇诲彇瀹屾暣宸ㄥ瀷鏂囦欢銆侀儴鍒嗚鍙?100琛?銆?0娆￠噸澶嶈鍙?50琛? | 澶ф枃浠?I/O 鍚炲悙 |
| [2] 鏂囦欢鍒楄〃 | `test_file_list_performance()` | 鍒楀嚭 examples 鐩綍銆佸垪鍑洪」鐩牴鐩綍 | 鐩綍閬嶅巻鏁堢巼 |
| [3] Grep 鎼滅储 | `test_grep_performance()` | 鎼滅储 class 瀹氫箟銆乫unc_ 鍑芥暟銆佹帓搴忕畻娉曘€佽璁℃ā寮忋€佹暟鎹粨鏋?| 姝ｅ垯鍖归厤 + 澶ф枃浠舵悳绱?|
| [4] 璁板繂瀛樺偍 | `test_memory_performance()` | 瀛樺偍宸ㄥ瀷鏂囦欢璁板綍銆佹悳绱?func/class/sort 鍏抽敭璇?| 鎽樿鐢熸垚 + 妫€绱㈤€熷害 |
| [5] 涓婁笅鏂囩鐞?| `test_context_performance()` | 宸ㄥ瀷鍐呭 token 浼扮畻銆? 涓ぇ娑堟伅浼扮畻銆佸ぇ涓婁笅鏂囩粍瑁?| token 浼扮畻 + 瑁佸壀鏁堢巼 |
| [6] 鏂偣 I/O | `test_checkpoint_performance()` | 淇濆瓨澶у瀷鐘舵€?鍚?10000 瀛楃娑堟伅)銆佸姞杞藉ぇ鍨嬫柇鐐?| JSON 搴忓垪鍖?鍙嶅簭鍒楀寲 |
| [7] 宸ヤ綔鍖烘搷浣?| `test_workspace_operations()` | 鍐欏叆澶ф枃浠躲€佽鍙栧ぇ鏂囦欢銆?00 涓皬鏂囦欢鍐欏叆銆佸垪鍑?100+ 鏂囦欢 | 娌欑鏂囦欢鎿嶄綔鏁堢巼 |
| [8] 宸ュ叿娉ㄥ唽 | `test_tool_registry_performance()` | 100 娆℃瀯寤?registry銆佽幏鍙栧叏閮?7 涓伐鍏枫€佽幏鍙栧伐鍏?schema | 娉ㄥ唽琛ㄦ瀯寤?+ 鏌ヨ |

### 杩愯鎬ц兘娴嬭瘯

```bash
# 杩愯鎬ц兘娴嬭瘯(闇€瑕佸厛鐢熸垚 giant_test.py)
python -m pytest tests/test_performance.py -v -s

# 杩愯鎬ц兘娴嬭瘯(涓嶆樉绀?print 杈撳嚭)
python -m pytest tests/test_performance.py -v
```

### 鎬ц兘娴嬭瘯棰勬湡杈撳嚭

```
[1] File Read Performance
  [read_giant_file] avg=0.0xxx s
  [read_partial_file] avg=0.0xxx s
  [10x_partial_reads] avg=0.0xxx s

[2] File List Performance
  [list_examples_dir] avg=0.0xxx s
  [list_project_root] avg=0.0xxx s

[3] Grep Search Performance
  [grep_class_def] avg=0.0xxx s
  [grep_func_def] avg=0.0xxx s
  [grep_sort_algo] avg=0.0xxx s
  [grep_design_pattern] avg=0.0xxx s
  [grep_data_structure] avg=0.0xxx s

[4] Memory Store Performance
  [store_giant_file_record] avg=0.0xxx s
  [memory_search_func] avg=0.0xxx s
  [memory_search_sort] avg=0.0xxx s

[5] Context Management Performance
  [estimate_giant_tokens] avg=0.0xxx s
  [estimate_5x_large_messages] avg=0.0xxx s
  [assemble_large_context] avg=0.0xxx s

[6] Checkpoint Performance
  [save_large_checkpoint] avg=0.0xxx s
  [load_large_checkpoint] avg=0.0xxx s

[7] Workspace Operations Performance
  [write_large_file] avg=0.0xxx s
  [read_large_file] avg=0.0xxx s
  [write_100_small_files] avg=0.0xxx s
  [list_100_plus_files] avg=0.0xxx s

[8] Tool Registry Performance
  [build_registry_100x] avg=0.0xxx s
  [get_all_7_tools] avg=0.0xxx s
  [get_all_tool_schemas] avg=0.0xxx s

============================================================
PERFORMANCE SUMMARY
============================================================
Test                                Avg(s)     Min(s)     Max(s)
-----------------------------------------------------------------
...
Total tests: 24
Total time: x.xx s
============================================================
```

## 瀹夊叏杈圭晫娴嬭瘯

### 鍙傛暟鏍￠獙
```bash
python -m pytest tests/test_safety.py::TestParamValidation -v
```

### 宸ヤ綔鍖洪殧绂?```bash
python -m pytest tests/test_sandbox.py::TestResolve -v
```

### HITL 瀹℃壒
```bash
python -m pytest tests/test_safety.py::TestHitl -v
```

### 鍘婚噸鎷︽埅
```bash
python -m pytest tests/test_safety.py::TestDedup -v
```

### 鏁忔劅淇℃伅鑴辨晱
```bash
python -m pytest tests/test_safety.py::TestRedact -v
```

## 涓婁笅鏂囨不鐞嗘紨绀?
`examples/context_demo.py` 浣跨敤 `giant_test.py` 妯℃嫙 15 杞笂涓嬫枃鑶ㄨ儉:

```bash
# 杩愯涓婁笅鏂囨不鐞嗘紨绀?python examples/context_demo.py
```

**棰勬湡杈撳嚭**:
```
Giant file: 4669 lines, ~200000 chars, ~50000 tokens

Simulating 15 turns (each reads ~300 lines of giant file)

  Turn  1 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: []
  Turn  3 | Raw:  xxxx tokens -> After:  xxxx tokens | Ratio:  xx%
  Turn  6 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns']
  Turn  9 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns', 'drop_stale_turns']
  Turn 12 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns', 'drop_stale_turns', 'truncate_long_content']
  Turn 15 | Raw:  xxxx tokens -> After:  xxxx tokens | Ratio: ~80%

Final Summary
  Total turns:        15
  Without governance:  ~xxxxx tokens (exceeds hard limit by xx)
  With governance:     ~xxxx tokens (within budget!)
  Compression ratio:   ~80%
  Strategies used:     ['fold_old_turns', 'drop_stale_turns', 'truncate_long_content']
```

## 璇勬祴鎶ュ憡

杩愯瀹屾暣璇勬祴鍚?鐢熸垚鎶ュ憡:

```bash
python -m mycoder eval --suite all --output .mycoder/eval
# 鍗曠嫭杩愯鏌愪竴灞?regression | context | memory | resume | retrieval
python -m mycoder eval --suite retrieval
```

鎶ュ憡鏂囦欢:
- `.mycoder/eval/report.json`: 缁撴瀯鍖栨姤鍛?JSON)
- `.mycoder/eval/report.md`: 浜虹被鍙鎶ュ憡(Markdown)

## 娴嬭瘯瑕嗙洊鐜?
### 妯″潡瑕嗙洊
- 鉁?models: MockBackend, LocalOpenAIBackend(閲嶈瘯/閫€閬?娴佸紡/usage), 宸ュ巶瑁呴厤
- 鉁?tools: 7 绫诲伐鍏峰姛鑳芥祴璇?- 鉁?sandbox: 璺緞闅旂銆佹寚绾瑰揩鐓?- 鉁?safety: 鍙傛暟鏍￠獙銆侀殧绂汇€丠ITL銆佸幓閲嶃€佽劚鏁?- 鉁?context: token 浼扮畻銆佹姌鍙犮€佺‖闄愰銆佹嫹璐濆畨鍏ㄣ€佹憳瑕佸櫒鍒囨崲
- 鉁?memory: 涓夊眰瀛樺偍銆佸幓閲嶃€佹绱?substring/vector/hybrid)銆佹寔涔呭寲
- 鉁?vectors: HashingEmbedder/BM25/HybridRetriever 妫€绱笌鎵撳垎
- 鉁?checkpoint: 鏂偣淇濆瓨/鍔犺浇銆佹紓绉昏瘑鍒?- 鉁?harness: 涓诲惊鐜€佸畨鍏ㄦ嫤鎴€佸幓閲嶃€佽蹇嗐€佹仮澶?- 鉁?observability: Tracer/trace.json銆乷n_event 鍩嬬偣銆丣SON 缁撴瀯鍖栨棩蹇?- 鉁?api: FastAPI + SSE 浜嬩欢娴併€丒ventBus銆佸疄鏃惰拷韪〉
- 鉁?orchestrator: 骞惰缂栨帓銆佸け璐ラ檷绾с€佷簨浠跺彂灏?- 鉁?cost: 鎸変环鐩〃鏍哥畻杩愯鎴愭湰
- 鉁?eval: 浜斿眰璇勬祴銆乥enchmark 鏁版嵁瀹屾暣鎬?- 鉁?performance: 8 缁村害鎬ц兘鍘嬪姏娴嬭瘯

### 娴嬭瘯鐢ㄤ緥缁熻

| 娴嬭瘯鏂囦欢 | 鐢ㄤ緥鏁?| 娴嬭瘯鍐呭 |
|----------|--------|----------|
| test_models.py | 14 | Mock 鑴氭湰 progression/state鎭㈠, LocalOpenAI parse, 宸ュ叿schema鏍煎紡 |
| test_tools.py | 21 | 姣忕宸ュ叿鐨?execute + error case + meta 瀛楁 |
| test_sandbox.py | 15 | PathEscapeError 鎷︽埅, rel鍏煎, snapshot 鎸囩汗, list杩囨护闅愯棌 |
| test_safety.py | 27 | validate_params(11缁勫悎)/escape(4鍦烘櫙)/shell(4鍦烘櫙)/HITL(3绛栫暐)/dedup(3)/redact(5) |
| test_context.py | 19 | CJK/ASCII token浼拌, fold/fold_to_1/enforce_budget, 娣辨嫹璐濆畨鍏? deterministic replay, 鎽樿鍣?|
| test_memory.py | 19 | remember_task/update/parent_link, file_symbols/same_hash_skip, relation/link, search(3kind), followup_context, save_load_roundtrip, stats, disabled_no_save |
| test_checkpoint.py | 15 | save_load_unicode/overwrite, exists/list_all, drift_compare(modified/added/deleted/empty), summary_text |
| test_harness.py | 15 | run_flow(complete/artifacts/metrics/max_steps/unknown_tool/invalid_params), safety_intercept, dedup, resume_flow |
| test_backend.py | 9 | 閲嶈瘯/鎸囨暟閫€閬?429/5xx/Retry-After, usage 瑙ｆ瀽, 娴佸紡 complete_stream |
| test_cost.py | 5 | 鎸変环鐩〃鏍哥畻 token 鎴愭湰, 缂轰环鐩笉璁¤垂 |
| test_eval.py | 14 | benchmark_data, eval_layers(鍥炲綊/涓婁笅鏂?璁板繂/鎭㈠/妫€绱?, report_writing |
| test_observability.py | 7 | Tracer span 灞傜骇/鑰楁椂, on_event 閲嶅缓, JSON 鏃ュ織鍙В鏋? trace.json 瀵煎嚭 |
| test_vectors.py | 11 | HashingEmbedder 纭畾鎬?褰掍竴鍖? 浣欏鸡, BM25 鎺掑簭, HybridRetriever 伪 鍔犳潈, FastEmbed 鍙€?|
| test_api.py | 3 | health/杩借釜椤? 鎻愪氦鈫扴SE鈫掑畬鎴愪簨浠? 鏈煡浠诲姟 404 |
| test_orchestrator.py | 4 | 骞惰缂栨帓, 澶辫触闄嶇骇(partial), 榛樿 planner 鍗曞瓙浠诲姟, 浜嬩欢鍙戝皠 |
| test_performance.py | 8 | 鏂囦欢璇诲彇/鍒楄〃/Grep/璁板繂/涓婁笅鏂?鏂偣/宸ヤ綔鍖?宸ュ叿娉ㄥ唽 鎬ц兘娴嬭瘯 |

**鎬昏**: 206 涓祴璇曠敤渚?16 涓祴璇曟枃浠?

## 纭畾鎬т繚璇?
鎵€鏈夋祴璇曚娇鐢?
- **MockBackend**: 鑴氭湰鍖栧搷搴?鍚屼竴杈撳叆蹇呭緱鍚屼竴杈撳嚭
- **涓存椂宸ヤ綔鍖?*: pytest tmp_path fixture,浜掍笉姹℃煋
- **鍥哄畾閰嶇疆**: Config() 榛樿閰嶇疆,鏃犻殢鏈烘€?
淇濊瘉:
- 鍚屼竴鐜銆佸悓涓€浠ｇ爜,娴嬭瘯缁撴灉 100% 鍙鐜?- 涓嶅悓鐜(Windows/Linux/macOS),娴嬭瘯缁撴灉涓€鑷?
## 鏁呴殰鎺掓煡

### pytest 鎵句笉鍒版祴璇?```bash
# 纭繚鍦?mycoder 椤圭洰鏍圭洰褰?cd "D:\DeepSeek Harness\mycoder"

# 纭繚浣跨敤 ML2 鐜
python -m pytest tests/ --collect-only
```

### 瀵煎叆閿欒
```bash
# 纭繚 conftest.py 瀛樺湪
ls tests/conftest.py

# 纭繚椤圭洰鏍圭洰褰曞湪 sys.path
python -c "import sys; sys.path.insert(0, '.'); import mycoder"
```

### 鎬ц兘娴嬭瘯澶辫触
```bash
# 纭繚 giant_test.py 宸茬敓鎴?python generate_test_file.py

# 鏌ョ湅璇︾粏杈撳嚭
python -m pytest tests/test_performance.py -v -s
```

### 璇勬祴澶辫触
```bash
# 鏌ョ湅璇︾粏杈撳嚭
python -m pytest tests/test_eval.py -v -s

# 鏌ョ湅璇勬祴鎶ュ憡
cat .mycoder/eval/report.md
```

## 鎸佺画闆嗘垚

寤鸿閰嶇疆 CI(濡?GitHub Actions):

```yaml
name: Test MyCoder
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest
      - name: Generate test file
        run: python generate_test_file.py
      - name: Run tests
        run: pytest tests/ -v
      - name: Run eval
        run: python -m mycoder eval --suite all
