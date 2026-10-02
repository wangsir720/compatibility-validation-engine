# 数据来源登记表

> 本文件是 `data/` 下所有数据表的**唯一出处**。每条数据行都带 `source_id` 与 `credibility` 两列，
> 前者指向本表条目，后者标注可信等级。判定逻辑见 `src/catalog.py`。
>
> **抓取日期：2026-10-02**（全部条目同批抓取）

## 可信等级定义

| 等级 | 含义 | 在判定中的作用 |
|---|---|---|
| `official` | 厂商官网 / 官方文档 / 官方镜像仓库 | 可直接作为判定依据 |
| `secondary` | 百科、聚合站、行业媒体、已署名技术博客 | 可作为判定依据，但结论中必须显示来源 |
| `unverified` | 单一来源、与官方口径矛盾、或明显孤证 | **不参与自动判定**，仅列为待人工核实项 |

> 本项目**没有任何 `official` 级数据** —— 原因是芯片规格与软件栈版本未在厂商官网公开文档中
> 提供可直接引用的规格表（官网仅有产品宣传页，无参数表）。
> 这意味着：**本引擎输出的每一条判定都是「基于公开二手资料」的方法论验证，不是厂商认证结论。**
> 这一点在 README 与输出文档中都会显式声明。

## 来源清单

| source_id | 类型 | 名称 | URL | 覆盖内容 |
|---|---|---|---|---|
| S1 | secondary | 百度百科 · C86-4G | https://baike.baidu.com/item/c86-4g/68091380 | CPU 型号核数/主频/缓存；Geekbench 6 得分；生态适配数量 |
| S2 | secondary | 今日头条 · 海光 C86 全系列 CPU 参数表（2G/3G/4G 合集） | https://www.toutiao.com/a7668201996213633570 | CPU 7 系/5 系/3 系全型号参数表 |
| S3 | secondary | 集特智能 · 国产海光 4 号处理器参数整理 | https://jingchuang391.cn.china.cn/corparticle-leads.html | 3490/7480 频率（与其他来源冲突） |
| S4 | secondary | 百度百科 · 海光四号 | https://baike.baidu.com/item/%E6%B5%B7%E5%85%89%E5%9B%9B%E5%8F%B7/67363340 | 7400 系列发布信息、国密能力 |
| S5 | secondary | CSDN · Linux 系统上使用海光 DCU 部署开源大模型全攻略（以 Qwen3-8B 为例） | https://blog.csdn.net/qq_23625847/article/details/159507206 | **DCU 规格表**、DTK 版本与内核对应矩阵、vLLM/Ollama 镜像标签、torch 版本号 |
| S6 | unverified | EET China · 十问十答解读 AI 芯片未来 | https://www.eet-china.com/mp/a209073.html | Z100 FP32 算力另一口径（与 S5 冲突）、超算中心部署情况 |
| S7 | secondary | 百度百科 · 海光 DCU | https://baike.baidu.com/item/%E6%B5%B7%E5%85%89DCU/68580827 | Z100L 计算单元数与核心数、显存带宽；400+ 大模型适配口径 |
| S8 | secondary | Ultralytics YOLOv8 官方文档 | https://docs.ultralytics.com/models/yolov8/ | 视觉检测模型参数量与规模 |
| S9 | secondary | ROCm 官方文档 | https://rocm.docs.amd.com/ | DTK 的对标软件栈参照系（架构分层，非海光数据） |

## 已识别的来源冲突（不静默取舍）

引擎在加载数据时会自动检测同型号同字段的多来源取值差异，并标记为冲突。
**当前数据集中已确认 3 处冲突**：

| 冲突项 | 取值 A | 取值 B | 处置 |
|---|---|---|---|
| `Z100` FP32 算力 | 10.8 TFLOPS（S5） | 21.0 TFLOPS（S6，标 unverified） | 取 S5；S6 列入待人工核实 |
| `7480` 基础频率 | 2.0 GHz（S2） | 2.2 GHz（S3） | 判定不使用频率字段；仅记录冲突 |
| `3490` 最高加速频率 | 3.3 GHz（S2） | 3.5 GHz（S1） | 同上 |

> **设计取舍说明**：出现冲突且一方为 `unverified` 时，引擎采用可信等级更高的一方并**显式记录冲突**；
> 双方等级相同时，相关字段一律降级为「未查到」并从自动判定中排除 —— 
> 理由是：宁可少判，不可错判。适配性验证的价值在于每条结论都能站住。
