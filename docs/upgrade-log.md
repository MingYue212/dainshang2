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
| 主循环 | langchain v1 create_agent + 自研三中间件（R5 精化，与课程一致） | ✅ |
| PRD | v1.0 已审核通过（2026-09-27），进入 SPEC 编写 | ✅ |
| SPEC | v1.0 产出（docs/SPEC.md，18 章），等用户审定 | ⏳ |
| 护栏 | 工具签名 pydantic 强校验为主，prompt 配合，checklist 注入 | ✅ |
| 流程知识 | markdown playbook + 工具参数模型 | ✅ |
| API | 完全兼容 csb，跑 18082，前端零改动 | ✅ |
| 复用 | 抄 infra/Action/provider，重写 engine 与 prompts | ✅ |
| 持久化 | 只存消息历史，业务数据现查现用 | ✅ |
| 评测 | 50 条分维度标注集 + HTTP 黑盒双版跑分 | ✅ |
| 判分 | 规则断言（确定性维度）+ LLM-as-judge（主观维度） | ✅ |
| 对齐策略 | 轻量对齐（保自研轻量边界，吸收课程 harness 概念） | ✅ |
| 课程资料 | day11 最终代码 4 包验证解压完毕；md 课件未下（可选补） | ✅ |

## 5. 待办池

- [x] 用户下载课程代码（day11 最终版 4 包，验证并解压到 ../course-v2/extracted/）
- [x] Round 4：对齐策略 = 轻量对齐
- [x] 课程参考实现精读（docs/course-ai-service-notes.md）+ 最终架构方案（第 8 节）
- [x] M0-1：dainshang2 旧骨架存档 commit（a199c2b）
- [x] Round 5：循环改用 create_agent + 三中间件；8.3 两处精化确认；先 PRD 后代码
- [x] PRD v1.0 产出并经用户审核通过（2026-09-27，全部接受）；v1.1 增补契约核实修订（见 PRD 13.5 末行）
- [x] SPEC v1.0 产出（docs/SPEC.md，18 章）
- [ ] ⏳ **等用户审定 SPEC** → M0-2 清场 + M1 开工
- [ ] M1：harness 最小闭环（循环 + 工具信封 + 1 个工具 + 消息历史 + API 兼容 + pytest）
- [ ] M2：全工具 + playbook（按需加载）+ 三层护栏；M3：真流式；M4：RAG 壳子
- [ ] M5：50 条评测集 + 跑分脚本 + 双版对比表
- [ ] M6：README / 架构图 / 面试材料
- [x] 补下课件：day07~11 课件 + 面试指南 + Harness 概念文档 + excalidraw 笔记（../course-v2/2_resource、4_other/）

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

对应关系：csb ≈ 课程 V1 的电商客服（workflow 版）；dainshang2 的目标 ≈ V2.0 的 ai-service（harness+智能体）。

**下载验证（2026-09-27 晚）**：用户下载了 day11 最终代码 4 件套到 `../course-v2/3_code/`（ai-service.zip 410KB / backend.zip 84KB / customer-service.7z 161KB / frontend.zip 50KB，字节数与网盘清单一致）。三个 zip testzip 通过，7z 用 bsdtar 验证通过，已解压到 `../course-v2/extracted/`（ai-service 242 文件 / customer-service 186 项 / backend 27 / frontend 23）。**完整性结论：最终代码齐全 ✅；md 课件（2_resource）未下载**——day07《面试指南》《Harness_Engineering 概念与原理》和 day08~11 课件建议补下（可选，不阻塞开工）。

**Round 4 决定（2026-09-27）**：对齐策略 = **轻量对齐**——保持已定轻量边界（单服务/API 兼容/只存历史/MySQL），吸收课程 harness 成熟概念。

---

## 7. 课程参考实现精读（摘要）

完整笔记见 [docs/course-ai-service-notes.md](course-ai-service-notes.md)。要点：

- 课程的循环本体是 langchain v1 `create_agent` + 中间件（@dynamic_prompt / SkillScopeMiddleware / ToolCallLimitMiddleware），**"harness"的价值在中间件 + 工具/校验/技能那一圈**。我们自研循环 = 把这三个中间件的职责自己实现，概念可一一对应。
- 最值得吸收的 8 个设计：①ToolResult 信封（工具永不向模型抛异常）②工具调用快照落库 ③事实检验纯函数（提取/比较/纠错反馈）④页面动作服务端白名单 ⑤写操作两阶段确认 ⑥纠错重试（≤2 次、复用全轨迹）⑦AgentRun 观测表（含 prompt_version）⑧技能工具收窄。
- 课程模型是 deepseek-chat；我们是 qwen 百炼，仅配置差异。

## 8. 最终架构方案（轻量对齐版 · 2026-09-27 · 待确认）

### 8.1 设计原则

