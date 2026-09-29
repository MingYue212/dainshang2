# 电商客服智能体引擎（dainshang2）· 技术设计规格（SPEC）

| 项 | 内容 |
|---|---|
| 版本 | v1.0（2026-09-27） |
| 上游文档 | [PRD.md](PRD.md) v1.1（需求与验收）、[upgrade-log.md](upgrade-log.md)（设计访谈）、[course-ai-service-notes.md](course-ai-service-notes.md)（课程参考实现精读） |
| 本文档定位 | **怎么实现**：模块/类/函数级设计、DDL、中间件行为、prompt 与技能全文、契约字段。需求与验收以 PRD 为准，本文不重复 |
| 契约依据 | V1 契约与 18081 端点已逐字段核实（证据见 14 章标注），非凭印象 |
| 状态标记 | ✅ 已定 ｜ ⚠️ 依赖 M1 实测 ｜ 📌 扩展候选（不在本期范围） |

---

## 1. 架构总览

### 1.1 组件图

```
                     ┌────────────────────────────────────────────────┐
                     │                dainshang2 (18082)               │
 前端(Vue,零改动)     │  ┌──────────┐   ┌──────────────────────────┐   │
 ┌──────────┐ HTTP   │  │ api 层    │   │ harness                  │   │
 │ServiceChat├───────┼─▶│ /api/chat │──▶│ dialogue_service         │   │
 └──────────┘ /ws/chat│  │ /ws/chat  │   │   ├─ memory/repository   │──┐│
 (ws-test.html 演示)  │  │ /history  │   │   ├─ run_service(状态机)  │  ││
 ┌──────────┐ HTTP   │  └──────────┘   │   └─ executor(纠错循环)   │  ││
 │数字人页面 ├───────┼▶ credentials    │        │ create_agent     │  ││
 └──────────┘        │                 │   ┌────┴───────────┐      │  ││
                     │                 │   │ agent(组装)     │      │  ││
                     │                 │   │ ├ middleware×2  │      │  ││
                     │                 │   │ │ dynamic_prompt│      │  ││
                     │                 │   │ │ skill_scope   │      │  ││
                     │                 │   │ ├ tools×7+1     │──┐   │  ││
                     │                 │   │ └ output 校验    │  │   │  ││
                     │                 │   └────────────────┘  │   │  ││
                     │  ┌──────────┐   │   rules(fact)+validator│  │  ││
                     │  │ infra     │  │   skills(catalog)      │  │  ││
                     │  │ llm→qwen◀─┼──┼────────────────────────┘  │  ││
                     └──┴───────────┴──┴───────────────────────────┴──┘│
                         ▲                            ▲                 │
                         │ MySQL(customer_service_v2) │ httpx           │
                         └────────────────────────────┴─────────────────┘
                              三表:chat_messages/agent_runs/   电商业务API
                                  agent_tool_calls            (18081)
```

### 1.2 一次请求时序（HTTP 路径，前端实际使用）

```
ChatRequest → dialogue_service.process()
  1. repository.save_message(user)                  # 消息先落库
  2. run_service.create(conversation_id) → Run(RUNNING)
  3. ContextCompiler.compile()                      # 历史裁剪 + 对象消息注入 + 待确认摘要
  4. AgentExecutor.execute(run, messages):
     4a. agent.ainvoke()                             # create_agent 主循环
         ├ dynamic_prompt: 每次模型调用重渲染系统提示
         ├ skill_scope: 修改本次请求的可见工具集
         ├ (内置) ToolCallLimitMiddleware(run_limit=8)
         └ 工具调用 → tool_executor.envelope() → 快照落库 → 信封 JSON 回模型
     4b. response_format → AgentOutput(pydantic)
     4c. AgentOutputValidator.validate(output, run_id)
         ├ PageActionValidator: 动作白名单 + 资源核实
         └ AnswerValidator: 事实检验（读 agent_tool_calls 成功记录）
     4d. 可纠正错误 → OutputCorrectionRules.feedback() 追加 SystemMessage → 回 4a（≤2 次）
  5. run_service.finalize(): 状态机流转 / AWAITING_CONFIRM 判定 / 用量回填
  6. repository.save_message(bot) + commit
  7. ChatResponse{sender_id, msg_id, msgs:[BotMsgResponse]}          # 与 V1 字段一致
```

WS 路径差异：第 1 步前发 `status:thinking`；第 4~7 步之间每当 AgentOutput 就绪即发 `bot_message`，流式演示走 `bot_message_delta`（见 14.4）；结束发 `status:done`。异常发 `error`。

### 1.3 依赖方向原则

`api → service → harness → {agent, tools, rules, validator, skills, memory} → infra`。上层可依赖下层，反向禁止；tools 不 import validator；rules/validator 为纯逻辑（不依赖 FastAPI）。这保证 pytest 不起服务就能测 harness 全部核心。

## 2. 目录结构

