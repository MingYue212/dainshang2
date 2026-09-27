# dainshang2 智能体改造 · 设计讨论记录

> 本文件持续记录 harness + 智能体改造的设计对话与全部决策，按轮次追加。
> 基线：`../customer-service-backend/`（workflow 版，可运行）；本目录 `dainshang2/`（agent 版，重建中）。
> 开始日期：2026-09-27

---

## 0. 事实基线（2026-09-27 代码探索结论）

- **customer-service-backend（csb）**：完整可跑的 workflow 版，3652 行 Python + 438 行 YAML。
  架构 = LLM 每轮输出 JSON 规划（TurnPlanner）+ 自研 YAML 流程引擎（FlowExecutor）+ 三轨分派（task / knowledge / chitchat）。
  亮点：任务打断恢复（paused_tasks）、焦点对象自动填槽、对象消息处理。
- **已知短板**：无 tool calling / agent（LLM 只能发 4 种命令）；RAG 空壳（检索写死"未检索到相关问题"，无向量库）；LLM 非流式（WS 伪流式）；流程条件跳转用裸 `eval()`；测试为手动脚本（无 pytest）；整份 DialogueState JSON 存 MySQL（question.md 已指出写放大 / 丢更新问题）。
- **dainshang2**：2026-09-11 新开的重写骨架，仅 264 行且语法不完整（routers.py 未写完），`app/` 未提交 git。本次作为 agent 版的新家重建。
- **技术栈**：Python 3.13 + uv、FastAPI、LangChain 1.x（langchain-openai）、qwen（阿里百炼 OpenAI 兼容接口）、MySQL 8.4（docker compose）、前端 customer-service-frontend（Vue3）+ shuziren.html 数字人页。
- **电商业务 API**：ecommerce-service-backend（18081），提供订单状态 / 物流 / 退款提交 / 相似推荐等接口。
- **对话引擎端口**：csb 跑 18082（`/api/chat`、`/ws/chat`、`/api/chat/history`、`/api/digital-human/credentials`）。

---

## 1. Round 1（2026-09-27 · 已定）

| # | 问题 | 选项 | 决定 |
|---|---|---|---|
| Q1 | 改造目的 | a 简历/面试 · b 真实上线 · c 学习 | **a）简历/面试项目**：要架构亮点、取舍故事、量化对比 |
| Q2 | 目标形态 | a 混合护栏 · b 全 agent 化 · c 多智能体 | **b）全 agent 化**：拆掉状态机，一个大 agent 挂全部 tools，靠 prompt + tool calling 完成一切 |
| Q3 | 改造落点 | a csb 原地升级 · b dainshang2 重写 · c 新目录 | **b）dainshang2 重建**：可复用环境、可粘贴 csb 代码改造、可自写 |
| Q4 | 短板处理 | — | **RAG 只建壳子**（不接真向量库，能讲清套路应付面试即可）；其余按建议：流式改真流式、agent 循环与工具层补 pytest；eval() 安全、状态拆表缓 |

推论与影响：

- YAML 流程引擎（FlowExecutor / commands / validator）整体退役；"打断恢复"由对话历史 + agent 自身注意力天然承担。
- 简历故事线：固定 workflow → 自研 harness + tool-calling 智能体，并用量化评测证明"更强"。

---

## 2. Round 2（2026-09-27 · 已答）

