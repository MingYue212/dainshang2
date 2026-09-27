# 尚硅谷电商小二 V2.0 · ai-service 最终实现精读笔记

> 来源：course-v2/extracted/ai-service/ai-service/atguigu/（day11 最终代码包，全项目约 3300 行）
> 精读日期：2026-09-27。本文是 dainshang2 轻量版 harness 的主要参考。

## 1. 模块地图（agent/ 38 个 py）

```
agent/
├── factory.py                    # create_support_agent()：组装 LLM+工具+中间件
├── llm/
│   ├── adapter.py                # ModelAdapter：模型实例 + normalize_output
│   ├── output.py                 # AgentOutput/ReplyType(ANSWER/CLARIFY/DECLINE/REQUEST_HANDOFF)/页面动作
│   └── prompt.py                 # BASE_PROMPT（全局系统提示词）
└── harness/
    ├── errors.py                 # CorrectableErrorCode/TerminalErrorCode/AgentOutputValidationError/AgentExecutionError
    ├── dynamic_prompt.py         # @dynamic_prompt 每次模型调用重渲染系统提示词
    ├── run/
    │   ├── coordinator.py        # AgentRunCoordinator：创建 Run/状态机/事件映射
    │   ├── executor.py           # AgentExecutor：主循环入口 + 纠错重试（≤2 次）
    │   ├── context.py            # ContextCompiler：历史裁剪与当前消息构建
    │   ├── runtime.py            # AgentRuntimeContext(冻结) + AgentExecutionState
    │   ├── output.py             # AgentRunOutPutMapper：输出 → Run 状态映射
    │   └── events.py             # AgentRunState → 事件契约
    ├── tools/
    │   ├── catalog.py            # ToolCatalog/ToolDefinition/ToolCategory + TOOL_CATALOG 单例
    │   ├── read.py               # 8 个业务查询工具（@tool 装饰器）
    │   ├── skill.py              # load_skill 工具（返回 langgraph Command 改状态）
    │   ├── executor.py           # ToolExecutor：落库/执行/校验/信封
    │   ├── output.py             # ToolResult 统一信封 + 业务数据模型
    │   └── snapshot.py           # ToolCallSnapshot：工具调用只读快照
    ├── rules/
    │   ├── fact.py               # FactExtractor + FactChecker（纯函数事实检验）
    │   ├── action.py             # ACTION_CATALOG 页面动作白名单
    │   └── correction.py         # OutputCorrectionRules 纠错反馈消息
    ├── validator/
    │   ├── output.py             # AgentOutputValidator（校验编排）
    │   ├── answer.py             # AnswerValidator（失败降级 + 事实校验）
    │   └── action.py             # PageActionValidator
    ├── skills/
    │   ├── definition.py / catalog.py    # SkillDefinition（5 个技能）+ SKILL_CATALOG
    │   └── middleware.py         # SkillScopeMiddleware：按技能收窄工具列表
    └── knowledge/                # KnowledgeQueryService（固定数据占位）
```

## 2. 一次请求链路

`POST /internal/v1/agent/runs` → AuthService 解析 JWT → AgentRunCoordinator.start_run（落库 AgentRun）→ AgentExecutor.execute：①ContextCompiler 裁剪历史 ②agent.ainvoke（langchain create_agent 主循环 + middleware：@dynamic_prompt、SkillScopeMiddleware、ToolCallLimitMiddleware(run_limit=8)）③normalize_output → AgentOutput ④AgentOutputValidator（事实+动作校验）⑤失败可纠正 → 追加纠错 SystemMessage 复用全轨迹重跑（≤2 次）→ 映射 Run 状态 → 事件契约。

**两种决策类型**：回复决策（ANSWER/CLARIFY/DECLINE/REQUEST_HANDOFF）+ 页面动作（page_action_request）。
**两阶段确认**：带页面动作的回答停在 `DECISION_PREPARED`，前端 confirm → COMPLETED / cancel → SUPERSEDED。

## 3. 关键机制