```
dainshang2/
├── main.py                          # uvicorn app.api.app:app --port 18082
├── pyproject.toml / uv.lock         # 继承现有依赖（langchain>=1.3 已含 create_agent/middleware）
├── .env / .env.example
├── ws-test.html                     # 流式演示页（独立静态页，不动 Vue 工程）
├── docs/                            # PRD / SPEC / upgrade-log / course-ai-service-notes
├── evals/
│   ├── dataset.yaml                 # 50 条题库（schema 见 16.1）
│   ├── runner.py                    # HTTP 黑盒跑分（--base-url × --dataset）
│   ├── judge.py                     # LLM-as-judge
│   └── report.py                    # 对比报告生成 → docs/eval-report.md
├── tests/                           # pytest（见 15 章映射表）
└── app/
    ├── api/
    │   ├── app.py                   # FastAPI 实例 + lifespan（db/httpx）
    │   ├── schemas.py               # V1 兼容交互模型（14.1 逐字段）
    │   ├── routers.py               # 4 个端点
    │   └── deps.py
    ├── conf/config.py               # Settings（9.3 参数表全部集中于此）
    ├── domain/
    │   ├── messages.py              # MsgType/MsgObject/UserMsg/BotMsg（V1 同构）
    │   └── enums.py                 # RunState/ReplyType/FailureType/SkillCode/ToolCategory
    ├── errors.py                    # CorrectableErrorCode/TerminalErrorCode/异常类
    ├── infra/
    │   ├── llm.py                   # ChatOpenAI 工厂（百炼、temperature=0）
    │   ├── db.py                    # async engine/session（aiomysql）
    │   └── commerce_client.py       # httpx 单例 + ApiResponse{code,message,data} 解包
    ├── memory/
    │   ├── models.py                # SQLAlchemy ORM：三表（3 章 DDL）
    │   └── repository.py            # 消息/Run/ToolCall 读写
    ├── harness/
    │   ├── middleware/
    │   │   ├── dynamic_prompt.py    # @dynamic_prompt 三层重渲染（6.1）
    │   │   └── skill_scope.py       # 工具收窄中间件（6.2）
    │   ├── executor.py              # AgentExecutor：ainvoke + 纠错循环（6.4）
    │   ├── tool_executor.py         # 信封 + 快照落库（6.5）
    │   ├── run_service.py           # Run 生命周期与状态机（10 章）
    │   ├── context.py               # ContextCompiler（11 章）
    │   └── events.py                # WS 事件装配
    ├── agent/
    │   ├── factory.py               # create_support_agent()
    │   ├── prompts.py               # BASE_PROMPT 全文（9 章）
    │   └── output.py                # AgentOutput/ReplyType/PageActionRequest
    ├── skills/
    │   ├── definition.py            # SkillDefinition(pydantic frozen)
    │   ├── catalog.py               # SKILL_CATALOG 全文（7 章）
    │   └── load_skill.py            # load_skill 工具（Command 更新状态）
    ├── tools/
    │   ├── envelope.py              # ToolResult 泛型（5.2）
    │   ├── registry.py              # ToolCatalog/ToolDefinition/ToolCategory
    │   ├── action.py                # ACTION_CATALOG（9 章）
    │   └── business/
    │       ├── orders.py            # list_orders / get_order
    │       ├── logistics.py         # get_logistics
    │       ├── products.py          # get_product / recommend_similar_products
    │       ├── refund.py            # submit_refund_application（确认门）
    │       └── knowledge.py         # search_knowledge（固定 FAQ Provider）
    ├── rules/
    │   ├── fact.py                  # FactExtractor/FactChecker（12.2）
    │   └── correction.py            # OutputCorrectionRules（12.4）
    ├── validator/
    │   ├── output.py                # AgentOutputValidator 编排
    │   ├── answer.py                # 事实检验 + 降级
    │   └── action.py                # 动作白名单校验
    └── service/
        └── dialogue_service.py      # 编排入口（1.2 时序的实现载体）
```

## 3. 数据层（DDL）

新增库 `customer_service_v2`（初始化脚本放 `../docker/mysql/initdb/003_init_v2.sql`，父目录 compose 已挂载 initdb，M1 核实挂载与建库授权；脚本幂等）。

> **M1 环境实测修订（2026-09-27）**：本机 3306 为宿主机原生 MySQL（Docker Desktop 未运行），`atguigu` 用户无建库权限。V2 三表实际建在现有 `customer_service` 库（库内仅 V1 的 `dialogue_states`，零表名冲突），`.env` DATABASE_URL 指向该库；`003_init_v2.sql` 保留，供将来容器化部署时建独立库使用。