| # | 问题 | 决定 |
|---|---|---|
| Q1 | 主循环技术选型 | **b）自研 harness 循环 + langchain-openai 薄客户端**：循环自己写（while + bind_tools），模型调用沿用 ChatOpenAI（百炼兼容） |
| Q2 | 护栏位置 | **b）护栏在工具签名里**：工具参数 pydantic 强校验，缺参返回错误让 agent 自然反问；system prompt 约束配合；harness 每轮注入"未完成任务/待收集字段"摘要顺手做 |
| Q3 | 流程知识去向 | **b）markdown playbook**：每条流程一节（目的、前置、必收信息、可用工具）随 prompt 注入；槽位定义转成工具 pydantic 参数模型；YAML 引擎文件退役 |
| Q4 | API 兼容 | **a）完全兼容**：dainshang2 跑 18082，契约照抄 csb，前端零改动 |
| Q5 | 代码复用 | **a）抄部件、重写大脑**：infra 照抄、4 个业务 Action 改造成 tools、knowledge HTTP provider 照抄；engine/prompts 全部重写 |
| Q6 | 状态持久化 | **a）只存消息历史**：agent 每轮从历史重建上下文，业务数据现查现用；断线恢复、对象卡片由 harness 适配层处理 |
| Q7 | 评测集 | **要建**；规模 20 条被否，Round 3 定规模与判分方式 |

推论与影响：

- harness 的核心交付物清单：agent 主循环、工具注册表、上下文组装（消息历史 + playbook + 未完成任务摘要）、参数护栏（pydantic）、可观测（日志/事件）。
- 焦点对象 / 点选卡片消息 → harness 适配层翻译成普通上下文文本，agent 无感知。
- WS 真流式必须在现有前端协议内实现（BotMsg + thinking/done 状态），最终回答的 token 流分片下发。

---

## 3. Round 3（2026-09-27 · 待答）

**Q1 评测集规模**
- a) 30 条　b) 50 条（按维度分层，脚本支持随时扩充）　c) 80~100 条
➡️ 推荐 b：50 条按维度分层后每格 5~8 条已能稳定区分两版差异；每条都要写"预期行为"，质量比数量重要；全量跑一轮要花 LLM 调用，太多会拖迭代。讲出口也够分量（"50 条标注评测集"）。

**Q2 判分方式**
- a) 规则断言（检查工具调用序列、槽位、关键词）
- b) LLM-as-judge（用另一个 LLM 按标准打分）
- c) 混合：确定性维度（工具序列/槽位/完成与否）用规则断言，最终回答质量用 LLM-as-judge
➡️ 推荐 c：规则断言可复现、零成本，judge 补主观维度。面试追问"完成率谁判的"时有干净答案。

**Q3 收尾确认清单（默认项，有异议则改）**
1. 包结构：`app/api`（路由契约照抄 csb）、`app/harness`（主循环/工具注册/护栏/上下文组装）、`app/agent`（system prompt、playbook 加载）、`app/tools`（业务工具 + pydantic 参数）、`app/memory`（消息历史）、`app/infra`（llm_client/config/db，抄 csb）
2. 评测走 HTTP 黑盒：脚本同时打 csb(18082) 和 dainshang2 的接口，同一套 case 公平对比
3. 开工前先把 dainshang2 当前残缺骨架 commit 一次存档，再清场重写
4. 里程碑：M0 存档清场 → M1 harness 最小闭环（循环+1工具+历史+API 兼容+pytest）→ M2 全工具+playbook+护栏 → M3 真流式 → M4 RAG 壳子 → M5 评测双版对比 → M6 文档与面试材料
➡️ 无异议即视为共识达成，进入架构方案与开工。

---

## 4. 决策汇总表（随轮次更新）

| 决策 | 结论 | 状态 |
|---|---|---|
| 目的 | 简历/面试项目 | ✅ |
| 形态 | 全 agent 化（拆状态机，单 agent + tools） | ✅ |
| 落点 | dainshang2 重建，csb 为基线 | ✅ |
| RAG | 只建壳子（面试讲套路） | ✅ |
| 流式 | 真流式（协议兼容现有前端） | ✅ |
| 测试 | agent 循环 + 工具层 pytest | ✅ |
| 主循环 | 自研 harness 循环 + langchain-openai 薄客户端 | ✅ |
| 护栏 | 工具签名 pydantic 强校验为主，prompt 配合，checklist 注入 | ✅ |
| 流程知识 | markdown playbook + 工具参数模型 | ✅ |
| API | 完全兼容 csb，跑 18082，前端零改动 | ✅ |
| 复用 | 抄 infra/Action/provider，重写 engine 与 prompts | ✅ |
| 持久化 | 只存消息历史，业务数据现查现用 | ✅ |
| 评测 | 要建自动评测，规模与判分方式 Round 3 定 | ⏳ |