- **工具信封**：`ToolResult{success, code, message, data, failure_type}`，ToolExecutor 永不向模型抛异常（HTTP 异常→SERVICE_CALL、schema 不符→CONTRACT、业务空→BUSINESS），双层校验（信封 + TypeAdapter(output_schema)）。执行前后落库 AgentToolCall（latency_ms）。
- **令牌透传**：AgentRuntimeContext（frozen dataclass）经 ToolRuntime 注入，工具用用户自己的 JWT 调电商服务。
- **load_skill**：返回 Command 同时改 AgentExecutionState.active_skill_code + 写 ToolMessage 进轨迹；下一跳 dynamic_prompt 与工具收窄立即生效。
- **历史裁剪三策略**（顺序执行）：条数上限 30 → 字符预算 12000（从新往旧保留）→ 从第一条 user 消息开始保留。
- **事实检验**：校验时机 = 循环结束拿到 AgentOutput 之后。FactExtractor 正则抽三类（编号/金额数字/12 个中文状态词）；FactChecker 拿**本 Run 全部成功工具调用的 arguments+result 递归标量**做证据（Decimal 等值、NFKC 归一化）；不过 → UNSUPPORTED_FACT 进纠错循环。证据源 = 执行时落库的工具快照（按 run_id 读，frozen 深拷贝）。
- **页面动作**：模型只报 action_code（白名单 6 个）+ resource_id；URL 由服务端 ACTION_CATALOG 用 quote() 拼；带资源的动作必须有对应 get_order 成功记录，否则 UNVERIFIED_ACTION_RESOURCE。
- **错误码二分**：CorrectableErrorCode（MODEL_OUTPUT_INVALID/UNSUPPORTED_FACT/UNVERIFIED_ACTION_RESOURCE → 纠错重试）vs TerminalErrorCode（MODEL_CALL_FAILED/OUTPUT_VALIDATION_FAILED/AGENT_EXECUTION_FAILED → Run FAILED）；工具层零异常逃逸（ToolFailureType + 固定 DECLINE 降级）。
- **观测**：AgentRun 一行/run（input/output_tokens、latency_ms、model_name、prompt_version、error），UsageMetadataCallbackHandler 汇总。

## 4. 依赖与模型

langchain>=1.0（create_agent/AgentState/middleware/ToolStrategy）+ langchain-openai + langchain-deepseek（deepseek-chat, temperature=0, 关思考）；PostgreSQL(psycopg) + SQLAlchemy 2；pyjwt。**循环本体不是手写的**——是 create_agent + 中间件；"harness"的价值在中间件 + 校验/工具/技能那一圈。

## 5. Skill 定义示例（四段式 guidance）

```python
SkillDefinition(
    code=SkillCode.LOGISTICS_SERVICE,
    description="具体订单的发货状态、承运公司、运单号和物流轨迹",
    guidance=(
        "查询入口：用户没有提供订单编号时，先使用 list_orders 查询订单列表。",
        "工具选择：订单基础信息使用 get_order，配送进度和物流轨迹使用 get_logistics。",
        "可信依据：物流公司、运单号、状态和轨迹只能来自 get_logistics 的成功结果。",
        "边界处理：物流工具失败或没有结果时不得猜测配送进度。"
    ),
    tools=("list_orders", "get_order", "get_logistics")
)
```

## 6. 轻量版吸收清单（按优先级）

1. ToolResult 信封 + ToolExecutor 永不抛异常（消灭"模型看到 traceback 胡编"）
2. agent_tool_calls 快照表（MySQL 建同款：run_id, tool_call_id, tool_name, arguments JSON, result JSON, success, latency_ms）
3. fact.py 纯函数事实检验 + correction.py 反馈闭环（可几乎原样移植）
4. 页面动作服务端白名单（模型只报 code+resource_id，防链接注入）
5. 写操作两阶段确认（课程为 UI confirm；我们前端零改动 → 改为对话级确认）
6. 纠错重试框架（≤2 次，复用整条消息轨迹）
7. AgentRun 观测表（含 prompt_version 字段）
8. SkillScope 工具收窄（未激活只给 load_playbook；激活后给 skill.tools；parallel_tool_calls=False）

**舍弃**：AgentRun.input_context 全量存请求、ToolStrategy（改 bind_tools 原生）、psycopg/SelectorEventLoop（MySQL 不需要）、JWT 服务间鉴权、pg/Redis/turn worker。