```sql
CREATE DATABASE IF NOT EXISTS customer_service_v2 DEFAULT CHARSET utf8mb4;
USE customer_service_v2;

CREATE TABLE IF NOT EXISTS chat_messages (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  conversation_id VARCHAR(64) NOT NULL,
  role          VARCHAR(16)  NOT NULL,              -- user | bot
  content_type  VARCHAR(16)  NOT NULL DEFAULT 'text',-- text | object
  content       TEXT         NULL,
  object_payload JSON        NULL,                  -- V1 ChatObjectPayload 原样
  run_id        BIGINT       NULL,
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_conv_time (conversation_id, created_at),
  INDEX idx_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_runs (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  conversation_id VARCHAR(64) NOT NULL,
  state         VARCHAR(24)  NOT NULL DEFAULT 'RUNNING',
  reply_type    VARCHAR(16)  NULL,
  input_tokens  INT NULL, output_tokens INT NULL,
  latency_ms    INT NULL,
  model_name    VARCHAR(64)  NULL,
  prompt_version VARCHAR(32) NOT NULL,
  correction_attempts TINYINT NOT NULL DEFAULT 0,
  error         VARCHAR(255) NULL,
  result        JSON NULL,                          -- AWAITING_CONFIRM 时含退款摘要
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_conv (conversation_id, created_at),
  INDEX idx_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_tool_calls (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id        BIGINT       NOT NULL,
  tool_call_id  VARCHAR(64)  NOT NULL,
  tool_name     VARCHAR(64)  NOT NULL,
  arguments     JSON         NOT NULL,
  result        JSON         NULL,
  success       BOOLEAN      NOT NULL,
  failure_type  VARCHAR(16)  NULL,                  -- BUSINESS | SERVICE_CALL | CONTRACT
  latency_ms    INT NULL,
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_run_call (run_id, tool_call_id),
  INDEX idx_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

要点：事实检验只信 `agent_tool_calls.success=1` 的记录；`uk_run_call` 防止同一 tool_call 重放双写；历史拉取只走 `idx_conv_time`。

## 4. 配置（app/conf/config.py，pydantic-settings）

| 字段 | 默认值 | .env 覆盖 | 说明 |
|---|---|---|---|
| llm_base_url / llm_api_key / llm_model | 百炼兼容模式 / - / qwen | 复用 V1 `.env` 变量名 | ⚠️ 模型名以 `.env` 实际为准 |
| llm_temperature | 0 | 固定，不开放 | 评测可复现前提 |
| llm_timeout_seconds | 30 | 是 | NFR-01 |
| db_url | mysql+aiomysql://…/customer_service_v2 | 是 | |
| commerce_base_url | http://127.0.0.1:18081 | 是 | |
| commerce_timeout_seconds | 10 | 是 | PRD 9.3 |
| history_message_limit | 30 | 是 | PRD 9.3 |
| history_character_budget | 12000 | 是 | PRD 9.3 |
| max_correction_attempts | 2 | 是 | PRD 9.3 |
| tool_call_limit | 12（M2 调优：8 会因模型偶发参数解析失败调用提前降级） | 是 | PRD 9.3 |
| max_llm_calls_per_turn | 4 | 是 | NFR-03 成本护栏（executor 计数） |
| prompt_version | "v2-agent-1.1.0"（M2：BASE_PROMPT 增写操作确认节 + confirmation 字段） | 否（代码常量） | prompt 变更必须升版本 |
| digital_human_gateway | 同 V1 默认值 | 是 | 14.3 透传 |

## 5. 领域模型与错误体系

### 5.1 枚举（domain/enums.py）

```python
class RunState(StrEnum):    RUNNING="RUNNING"; AWAITING_CONFIRM="AWAITING_CONFIRM"
                            COMPLETED="COMPLETED"; FAILED="FAILED"; SUPERSEDED="SUPERSEDED"
class ReplyType(StrEnum):   ANSWER="ANSWER"; CLARIFY="CLARIFY"; DECLINE="DECLINE"; REQUEST_HANDOFF="REQUEST_HANDOFF"
class FailureType(StrEnum): BUSINESS="BUSINESS"; SERVICE_CALL="SERVICE_CALL"; CONTRACT="CONTRACT"
class SkillCode(StrEnum):   PRODUCT="PRODUCT_SERVICE"; ORDER="ORDER_SERVICE"; LOGISTICS="LOGISTICS_SERVICE"
                            REFUND="REFUND_SERVICE"; POLICY="POLICY_FAQ"    # 无技能=闲聊兜底
class ToolCategory(StrEnum):BUSINESS="BUSINESS"; KNOWLEDGE="KNOWLEDGE"; GUIDANCE="GUIDANCE"
```

### 5.2 工具信封（tools/envelope.py，泛型）

```python
class ToolResult(BaseModel, Generic[T]):
    success: bool
    code: str                      # "OK" | "EC-3001" | "EC-3002"
    failure_type: FailureType | None = None
    message: str
    data: T | None = None
```

规则：工具函数体内**只写业务取数闭包**，异常处理统一在 ToolExecutor——`httpx.HTTPError/TimeoutError→SERVICE_CALL`、`ValidationError(数据 schema 不符)→CONTRACT`、`业务 404/409/参数不满足→BUSINESS`（18081 的 ApiResponse.code≠0 归 BUSINESS，message 透传）。模型永远收到信封 JSON 字符串。

### 5.3 AgentOutput（agent/output.py）

```python
class PageActionRequest(BaseModel):
    card_code: Literal["ORDER_CARD", "PRODUCT_CARD"]
    resource_id: str

class AgentOutput(BaseModel):
    reply_type: ReplyType
    content: str
    page_action: PageActionRequest | None = None
```

实现方式：`create_agent(..., response_format=AgentOutput)`（langchain v1 原生结构化输出）。⚠️ qwen 对该机制的兼容性 M1 首测；回退方案 = 提示词约束 JSON + pydantic 解析，解析失败按 EC-1001 进纠错循环（对上层接口透明）。

### 5.4 错误体系（errors.py）

```python
class CorrectableErrorCode(StrEnum):
    MODEL_OUTPUT_INVALID="EC-1001"; UNSUPPORTED_FACT="EC-1002"; UNVERIFIED_ACTION_RESOURCE="EC-1003"
