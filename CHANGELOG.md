# CHANGELOG

本文件记录本项目实际发生的变更。只写真实做过的事，不补历史。

## [0.1.0] — 2026-10-02

首个可用版本：目录与冲突检测 + 兼容性判定矩阵 + 调优建议 + 排查 FAQ + 方案装配。

### 新增 · 数据层
- `data/sources.md` —— 9 个来源登记（S1–S9），每条含类型、名称、URL、覆盖内容；
  定义 `official` / `secondary` / `unverified` 三级可信度
- `data/chips/cpu_specs.csv` —— 20 行，覆盖 C86-4G 三个系列（7400 / 5400 / 3400）14 个型号
- `data/chips/dcu_specs.csv` —— 6 行，Z100 / Z100L / K100 / K100-AI / BW100 五个型号
- `data/chips/swstack.csv` —— 9 行，DTK 版本与内核对应关系、框架适配版本
- `data/models/model_matrix.csv` —— 10 个模型的参数、权重、最小显存要求
- `data/scenarios/` —— 2 个业务场景：政务大厅推理 / 金融私有化微调
- `data/assumptions.md` —— A-01~A-05 假设登记 + B 节「明确不做的事」

### 新增 · 计算层
- `src/catalog.py` —— 目录加载、可信度校验、同字段多来源冲突检测
- `src/compat_matrix.py` —— 四档判定（supported / needs_tuning / not_recommended / unknown）、
  证据链、KV Cache 估算（结构参数缺失时返回 None）
- `src/tuning_faq.py` —— 6 条调优规则 + 5 条 FAQ 模板，均可追溯到矩阵判定
- `src/doc_assembler.py` —— 方案草稿渲染（纯标准库字符串模板）
- `src/cli.py` —— `--list` / `--conflicts` / `--scenario` / `--all`

### 新增 · 测试
- 39 项单元与端到端测试，含边界：未收录型号、空型号列表、缺失必填字段、
  空字段不填 0、冲突检出、不可推荐档不给调优建议、FAQ 可追溯、同样输入产出同样文档

### 设计决策
- `unknown` 是一等判定档：关键字段缺失或冲突未消解时不下结论，而非猜一个
- DTK 版本分支约束记为独立标记 `version_lock_required`，不降级判定档 ——
  混在一起会让所有型号落进同一档，矩阵失去区分度
- 矩阵按「判定档 → 显存余量降序 → 型号名」排序，余量大的排前面

### 已知问题
- 无真机验证，全部结论基于公开资料与估算模型
- KV Cache 因缺模型结构参数而无法计算，显存需求为下界
- 无 `official` 级数据源，判定均基于公开二手资料
- 吞吐与延迟未建模，只判「装不装得下」，不判「跑得快不快」
