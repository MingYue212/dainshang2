# Harness 学习路线（从"没学过"到"面试能守住"）

> 目标：把 dainshang2（已建成的 harness 版）从"AI 帮我写的项目"变成"我能逐层讲清、扛住追问的项目"。
> 核心方法：**不需要从零学理论再重建——以自己的代码为教材，用课件判据理解每个设计，用 M5 实战补最后一块，用模拟面试钉牢。**
> 预估总投入：5~7 个碎片日。

---

## 阶段 0 · 认知校准（半天）

**目的**：先把"我有一个 harness 项目"这个事实立住，建立判据坐标系。

1. 通读 `../course-v2/4_other/Harness_Engineering概念与原理/Harness_Engineering概念与原理.md`（约 40 分钟），只要求记住课件的五个记忆点：
   - 一个公式：`Agent = Model + Harness`
   - 八类故障：循环失控 / Context 溢出 / Cache Miss / 工具错误吞 / 状态丢失 / 缺权限闸 / 缺自动评审 / 成本失控
   - 八大机制：Loop / Tool Use / Progress / Context / Feature List / Verification / Subagents / Generator–Evaluator
   - 三个维度：Agent 能看见什么、能做什么、能跑多久
   - 一种工程理性：从真实失败出发，保持简单，准备删除
2. 读 `docs/upgrade-log.md` 第 11、12 节（M2/M3 实施记录）——这是"八大故障在我们项目里的真实版本"。
3. 读 `interview-qa.md` 第 10、11 节（升级介绍短开场 + Agent/Harness 判据）。

**自测（说得出就过关）**：
- Workflow 和 Agent 的分界线是什么？（执行路径谁决定）
- 为什么说 V1 是 Workflow、V2 是 Agent？
- 课件五问，我们的项目各对应什么机制？

---

## 阶段 1 · 以自己的代码为教材（2~3 天）

**方法**：按依赖顺序精读 6 个模块。每读完一个模块，合上代码回答三个问题：**它防哪个故障？为什么这么设计？不做会怎样？**（答案都在课件对应小节 + upgrade-log 实战记录里）

| 序 | 模块 | 对应课件 | 自测三问要点 |
|---|---|---|---|
| 1 | `app/tools/envelope.py` + `app/harness/tool_executor.py` | 5.2 Tool Use | 防什么：工具错误吞。为什么三档失败类型？为什么永不向模型抛异常？ |
| 2 | `app/harness/context.py` | 5.4 Context Management | 防什么：Context 溢出。三层裁剪顺序为什么是这样？待确认摘要为什么注进 SystemMessage？ |
| 3 | `app/harness/executor.py` | 5.1 Agent Loop + 5.6 Verification Loop | 防什么：循环失控+缺自动评审。纠错为什么复用全轨迹？为什么最多 2 次？ |
| 4 | `app/rules/fact.py` + `app/validator/` | 5.8 Generator–Evaluator | 防什么：自评偏差。证据为什么来自快照而不是模型自述？三类事实为什么是编号/金额/状态？ |
| 5 | `app/skills/` + `app/harness/middleware/` | Context Engineering（6.1） | 防什么：选错工具+token 浪费。收窄为什么比全量注入好？ |
| 6 | `app/agent/factory.py` | 全景组装 | 能画出一次请求的完整链路图（照 SPEC 1.2 默写） |

**辅助材料（可选，不必通读视频）**：
- `../course-v2/2_resource/day10_生产级Agent_Harness校验与异常治理.md`、`day11_生产级Harness全链路打通.md`——课程对同一问题的讲法，对照你的实现找差异
- `../course-v2/2_resource/Customer Service 项目总结与面试指南.md`——课程自己的面试口径

**过关标准**：任意指一个文件，你能说出"它挡住了八大故障里的哪一个、生产环境对应哪次真实事故"（upgrade-log 里全有：百炼重复调用 400、隐形调用、5000 元幻觉拦截）。

---

## 阶段 2 · 补 M5 评测实战（2~3 天，边做边学）

评测是学习"Harness 判断标准"最好的方式——**写题库的过程就是把八大故障翻译成具体测试用例的过程**：

1. 写 50 条六维题库（写"打断恢复"维度时，你会真正理解状态为什么外置）
2. 写跑分脚本（HTTP 黑盒，V1/V2 同题对比）
3. 写 LLM-judge
4. 产出对比报告 → 更新进 README 和简历

这一步做完，简历上"量化证明升级效果"落地，你对 harness 的理解也从"机制"上升到"度量"。

---

## 阶段 3 · 面试陪练（持续，随时开始）

- 我扮演面试官，按 interview-qa.md 第 10 节的追问树追问，逐步加深度（先问是什么，再问为什么，最后问"如果不用会怎样"）
- 每轮陪练后标出答不上/答虚的点，回炉对应模块
- 目标状态：追问树三层深以内，每层都有"我的项目里的具体例子"兜底

---

## 不用做的事（防焦虑）

- ❌ 不用通读 day01~06 视频（那是 V1 生产化重制，我们明确砍掉的方向）
- ❌ 不用去看 Claude Code/Cursor 的源码（课件说清了原理，你的项目就是最小实现）
- ❌ 不用学 LangGraph 深层 API（循环骨架是框架的事，你自研的校验层才是考点）
- ❌ 不用等"学完"再面试——阶段 1 过关就敢讲，讲漏的回炉即可