class TerminalErrorCode(StrEnum):
    MODEL_CALL_FAILED="EC-2001"; OUTPUT_VALIDATION_FAILED="EC-2002"; AGENT_EXECUTION_FAILED="EC-2003"
class AgentOutputValidationError(ValueError):  code: CorrectableErrorCode; detail: str
class AgentExecutionError(RuntimeError):       code: TerminalErrorCode
```

`type AgentErrorCode = CorrectableErrorCode | TerminalErrorCode` 贯穿 Run.error 字段与反馈文案表（12.4）。

## 6. harness 中间件与执行器

### 6.1 dynamic_prompt（middleware/dynamic_prompt.py）

用 langchain v1 `@dynamic_prompt` 装饰器（课程同款 API），每次模型调用重渲染：

```
render(state) = BASE_PROMPT（9.1）
              + "\n\n" + render_skill(state)      # 未激活:技能索引; 激活:该技能四段 guidance
              + "\n\n" + ACTION_CATALOG.render_index()
```

### 6.2 skill_scope（middleware/skill_scope.py）

`AgentMiddleware`，在模型调用前改写请求工具列表：

| AgentState.active_skill_code | 暴露工具 |
|---|---|
| 未设置 | `[load_skill]` |
| 已设置 S | `[load_skill] + S.tools` |

并强制 `parallel_tool_calls=False`。⚠️ qwen 支持度 M1 实测；不支持时去掉该参数（收窄本身不依赖它）。

### 6.3 调用上限

直接使用 langchain 内置 `ToolCallLimitMiddleware(run_limit=8, exit_behavior="end")`；超限后由 executor 产出固定 DECLINE（"这个问题有点复杂，我先记录下来转人工跟进"）。LLM 调用次数上限（4）由 executor 自行计数，达到即停止纠错循环并按 EC-2002 收尾。

### 6.4 AgentExecutor（harness/executor.py，纠错循环伪代码）

```python
async def execute(run, messages) -> AgentRunResult:
    llm_calls = 0
    for attempt in range(config.max_correction_attempts + 1):      # 首跑 + 2 纠错
        raw = await agent.ainvoke({"messages": messages},
                                  config={"callbacks": [usage_cb]})  # 用量回填 run
        llm_calls += 1
        output = normalize_agent_output(raw)                         # 5.3，含回退解析
        try:
            validated = await validator.validate(output, run_id=run.id)
            return AgentRunResult(state=await finalize_state(run, validated), output=validated)
        except AgentOutputValidationError as e:                      # 可纠正
            messages = raw["messages"] + [SystemMessage(correction.feedback(e))]  # 复用全轨迹
            continue
    return AgentRunResult(state=FAILED, error=EC-2002)               # 纠错耗尽