- **边界**：单服务（对话引擎+agent 一体），API 契约照抄 csb，前端零改动；MySQL 存消息历史 + 两张运行表；不引入 pg / Redis / turn worker / 服务间 JWT（day01~06 生产化重制明确不吸收）。
- **循环**：langchain v1 create_agent 为骨架 + 自研三个中间件（动态提示 / 技能工具收窄 / 调用上限），与课程实现保持一致（R5 精化）。
- **命名与课程对齐**（面试无缝衔接）：AgentRun / ToolResult / 工具快照 / Skill(playbook) / 事实检验 / 纠错循环 / 可纠正 vs 终态错误码。

### 8.2 模块清单（app/ 下）

| 模块 | 内容 | 来源 |
|---|---|---|
| `api/` | 路由 + 交互模型（契约照抄 csb；WS 事件兼容） | 抄 csb |
| `harness/` | middleware/（dynamic_prompt、skill_scope、call_limit=8 三中间件）；executor.py（执行 + 纠错循环）；run.py（AgentRun + agent_tool_calls 落库）；tool_executor.py（工具执行信封）；context.py（三层历史裁剪：条数 30 → 字符预算 12k → 从首条 user 保留；含未完成任务摘要注入）；events.py（WS 事件装配） | 吸收课程 |
| `agent/` | prompts（三层：全局 BASE_PROMPT / playbook 动态层 / 动作索引）；correction.py（纠错反馈消息，≤2 次重跑、复用全轨迹） | 吸收课程 |
| `skills/` | catalog（技能：商品 / 订单 / 物流售后 / 退款 / 政策问答 + 闲聊兜底）；definition（guidance 四段式：查询入口/工具选择/可信依据/边界处理）；middleware（未激活只给 load_playbook，激活后给 skill.tools） | 吸收课程 |
| `tools/` | registry（ToolDefinition + category 标签）；business/（查订单/查物流/提交退款/相似推荐，由 csb Action 改造）；envelope（ToolResult 泛型信封）；action.py（页面动作白名单：模型只报 code+resource_id，服务端拼 URL，资源必须先被成功查询）；knowledge.py（RAG 壳） | 吸收课程 + 抄 csb |
| `rules/` | fact.py（编号/金额/状态三类事实提取与比较，改造课程实现） | 吸收课程 |
| `errors/` | Correctable（→纠错循环）vs Terminal（→FAILED+稳定错误码）二分 | 吸收课程 |
| `memory/` | 消息历史（MySQL）；agent_runs / agent_tool_calls 两张运行表 | 吸收课程 |
| `infra/` | llm_client（langchain-openai 薄客户端，qwen 百炼）/ config / db | 抄 csb |

### 8.3 相对 Round 2 决策的两处精化（需要确认）

1. **playbook 交付方式**：Round 2 定的"全量注入 system prompt" → 精化为课程式"**目录常驻 + load_playbook 工具按需加载 + 工具收窄**"。省 token、降选错工具率，中间件模式与课程一致。
2. **护栏从一层变三层**：Round 2 定的"护栏在工具签名里" → ①工具参数 pydantic 强校验（原方案）②事实检验（回复中的编号/金额/状态必须来自本 Run 成功工具结果，否则纠错重跑）③写操作（提交退款）**对话级二次确认**——agent 复述订单+退款原因，用户下一条消息确认后才调工具。课程的 UI 级 confirm 接口因"前端零改动"约束改为对话级实现。

### 8.4 吸收 / 不吸收清单

- **吸收**：ToolResult 信封 / 工具快照落库 / 事实检验纯函数 / 动作白名单 / 纠错循环（≤2、复用轨迹）/ AgentRun+用量观测（prompt_version）/ Skill 收窄 / 三层历史裁剪 / 三层 prompt / 错误码二分。
- **不吸收（轻量边界）**：pg、Redis pub/sub、turn worker 异步领取、JWT 服务间鉴权、UI 级 confirm/cancel 接口（改对话级）、ToolStrategy（用 bind_tools 原生结构化输出）。

---

## 9. Round 5（2026-09-27 · 已答）

| # | 问题 | 决定 |
|---|---|---|
| Q1 | 缺失课件 | 已下载齐全：day07~11 课件 + 面试指南 + Harness 概念文档 + excalidraw 笔记（../course-v2/2_resource 与 4_other/；day08 课件已从误拼目录 2_resouce 归位） |
| Q2 | 循环本体 | **改用 langchain v1 create_agent + 自研三中间件**（动态提示 / 技能工具收窄 / 调用上限），与课程保持一致。R2-Q1 的"自研 while 循环"就此精化：自研重心在 harness 中间件与校验层，不在循环骨架 |
| Q3 | 8.3 两处精化 | 确认采纳（playbook 按需加载 + 三层护栏含退款对话级二次确认） |
| Q4 | 开工节奏 | **先写 PRD 汇报审核，通过后再写代码**（采用 prd-craft 工作流） |

推论与影响：

- 依赖不变：csb 的 langchain>=1.3 已内置 create_agent / middleware / langgraph Command。
- 简历措辞调整："基于 langchain v1 agent 中间件机制自研工程化 harness 层（工具信封 / 快照取证 / 事实检验 / 纠错闭环 / 技能收窄）"。
- 8.1/8.2 架构方案已同步修订（middleware/ 代替 loop.py）。