## 5. 待办池

- [ ] ⏳ **等用户**：下载课程资料的 2_resource + 3_code + 4_other（约 25MB，13GB 视频不用下）到本地（如 `D:\Code\VSCode\ecommerce_customer_ls\course-v2\`），告知路径
- [ ] ⏳ **Round 4 待决**：与官方 V2.0 的对齐策略（完整跟课 / 轻量对齐 / 代码对照）
- [ ] 对齐后更新架构方案（吸收课程概念：协调者 / AgentRun / Skills / 事实检验 / 异常治理），再进 M0
- [ ] M0：dainshang2 残缺骨架 commit 存档后清场重写
- [ ] M1：harness 最小闭环（循环 + 1 工具 + 消息历史 + API 兼容 + pytest）
- [ ] M2：全工具 + playbook + 护栏；M3：真流式；M4：RAG 壳子
- [ ] M5：50 条评测集 + 跑分脚本 + 双版对比表
- [ ] M6：README / 架构图 / 面试材料
- [ ] RAG 壳子设计要点：Provider 接口 + 假检索实现（面试可讲：换向量库只换 Provider）

---

## 6. 课程资料检查（2026-09-27 · 开工前置项）

链接：https://pan.baidu.com/s/18v2JYklN8HA2u_r5snH3EA（提取码 yyds）

**结论：能访问。** 内容 = 尚硅谷《大模型项目之电商小二 V2.0（harness+智能体）》全套课程资料（11 天，149 个视频共 12.99GB + 课件/代码/笔记约 25MB）。

结构：

- **day01~06：重制版 customer-service**——比 csb 多了 JWT 认证、turn worker 异步领取轮次、会话/轮次/消息三表 + 版本字段 + 并发锁、Redis pub/sub 实时推送、人工客服工单、监控。即课程把 V1 的"伪流式直接处理"升级成了生产化异步架构（含 pg 数据库）。
- **day07：客服服务测试总结 + AI_Service 框架搭建**（协调者、两种决策类型、两阶段准备确认）；附《Customer Service 项目总结与面试指南.md》《Harness_Engineering概念与原理.md》。
- **day08：AI 服务核心链路**——模型实例封装、FastAPI 生命周期共享 Agent、AgentRun、上下文构建（历史裁剪三种策略）、结构化输出。
- **day09：工具定义与执行**——Agent 运行上下文、令牌透传、业务读工具、工具执行器、端到端流程。
- **day10：生产级 Harness**——事实检验（提取/比较/校验输出三组件、工具快照）、页面行动校验、异常体系（工具层 / Output 校验层 / 执行层 / 协调层）。
- **day11：全链路打通**——四层边界、全局提示词、Skills 定义/分类/中间件、load_skill 修改 AgentState 共享状态、商品/订单/售后物流领域工具测试；3_code 是四服务最终版代码包。
- 每天都有：`1_vcr/` 视频、`2_resource/` md 课件（共 17 个 398KB）、`3_code/` 当日代码 zip、`4_other/` excalidraw 课堂笔记。

访问能力边界：**浏览目录 ✅**（提取码已验证，能列出全部 228 个文件）；**直接下载 ❌**（百度 sign 反爬，未登录会话拿不到 dlink 签名，share/download 与 tplconfig 均 errno=2）。

对应关系：csb ≈ 课程 V1 的电商客服（workflow 版）；dainshang2 的目标 ≈ V2.0 的 ai-service（harness+智能体）。已定方案（自研循环/工具签名护栏/playbook/只存历史）与课程方向一致，但课程另有协调者、两阶段确认、Skills、事实检验、异常治理等概念，待 Round 4 定对齐深度。