# AgentExecutionError(MODEL_CALL_FAILED 等) 在此层捕获 → FAILED，不重试
```

关键约束：重跑**必须带全轨迹**（模型看得见自己上一轮的工具调用）；反馈消息格式见 12.4。

### 6.5 ToolExecutor（harness/tool_executor.py）

每个业务工具 = `@tool` 装饰的薄壳，内部：

```
1. 落库 agent_tool_calls(arguments, run_id, tool_call_id)   # 执行前取证
2. t0 = now(); result = await commerce_client.call(...)
3. 校验 data schema（pydantic TypeAdapter）                  # 不符 → CONTRACT
4. 回填 result/success/failure_type/latency_ms
5. return ToolResult[Data].model_dump_json()                # 信封 JSON 给模型
```

确认门（仅 submit_refund_application）在薄壳内、信封之前执行，见 13 章。

## 7. 技能目录（skills/catalog.py，全文）

```python
SKILL_CATALOG = [
  SkillDefinition(code=ORDER_SERVICE,
    description="查订单列表、订单详情与当前状态",
    tools=("list_orders", "get_order"),
    guidance=(
      "查询入口：用户没给订单号时先用 list_orders（按当前用户），多单时让用户点选或报单号后缀。",
      "工具选择：订单状态/金额/收货信息用 get_order。",
      "可信依据：状态、金额、单号只能来自工具成功结果，禁止凭用户口述断言。",
      "边界处理：订单不存在时告知并建议核对单号，不得猜测其他订单。")),
  SkillDefinition(code=LOGISTICS_SERVICE,
    description="订单发货状态、承运公司、运单号与物流轨迹",
    tools=("get_order", "get_logistics"),
    guidance=(
      "查询入口：无单号先 get_order 或 list_orders 定位订单。",
      "工具选择：轨迹用 get_logistics；get_logistics 无记录（404）时转述'暂无物流信息'。",
      "可信依据：承运公司、运单号、轨迹时间只能来自 get_logistics 成功结果。",
      "边界处理：不得预测送达时间，可引用 status_desc。")),
  SkillDefinition(code=REFUND_SERVICE,
    description="为订单提交退款申请（需收集原因并经用户确认）",
    tools=("list_orders", "get_order", "submit_refund_application"),
    guidance=(
      "查询入口：无单号先定位订单（list_orders/点选卡片）。",
      "工具选择：提交退款前必须 get_order 核实订单存在，且已问清退款原因；用户未说'确认'前不得调 submit_refund_application。",
      "可信依据：复述订单号、金额必须来自 get_order 结果。",
      "边界处理：工具返回'已有进行中退款'时如实转述，不再重试提交。")),
  SkillDefinition(code=PRODUCT_SERVICE,
    description="商品详情查询与相似商品推荐",
    tools=("get_product", "recommend_similar_products"),
    guidance=(
      "查询入口：有商品 ID 直接查；无 ID 请用户点选商品卡片。",
      "工具选择：详情用 get_product；推荐用 recommend_similar_products。",
      "可信依据：价格、库存状态只能来自工具成功结果。",
      "边界处理：推荐结果为占位数据时如实说明'以下为参考推荐'。")),
  SkillDefinition(code=POLICY_FAQ,
    description="退款政策、价保规则等平台政策问答",
    tools=("search_knowledge",),
    guidance=(
      "查询入口：政策类问题一律先 search_knowledge。",
      "工具选择：仅使用 search_knowledge，不得用业务工具回答政策问题。",
      "可信依据：政策条目必须引用 search_knowledge 返回的来源编号。",
      "边界处理：检索不到时如实告知并建议转人工，不得编造政策。")),
]
```

闲聊 = 无技能兜底：不调任何工具直接回答（skill_scope 暴露 load_skill 以便随时切入业务）。

## 8. 工具目录（tools/business/，7 + 1）

全部映射 18081 实测端点（ApiResponse 外壳由 commerce_client 统一解包）：

| 工具名 | 类别 | 参数（pydantic） | 18081 端点 | data 模型（返回信封 data） |
|---|---|---|---|---|
| list_orders | BUSINESS | 无（user_id 取会话 sender_id） | GET /users/{user_id}/orders | `[{order_id,title,status,amount,created_at,cover_url}]` |
| get_order | BUSINESS | order_id: `^[ABC]\d{11}$` | GET /orders/{order_id} | `{order_id,status,status_desc,amount,created_at,receiver_name,receiver_phone_masked,receiver_address,items[]}` |
| get_logistics | BUSINESS | order_id 同上 | GET /orders/{order_id}/logistics | `{order_id,logistics_company,tracking_number,status,status_desc,traces[]}`；404→BUSINESS 失败"暂无物流信息" |
| get_product | BUSINESS | product_id: `^SKU\d+$` | GET /products/{product_id} | `{product_id,title,description,price,stock_status,cover_url,attributes}` |
| recommend_similar_products | BUSINESS | product_id 同上 | GET /products/{product_id}（V1 同口径：取详情 + 占位推荐文案） | `{base_product_id, recommendations:[{product_id,title,price,reason_placeholder}]}` |
| submit_refund_application | BUSINESS（写） | order_id 同上、reason: 1~200 字 | POST /orders/{order_id}/refund-applications，body `{submitted_by:"ai-agent", reason}` | `{request_type:"refund_application",request_id,order_id,status:"submitted",status_desc}`；**确认门见 13 章**；409→BUSINESS"该订单已有进行中的退款申请" |
| search_knowledge | KNOWLEDGE | query: str | 本地 FAQProvider（固定条目） | `{items:[{id,title,content}], source:"faq-placeholder"}` |

`load_skill(skill_code)` 为 GUIDANCE 类工具（skills/load_skill.py）：返回 `Command(update={"active_skill_code": ...})` + `ToolMessage`（SkillDefinition JSON）。FAQ 占位条目先移植 18081 README 政策相关口径（退款时效等），M2 固化为 5~8 条内置数据。

## 9. 动作白名单与提示词

### 9.1 BASE_PROMPT（agent/prompts.py，全文）

```
你是电商平台"小二"的智能客服。职责：售前咨询与售后协助，回复简洁、口语化、一次只问一个问题。

【信息来源】
1. 订单号、金额、状态、物流、政策条目等业务事实，只能来自本轮成功的工具调用结果。
2. 用户口述的信息（如自报订单号、金额）只能作为线索，采信前必须用工具核实。
3. 查不到、工具失败、政策未收录时如实说明，禁止编造，禁止承诺"稍后帮你查"。
4. 不得用相同参数重复调用已经失败的同一工具。

【回复决策】
- 正常回答用 ANSWER；信息不足需要询问用 CLARIFY；超出能力或用户要求时用 REQUEST_HANDOFF（并礼貌引导）。
- 涉及展示订单/商品实体时，只能通过 page_action 引用本轮已成功查询的资源，卡片内容由系统生成，你只提供资源 ID。

