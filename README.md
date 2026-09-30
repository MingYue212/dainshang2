# 电商小二 V2 · 自研 Harness + 单 Agent 智能客服

> 一个电商客服机器人从 **Workflow（YAML 状态机）** 到 **Harness + 智能体** 的架构升级实战。
> 模型自主决策调工具，自研 Harness 层保证它"不编造、不越权、可观测、可恢复"。

[![tests](https://img.shields.io/badge/pytest-57%20passed-brightgreen)]() [![python](https://img.shields.io/badge/python-3.13-blue)]() [![langchain](https://img.shields.io/badge/langchain-1.x-blueviolet)]()

## 这是什么

电商客服智能体：售前咨询、订单/物流查询、退款申请（含二次确认）、商品推荐、政策问答。
模型负责理解与决策，**自研 Harness 层**负责让这些决策安全落地。

- **原版（V1，`../customer-service-backend`）**：LLM 每轮输出 JSON 规划，YAML 状态机执行——执行路径预定义，模型只是"点菜员"
- **本版（V2，本仓库）**：langchain v1 `create_agent` + 自研三中间件 + 校验层——执行路径由模型动态决定，工程系统管住边界

## 核心亮点

**1. 事实检验（Generator–Evaluator 的轻量实现）**
每次工具调用"执行时取证"落库（`agent_tool_calls` 快照）；回复生成后，服务端用正则提取回复中的订单号、金额、状态词，与成功工具结果做 Decimal/NFKC 精确比对——**对不上就打回重答（≤2 次复用全轨迹）**。生产环境真实拦截过"把退款金额改成 5000 元"的诱导。

**2. 护栏不在提示词里，在工具签名和状态机里**
工具参数 pydantic 强校验；提交退款必须先走 `request_refund_confirmation` 登记确认（硬校验订单已核实）→ `AWAITING_CONFIRM` → 确认门（存在/一致/30min 超时）→ 放行提交；用户跑题自动 SUPERSEDED。

**3. 技能工具收窄（Context Engineering）**
未激活领域技能时只暴露 `load_skill`；激活后仅放开该技能工具集 + `parallel_tool_calls=False`——单 agent 覆盖 6 类业务的关键。

**4. 工具统一信封（Tool 错误不吞）**
`ToolResult{success, code, failure_type, message, data}`——HTTP 异常→SERVICE_CALL、schema 不符→CONTRACT、业务失败→BUSINESS，模型永远收到结构化成败，永远看不到 traceback。

**5. 真流式（结构化输出不泄漏）**
WS 新增 `bot_message_delta` token 级分片；最终回答包在结构化输出的 JSON args 里流式返回，字符级状态机实时剥出 `content` 字段解码推送——JSON 骨架对前端透明，解析失败优雅降级为完整帧。

**6. Run 级观测**
每次对话一行 `agent_runs`（tokens/延迟/模型/prompt_version），每次工具调用一行快照——"这轮模型调了什么、返回了什么、为什么被校验打回"全程可追溯。

## 架构

```
前端(Vue,零改动) ──HTTP──▶ api 层 ──▶ dialogue_service（编排）
                              │
                    ┌─────────▼───────────┐
                    │ harness              │
                    │  AgentExecutor（纠错循环≤2）       ┌────────────┐
                    │  middleware: 动态提示/技能收窄  │──▶│ qwen(百炼)  │
                    │  ToolCallLimit(12)              │   └────────────┘
                    │  tool_executor（信封+快照落库）   │
                    │  validator: 事实检验/动作白名单    │
                    │  skills: 5 领域技能（guidance 四段式）│
                    └──────┬───────────────┘
                           │ 工具调用（httpx）
              MySQL（chat_messages / agent_runs / agent_tool_calls）
                           │
                    电商业务 API(18081)：订单/物流/退款/推荐
```

## 快速启动

```bash
# 1) 数据库（项目根 ../docker/docker-compose.yml）与电商业务 API
docker compose up -d          # MySQL 8.4，初始化脚本自动建库
cd ../ecommerce-service-backend && uv run main.py    # 业务 API :18081

# 2) 对话引擎（本仓库）
uv sync
uv run main.py                # :18082，.env 配置模型与数据库

# 3) 前端（../customer-service-frontend，零改动接入）或流式演示页
#    直接用浏览器打开 ws-test.html，可看 token 级逐字输出
```

## 测试与评测

```bash
uv run pytest                                    # 57 用例：信封/事实检验/状态机/确认门/技能收窄/流式提取
uv run python evals/runner.py --base-url http://127.0.0.1:18083 --tag v2 --clean --scope v2
uv run python evals/runner.py --base-url http://127.0.0.1:18082 --tag v1 --clean --scope v1
uv run python evals/judge.py --tag v2 && uv run python evals/judge.py --tag v1
uv run python evals/report.py                    # 生成 docs/eval-report.md
```

评测集：50 条 · 六维度（正常路径 12 / 缺槽位反问 8 / 打断恢复 8 / 多意图 6 / 越界与诱导 10 / 闲聊知识 6）。
判分 = 规则断言（确定性事实，可复现）+ LLM-judge（主观质量 1~5，temperature=0）。
对比结果见 [docs/eval-report.md](docs/eval-report.md)。

## 文档链

| 文档 | 内容 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 需求与验收：G/FR/NFR/AC/EC 编号体系，含评审修正记录 |
| [docs/SPEC.md](docs/SPEC.md) | 技术规格：模块/DDL/中间件/工具与技能全文/BASE_PROMPT/契约字段 |
| [docs/upgrade-log.md](docs/upgrade-log.md) | 设计访谈全记录（Round 1~5）+ M1~M3 实施记录与实战故障 |
| [docs/course-ai-service-notes.md](docs/course-ai-service-notes.md) | 尚硅谷电商小二 V2.0（harness+智能体）参考实现精读 |
| [docs/learn-plan.md](docs/learn-plan.md) | Harness 学习路线 |

## 诚实的边界

- 循环骨架使用 langchain v1 `create_agent`（与课程一致）——自研重心在中间件与校验层；Framework 提供积木，Harness 是组装后的运行系统
- 定位"对话域轻量 Harness"：无 Subagents / 长任务检查点（对话单轮即闭环，不需要）；无 Redis/pg/turn worker（单进程演示定位，主动砍掉）
- 知识检索为固定 FAQ 占位 Provider（接口已预留，换向量库只换实现）
- 模型实测结论：qwen thinking 模式不支持 `tool_choice=required`，ToolStrategy 需构造器级 `extra_body={"enable_thinking": False}`（见 `scripts/probe_qwen.py`）
