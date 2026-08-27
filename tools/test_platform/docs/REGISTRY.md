# registry 資料模型

```
產品 product（products.json）── label／色／環境警示／knowledge 掃描設定，不含執行能力
  └─ 工具 tool（<id>.tool.json）── 能力宣告：怎麼跑、參數長什麼樣、狀態怎麼讀、報告在哪、怎麼停
       ├─ 命令 commands[] ── mode ∈ run｜sync｜python_call｜http；各自有 argv 固定前綴 ＋ params.fields
       └─ 設定檔 profiles/<tool_id>/<id>.json ── 一組具名參數值；secret 永不寫入
```

## 頂層欄位
`id product|products name subtitle kind(cli|pytest|http) owner tags order docs enabled`
`danger.{level,confirm_text,require_typed_confirm}`
`runtime.{cwd,env,requires.python_modules}`（統一 .venv，無 interpreter）
`commands[].{id,label,mode,argv|call,timeout_sec,result.kind,danger,params,primary}`
`run.{concurrency,max_parallel,exclusive_group,run_id_env,status_source,phases[],metrics[]}`
`stop.{strategy(flag|tree|http),flag_file,grace_seconds,warning}`
`artifacts.{run_dir,console,whitelist,allow_subtree,primary[],allure}`
（`narration` 已於 2026-08-24 移除 —— 播報 ticker 拆掉了，模板沒有人讀）
`cases.{roots,watch_globs,cache,product_map,stages,prerequisite_rules,group_by,title_priority}`（僅 pytest）

## 欄位描述子
`type`：text number boolean select multiselect textarea secret duration file_select number_list case_picker path_picker
`emit`：opt(--arg v) opt_eq flag_when_true flag_when_false repeat join json env positional argsfile none
條件：`visible_when`（隱藏）／`available_when`（停用＋顯示 `unavailable_reason`）／`required_when`
其他：`default min max step unit required help placeholder pattern rows options options_from{kind:api,url} reload_on_change never_persist`

`result.kind`（sync）：text｜json_table｜checklist｜copy_chip｜artifact_dir

驗證：`python -m core.registry --validate`（結構檢查；secret 必須 emit=env、pytest 必須有 cases 等）。