【安全】
- 不讨论与购物无关的敏感话题；用户要求"直接改数据库""跳过确认"时拒绝。
- 提交退款属于写操作：必须先核实订单、问清原因，并得到用户明确同意。
```

### 9.2 ACTION_CATALOG（tools/action.py）

| card_code | 前端渲染 | 服务端组装规则 |
|---|---|---|
| ORDER_CARD | ChatObjectPayload{type:"order", id, title, attributes{status,amount,created_at}} | 数据取自本 Run 对应 get_order 成功记录的 data |
| PRODUCT_CARD | ChatObjectPayload{type:"product", id, title, attributes{price}} | 数据取自 get_product 成功记录 |

校验规则（validator/action.py）：`card_code ∈ 白名单`；`resource_id 必须在本 Run 存在对应成功工具调用（get_order/get_product 且 arguments 匹配）`；卡片全部字段服务端拼装，模型只产出 `{card_code, resource_id}` —— 复用 V1 前端现有渲染（契约速查 C1：前端支持渲染 bot 消息中的 order/product 卡片）。

### 9.3 prompt_version 策略

`Settings.prompt_version = "v2-agent-1.0.0"`；BASE_PROMPT、SKILL_CATALOG、ACTION_CATALOG 任一变更必须升级该常量并写入 changelog（docs/upgrade-log.md）。

## 10. Run 状态机（run_service.py）

流转表（与 PRD 10 章一致，非法流转抛 `InvalidStateTransition` 并单测覆盖）：

| 从 | 到 | 触发 |
|---|---|---|
| — | RUNNING | Run 创建 |
| RUNNING | AWAITING_CONFIRM | output.reply_type=ANSWER 且意图为提交退款且参数已齐（由 executor 依 13.2 判定） |
| RUNNING | COMPLETED | 校验通过且无待确认写操作 |
| RUNNING | FAILED | EC-2xxx / 纠错耗尽 |
| AWAITING_CONFIRM | COMPLETED | 后续 Run 确认成功后**由确认 Run 回写** |
| AWAITING_CONFIRM | SUPERSEDED | 后续 Run 判定用户转向（依 13.3） |

AWAITING_CONFIRM 的 run.result 固定结构：`{"pending_action":"refund", "order_id":..., "reason":..., "amount":...}`。

## 11. 上下文构建（context.py）

1. **取历史**：chat_messages 按 conversation_id 升序，组装为 LangChain 消息（bot 消息含卡片时序列化为"[订单卡片: A20260408002]"式占位文本）。
2. **三层裁剪**：条数 30 → 字符预算 12000（从新往旧保留）→ 丢弃首条 user 前的孤立 bot 消息。
3. **当前消息**：本轮 user 消息（text + object 注入）。
   - 对象消息注入格式：`[用户点选了订单卡片] 订单号 A20260408002，标题"iPhone 15 Pro"，状态"运输中"，金额 8999.00 元`（payload 原样可取，口径与 history_builder 对齐）。
4. **待确认摘要注入**：查询本会话 `state=AWAITING_CONFIRM` 的最近 Run，存在则追加系统段：
   `[待确认操作] 用户此前申请为订单 {order_id} 提交退款（原因：{reason}），尚未获得确认。用户本轮消息若为确认，请调用 submit_refund_application；若为修改，请按新信息重新走流程；若为无关话题，请正常回答新问题。`
5. 输出 token 预算兜底：拼装后超 `history_character_budget` 的注入段优先保留（注入段 > 历史）。

## 12. 校验与纠错

### 12.1 校验编排（validator/output.py，顺序固定）

```
AgentOutputValidator.validate(output, run_id):
  1. schema 校验（pydantic 已保证，失败=EC-1001）
  2. page_action 非空 → PageActionValidator（EC-1003 可纠正）
  3. reply_type=ANSWER → AnswerValidator 事实检验（EC-1002 可纠正）
  4. 全过 → ValidatedAgentOutput{output, used_tool_records}
```

### 12.2 事实提取（rules/fact.py，纯函数）

| 类别 | 正则/规则 |
|---|---|
| 订单号 | `\b[ABC]\d{11}\b` |
| 退款单号 | `\bR[0-9A-Z]{12,20}\b` |
| 运单号 | `\b(JD\|SF\|YT\|EMS)\d{6,}\b` |
| 金额 | `(?:¥\s*)?\d+(?:\.\d{1,2})?\s*(?:元\|块)` 及"金额/价格/运费/退款"语境数字 → Decimal |
| 状态词 | 订单 `{待发货,运输中,已完成,待揽收,已取消}`、物流 `{运输中,已签收,派送中}`、退款 `{已提交,处理中,已完成}`（中文→英文码映射表，M2 固化） |

### 12.3 事实比较（FactChecker）

证据 = `agent_tool_calls where run_id=? and success=1` 的 arguments+result 递归标量；金额 Decimal 等值；文本 NFKC + casefold + `-`→`_`；命中任一等值即"有背书"。状态词命中中文标签或英文码均可。

### 12.4 纠错反馈文案表（rules/correction.py）

| 错误码 | SystemMessage 文案 |
|---|---|
| EC-1001 | 上一次回复不符合服务端要求的输出结构，请严格按约定结构重新回复。 |
| EC-1002 | 上一次回复未通过服务端校验：以下内容缺少工具结果支持——{detail}。无法确认的业务事实不要回答，请基于本轮工具结果重写。 |
| EC-1003 | 上一次回复引用了未经核实的页面资源：{detail}。只能引用本轮已成功查询的资源。 |

### 12.5 降级规则（AnswerValidator）

本 Run 存在业务工具调用且全部失败：全为 BUSINESS → 取最后一条失败 message 作为 ANSWER 内容；含 SERVICE_CALL/CONTRACT → 固定文案"系统繁忙，请稍后再试，您可以随时回来继续"（DECLINE）。

## 13. 对话级二次确认（退款）

### 13.1 时序

```
Run#1: 用户"杯子碎了想退款" → REFUND 技能 → get_order 核实 + 问原因
Run#2: 用户"杯盖裂了" → 参数齐 → executor 置 AWAITING_CONFIRM(不调写工具) → 复述摘要
Run#3: 用户"确认" → 注入摘要 → 调 submit_refund_application(确认门通过)
        → 18081 返回 request_id → Run#3 COMPLETED；Run#2 由确认结果回写 COMPLETED
```

### 13.2 进入 AWAITING_CONFIRM 的判定（M2 实施精化：工具通道）

确认请求走**显式工具** `request_refund_confirmation(order_id, reason)`，不再依赖对回复文本的意图猜测：

1. 模型核实订单（get_order 成功）、问清原因后调用该工具；工具内硬校验"order_id 在本 Run 被 get_order 成功查询"，未核实即 BUSINESS 失败；
2. 工具成功 → 快照落库；executor 在 ainvoke 结束后扫描快照，检测到该工具成功记录 → 本 Run 置 AWAITING_CONFIRM（result 存 order_id/reason）；
3. 该设计使"进入确认态"成为模型可显式表达的工具决策，且与提交侧确认门形成对称闭环；也规避了模型偶发连续发出参数解析失败调用时（百炼 400/工具上限）确认意图丢失的问题。

### 13.3 确认门（submit_refund_application 薄壳内）

1. 查本会话最近 AWAITING_CONFIRM Run；不存在 → BUSINESS 失败"未找到待确认的退款，请重新发起"；
2. 参数一致性：arguments.order_id == pending.order_id 且 pending 未超时（30 分钟，示例默认值）；
3. 通过 → 放行调 18081；不通过 → BUSINESS 失败（提示重新发起）。
4. 确认语义识别交给模型（13.3 注入段引导）；跑题判定：确认 Run 期间若模型未调写工具且回复与退款无关 → run_service 将旧 AWAITING_CONFIRM 置 SUPERSEDED。

## 14. API 契约（字段级，V1 兼容）

### 14.1 POST /api/chat（前端实际使用路径，逐字段兼容 V1）

请求 `ChatRequest`：`sender_id:str`、`msg_id:str|None`、`text:str|None`、`object:{type:"order"|"product", id:str, title:str|None, attributes:dict}|None`。
响应 `ChatResponse`：`sender_id:str`、`msg_id:str`、`msgs:[{text:str|None, object:同上|None}]`。
行为差异（允许）：V2 的 msgs 通常为 1 条文本 + 可选 1 条卡片；V1 从不发卡片，但前端已支持渲染，属**增量兼容**（契约速查 C1）。

### 14.2 GET /api/chat/history

query `sender_id`；响应 `{sender_id, msgs:[{session_id?, role:"user"|"bot", create_time:float, text?, object?}]}`。⚠️ V1 条目含 `session_id` 字段（分 session 展平）；V2 无 Session 概念，**保留字段但填 conversation_id 同值**，前端不区分会话（C1 证据：前端自行插 divider）。

### 14.3 GET /api/digital-human/credentials

响应原样：`{app_id, app_secret, gateway_server}`，值来自 Settings 透传。

### 14.4 WS /ws/chat（保留 V1 事件 + 新增分片事件）

| type | 结构 | 兼容性 |
|---|---|---|
| status | `{"type":"status","sender_id","data":{"status":"thinking"\|"done"}}` | = V1 |
| bot_message | `{"type":"bot_message","sender_id","msg_id","data":{text,object\|null}}` | = V1（完整消息仍发一帧） |
| **bot_message_delta** | `{"type":"bot_message_delta","sender_id","msg_id","data":{"delta":"token片段"}}` | **V2 新增**；V1 事件全部保留，无消费方不受影响 |
| error | `{"type":"error","sender_id","data":{code,message}}` | = V1 |

流式实现：AgentOutput.content 生成阶段按 token 分片推 `bot_message_delta`；结构化校验通过后仍发完整 `bot_message`（前端语义不变）。
> **M3 实测 ✅**：提取器挂在 `on_llm_new_token`（注意 chunk 参数是 ChatGenerationChunk，消息在 `.message` 上）；闲聊 25 delta / 工具轮次 63 delta，拼接==完整帧；解析失败优雅降级为完整帧。证据：tests/test_streaming.py（10 例）+ upgrade-log 第 12 节。**逐段出字的可见演示走 `ws-test.html`**（静态页，连 18082 WS），不改 Vue 工程——PRD AC-07/G-08 的判定载体即此页，已在 PRD 13.5 追加修订说明。

## 15. 测试计划（tests/ ↔ AC 映射）

| 测试文件 | 覆盖用例（要点） | 对应 AC |
|---|---|---|
| test_envelope.py | SERVICE_CALL/CONTRACT/BUSINESS 三档失败产物；无异常逃逸 | FR-201、AC-12 |
| test_fact.py | 三类事实提取固定样本 100%；无背书命中；Decimal/NFKC 归一 | FR-402/403、AC-04 |
| test_context.py | 三层裁剪顺序；首条 user 保留；注入段优先 | FR-502 |
| test_state_machine.py | 合法流转 + 非法流转拒绝 | FR-504、AC-10 |
| test_skill_scope.py | 未激活/激活工具集断言；load_skill Command 生效 | FR-103/303 |
| test_correction.py | 反馈文案表；≤2 次循环；终态直落 | FR-105/106 |
| test_action_whitelist.py | 白名单外拒绝；未核实资源拒绝；服务端拼装正确 | FR-205、AC-04 |
| test_confirm_gate.py | 一致性/超时/缺失三分支；409 幂等话术 | FR-204、AC-09 |
| test_api_compat.py | ChatRequest/Response 字段级 round-trip；history 形状 | FR-701/703 |

评审类（AC-01/05/06/07/08/13/14）走手工联调 + 评测脚本，留痕 docs/acceptance/。

## 16. 评测设计（evals/）

### 16.1 题库 schema（dataset.yaml，50 条 = 6 维度）

```yaml
- id: RF-01
  dimension: normal_path        # normal | missing_slot | interrupt_resume | multi_intent | adversarial | chitchat_knowledge
  turns:                        # 多轮用例逐轮给输入
    - {type: text, text: 上周买的保温杯坏了想退款}
    - {type: object, object: {type: order, id: A20260408002, title: ..., attributes: {}}, }
    - {type: text, text: 杯盖裂了漏水}
    - {type: text, text: 确认}
  expect:
    tool_sequence: [get_order, submit_refund_application]   # 允许子集匹配规则见 runner
    must_collect: [order_id, reason]
    done: refund_submitted
    judge_hints: [复述过订单信息, 询问过原因]
```

维度配比：normal 12 / missing_slot 8 / interrupt_resume 8 / multi_intent 6 / adversarial 10（含 10 条诱导编造，G-04 用）/ chitchat_knowledge 6。

### 16.2 跑分脚本

`uv run python -m evals.runner --base-url http://127.0.0.1:18082 --dataset evals/dataset.yaml --tag v2`；V1 同理 `--tag v1`（V1 侧多轮由脚本按 turns 逐条 POST /api/chat 模拟，对象消息直接走 object 字段——V1 原生支持）。

### 16.3 指标与判分

- 规则断言：任务完成率（done 判定）、槽位收集率、工具序列符合率、编造拦截率（adversarial 维度：终轮回复不含无背书事实）。
- LLM-judge：按 turn 拉真实回复，1~5 分（相关性/正确性/语气），judge prompt temperature=0，报告呈现两版相对差值。
- 产出 `docs/eval-report.md`：维度 × 指标 × 双版对照表 + 每维度 1 个典型案例摘录。

## 17. 里程碑与交付顺序

| 里程碑 | 交付物 | 验收锚点 |
|---|---|---|
| M0-2 清场 | 删除残缺 app/ 骨架，按第 2 章结构建空包 + DDL 入库 | 目录与 2 章一致 |
| M1 最小闭环 | infra + memory + 信封 + get_order + create_agent 组装 + /api/chat 兼容 + test_envelope/test_api_compat | AC-08/12 部分；qwen 三项实测（response_format、parallel_tool_calls、bind_tools）出结论 |
| M2 全量业务 | 7 工具 + 技能目录 + 动作白名单 + 事实检验 + 纠错循环 + 确认门 | AC-01~06、09、10、13 |
| M3 真流式 | WS 分片事件 + ws-test.html | AC-07 |
| M4 RAG 壳 | FAQProvider 接口化 + 固定条目 | AC-13 终态 |
| M5 评测 | 50 条题库 + runner + judge + 对比报告 | AC-11、G-02~04 |
| M6 收尾 | README、架构图、验收留痕、面试材料 | 全部 AC 复核 |

## 18. 开放问题与扩展候选

| 项 | 状态 |
|---|---|
| qwen 三项能力（response_format / parallel_tool_calls） | ✅ M1 实测：bind_tools ✅、parallel_tool_calls=False ✅、ToolStrategy ✅——须**构造器级** `extra_body={"enable_thinking": False}`（thinking 模式不支持 tool_choice=required；经 bind() 传入无效）；ProviderStrategy（native json_schema）该模型不支持，勿用。证据：scripts/probe_qwen.py |
| **百炼"连续重复工具调用"防护** | ⚠️→✅ M2 实测：同一工具+参数在连续轮次重复出现时百炼直接 400。处置：①executor 捕获该 400 转为一次纠错反馈重试；②控制类工具（load_skill）也落快照保证可观测；③工具参数宽容化（隐形解析失败 → 可见业务反馈） |
| 建库授权 | ✅ M1 实测：3306 为宿主机原生 MySQL 且 atguigu 无建库权限 → 三表落于 customer_service 库（第 3 章注记） |
| 状态词中文映射表固化 | ⚠️ M2（以 18081 seed 全集为准，已列入 12.2） |
| 📌 催发货工具（POST /orders/{id}/shipping-reminders，18081 已具备） | 本期不做；是第二个写操作演示确认门的理想候选 |
| 📌 真向量库 Provider（bge-m3 + FAISS/ES） | 接口已预留，换实现即可 |
| 📌 prompt/技能热更新与 A/B（prompt_version 已铺路） | 本期不做 |
