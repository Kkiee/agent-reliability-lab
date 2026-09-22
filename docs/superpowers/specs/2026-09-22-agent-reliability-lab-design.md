# Agent Reliability Lab 设计规格

**状态：** 待用户审核  
**日期：** 2026-09-22  
**项目负责人：** Kkiee  
**目标仓库：** `Kkiee/agent-reliability-lab`  
**计划版本：** `v0.1.0`

## 1. 背景与目标

### 1.1 问题

工具调用 Agent 已经可以完成搜索、计算、数据读取和外部操作，但在真实工程中常见问题没有被系统解决：

- 工具超时、限流或返回脏数据时，Agent 可能直接失败或重复调用。
- 外部内容可能包含提示词注入，诱导 Agent 执行越权工具。
- Agent 执行过程缺少可验证记录，出现问题后难以复盘。
- 相同输入在不同时间执行时，模型输出和工具结果可能不同，无法稳定复现。
- 没有统一指标衡量成功率、恢复率、循环率、违规率和成本。

### 1.2 项目定位

Agent Reliability Lab 是一个面向工具调用 Agent 的可靠性与评测平台。它提供最小 Agent Runtime、事件溯源、确定性回放、故障注入、策略防护、基准场景和评测报告。

项目的核心不是“接入更多模型”，而是验证 Agent 在不确定性、故障和恶意输入下是否仍然安全、可恢复、可复盘。

### 1.3 面试价值

项目能够展示以下工程能力：

- Agent 状态机与工具调用协议
- 事件驱动架构、状态快照和确定性回放
- 声明式策略引擎和副作用控制
- 可重复的故障注入与故障恢复
- 可量化评测、基准测试和 CI 质量门禁
- 面向开源用户的 CLI、文档、版本发布和贡献流程

## 2. 产品范围

### 2.1 MVP 必须包含

1. 框架无关的同步 Agent Runtime。
2. 结构化事件模型和追加式 JSONL 事件日志。
3. `FakeAdapter` 确定性模型适配器。
4. `OpenAICompatibleAdapter`，兼容 Ollama 和 OpenAI-compatible HTTP 接口。
5. 工具注册、工具 schema 校验和可控的模拟工具。
6. 工具白名单、预算、循环检测、副作用审批策略。
7. 超时、异常、脏 JSON、空结果、延迟、提示词注入等故障注入。
8. 从事件日志确定性回放 Run，不重新调用模型或工具。
9. 至少 9 个基准场景和统一评测指标。
10. CLI 运行、回放、列场景、执行基准和生成报告。
11. JSON 与 HTML 评测报告。
12. pytest 测试、Ruff、mypy 和 GitHub Actions。
13. README、架构图、演示流程、设计取舍和版本发布说明。

### 2.2 MVP 不包含

1. 不做 Web 聊天界面。
2. 不做多租户 SaaS。
3. 不做分布式任务队列。
4. 不做自动修改生产系统的高风险工具。
5. 不做模型微调。
6. 不内置任何真实 API Key。
7. 不在 `v0.1.0` 提供 HTTP API 服务。

## 3. 目标用户与核心流程

### 3.1 目标用户

- 需要验证 Agent 故障恢复能力的应用开发者
- 需要复现线上 Agent 轨迹的调试者
- 需要建立 Agent 回归测试集的平台工程师
- 需要评估工具调用安全策略的研究者

### 3.2 核心流程

1. 用户选择基准场景或提供自己的场景 JSON。
2. CLI 启动 Run，并加载工具、策略和故障配置。
3. Runtime 调用模型适配器，接收结构化行动或最终答案。
4. Runtime 将模型行动交给策略引擎和工具执行器。
5. 每一步写入带顺序号的事件日志；事件通过 SHA-256 哈希链关联。
6. 故障注入器按固定种子在指定调用点注入故障。
7. Runtime 根据策略完成、终止或恢复 Run。
8. Evaluator 根据 Run 结果计算指标。
9. Reporter 输出 JSON 和 HTML 报告。
10. 用户通过 Run ID 回放事件，验证状态和事件序列是否一致。

## 4. 成功标准

### 4.1 功能验收

- 不配置 API Key 时，`agentlab demo` 可以完整运行并生成报告。
- 9 个基准场景表现符合预期，不依赖真实网络。
- `agentlab replay <run_id>` 不调用模型和工具。
- 回放后的最终状态哈希和原始 Run 一致。
- 策略可以阻止未授权副作用工具。
- 循环检测、步骤上限和预算上限可以终止 Run。
- 故障注入结果由 `seed` 决定，重复执行结果一致。
- CLI 返回非零退出码时，CI 能正确识别基准失败。

### 4.2 工程验收

- 核心模块测试覆盖率不低于 85%。
- Ruff、mypy、pytest 全部通过。
- GitHub Actions 在 Python 3.11、3.12、3.13 上通过。
- 每次合并到 `main` 后，README 中的 Quick Start 仍然可用。
- `v0.1.0` 发布包含源码包、变更日志和演示报告。
- 仓库历史中不包含 API Key、Token 或个人信息。

## 5. 总体架构

```text
+----------------------+
| CLI / Python API     |
+----------+-----------+
           |
           v
+----------------------+       +---------------------+
| Agent Runtime        |<----->| Policy Engine       |
| - state machine      |       | - budgets           |
| - step loop          |       | - tool allowlist    |
| - action validation  |       | - loop detection    |
+----+------------+----+       +---------------------+
     |            |
     |            v
     |      +----------------------+
     |      | Tool Registry        |
     |      | - schemas            |
     |      | - mock tools         |
     |      | - fault wrappers     |
     |      +----------+-----------+
     |                 |
     v                 v
+----------------+  +----------------------+
| Model Adapter  |  | Chaos Injector       |
| - Fake         |  | - deterministic seed |
| - OpenAI-compat|  +----------+-----------+
+--------+-------+             |
         |                     |
         +----------+----------+
                    v
           +-------------------+
           | Event Store       |
           | - JSONL log       |
           | - snapshots       |
           | - hash chain      |
           +---------+---------+
                     |
          +----------+-----------+
          |                      |
          v                      v
+-------------------+  +------------------+
| Replay Engine     |  | Evaluator        |
+-------------------+  +---------+--------+
                                 |
                                 v
                         +----------------+
                         | Reporter       |
                         | JSON + HTML    |
                         +----------------+
```

## 6. 核心组件

### 6.1 Agent Runtime

职责：

- 维护 Run 状态机。
- 推进模型与工具步骤。
- 校验模型行动格式。
- 调用策略引擎和工具执行器。
- 写入事件并处理恢复、终止和失败。

默认限制：

- `max_steps = 12`
- `max_tool_calls = 8`
- `max_tokens = 6000`
- `repeated_call_limit = 3`

Runtime 状态：

```text
CREATED
  -> RUNNING
  -> WAITING_FOR_MODEL
  -> RUNNING
  -> WAITING_FOR_TOOL
  -> RUNNING
  -> COMPLETED | FAILED | TERMINATED
```

任何状态迁移只能由事件处理函数完成，不能直接修改内存状态。

### 6.2 Model Adapter

统一接口：

```python
class ModelAdapter(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

实现：

- `FakeAdapter`：读取场景中的确定性响应脚本，支持演示和测试。
- `OpenAICompatibleAdapter`：通过 HTTP 调用 Ollama 或兼容 OpenAI Chat Completions 的服务。

`OpenAICompatibleAdapter` 只从环境变量读取配置：

- `AGENTLAB_BASE_URL`
- `AGENTLAB_API_KEY`
- `AGENTLAB_MODEL`

API Key 不写入日志、报告或仓库。

### 6.3 Tool Registry

每个工具包含：

- `name`
- `description`
- `input_schema`
- `output_schema`
- `side_effect`
- `handler`

内置模拟工具：

- `search_docs`
- `fetch_record`
- `calculate`
- `send_message`

工具输入先经过 Pydantic 校验。校验失败产生 `ToolFailed` 事件，不执行 handler。

### 6.4 Policy Engine

策略配置包含：

- `allowed_tools`
- `blocked_tools`
- `max_steps`
- `max_tool_calls`
- `max_tokens`
- `repeated_call_limit`
- `allow_side_effects`
- `approval_required_tools`

策略决策：

- `ALLOW`
- `DENY`
- `TERMINATE`

执行顺序固定为：

1. 步骤与调用次数检查
2. 工具白名单检查
3. 重复调用检查
4. 副作用检查
5. 输入 schema 检查

### 6.5 Event Store

事件日志是 Run 的事实来源。每个 Run 写入：

```text
runs/<run_id>/
  manifest.json
  events.jsonl
  state.json
  report.json
  report.html
```

事件字段：

```json
{
  "event_id": "uuid",
  "run_id": "uuid",
  "seq": 1,
  "type": "RunStarted",
  "timestamp": "2026-09-22T10:00:00Z",
  "payload": {},
  "prev_hash": null,
  "hash": "sha256"
}
```

哈希由规范化 JSON 的 SHA-256 计算。事件写入后不可修改。

事件类型：

- `RunStarted`
- `ModelRequested`
- `ModelResponded`
- `ToolRequested`
- `PolicyEvaluated`
- `ToolStarted`
- `ToolSucceeded`
- `ToolFailed`
- `FaultInjected`
- `RunCompleted`
- `RunFailed`
- `RunTerminated`

### 6.6 Replay Engine

Replay Engine 读取 `events.jsonl`，重新应用事件并构造最终状态。

规则：

- 不调用模型。
- 不调用真实工具。
- 不重新执行故障注入。
- 每个事件都必须按顺序处理。
- 事件哈希链校验失败时立即终止。
- 回放状态哈希必须与原 Run 的状态哈希一致。

### 6.7 Chaos Injector

故障类型：

- `timeout`
- `tool_error`
- `malformed_json`
- `empty_result`
- `extra_latency`
- `duplicate_result`
- `prompt_injection`
- `contradictory_result`

每个故障包含 `probability`、`tool_name`、`call_index` 和 `seed`。默认随机数生成器只依赖 Run `seed`，不依赖系统时间。

### 6.8 Evaluator

指标：

- `task_success`
- `recovery_rate`
- `policy_violation_count`
- `loop_termination_count`
- `average_steps`
- `average_tool_calls`
- `estimated_token_cost`
- `average_latency_ms`
- `replay_fidelity`
- `trace_completeness`

场景通过条件由场景 JSON 中的 `expected` 字段定义，例如：

```json
{
  "expected_status": "completed",
  "expected_recovered": true,
  "max_policy_violations": 0,
  "required_events": ["FaultInjected", "ToolFailed", "ToolSucceeded"]
}
```

### 6.9 Reporter

JSON 报告用于 CI 和二次分析。HTML 报告包含：

- 场景通过率和失败原因
- 每个 Run 的关键指标
- 时间线和工具调用摘要
- 策略拒绝与故障注入记录
- 回放校验结果

HTML 报告是静态文件，不依赖 JavaScript 框架或外部 CDN。

## 7. 数据模型

### 7.1 Run

- `run_id`
- `scenario_name`
- `status`
- `seed`
- `started_at`
- `finished_at`
- `steps`
- `tool_calls`
- `token_usage`
- `final_answer`
- `state_hash`

### 7.2 Scenario

- `name`
- `description`
- `user_input`
- `model_script`
- `tools`
- `policy`
- `faults`
- `expected`

### 7.3 FaultSpec

- `type`
- `tool_name`
- `call_index`
- `probability`
- `message`
- `payload`

### 7.4 EvaluationResult

- `scenario_name`
- `run_id`
- `passed`
- `metrics`
- `failures`
- `report_path`

## 8. 基准场景

`v0.1.0` 固定提供 9 个场景：

1. `happy_path`：搜索、计算并给出答案。
2. `tool_timeout_recovery`：首次工具超时，第二次成功。
3. `malformed_tool_output`：工具返回无效 JSON，Agent 重新调用。
4. `empty_result_fallback`：首选工具返回空结果，Agent 使用备用工具。
5. `loop_detection`：重复调用相同工具，Runtime 在达到阈值后终止。
6. `budget_exhaustion`：Token 或步骤预算耗尽，Run 安全终止。
7. `unauthorized_side_effect`：副作用工具未授权，策略拒绝执行。
8. `prompt_injection`：工具结果包含恶意指令，Agent 不遵循并记录风险。
9. `contradictory_evidence`：两个来源冲突，Agent 返回不确定性而不是编造结论。

## 9. 对外接口

### 9.1 CLI

```bash
agentlab list-scenarios
agentlab run happy_path --seed 42
agentlab run tool_timeout_recovery --adapter fake --out runs
agentlab replay <run_id> --runs-dir runs
agentlab report <run_id> --html --runs-dir runs
agentlab bench scenarios --runs-dir runs --fail-under 0.80
agentlab demo
```

### 9.2 Python API

```python
from agentlab import AgentRuntime, FakeAdapter, PolicyConfig, ToolRegistry

runtime = AgentRuntime(
    adapter=FakeAdapter(script),
    tools=ToolRegistry.default(),
    policy=PolicyConfig.default(),
    runs_dir="runs",
)
result = runtime.run(scenario)
```

公共 API 使用类型标注，并在 `v0.1.0` 后保持向后兼容。

## 10. 技术栈与工程约束

- Python：`>=3.11,<3.15`
- 核心模型：Pydantic 2
- CLI：Typer
- 终端输出：Rich
- 测试：pytest、pytest-cov
- 静态检查：Ruff、mypy
- 报告：Jinja2
- 存储：JSONL + 本地文件系统
- HTTP：httpx
- 构建：Hatchling
- CI：GitHub Actions
- 许可证：MIT

不引入 LangChain、LlamaIndex 或其他 Agent 框架作为核心依赖，以避免黑盒依赖并突出 Runtime、回放和策略实现。

## 11. 测试策略

### 11.1 单元测试

- 状态迁移合法性与非法迁移
- 策略检查顺序与决策结果
- 工具 schema 校验
- 故障注入确定性
- 哈希链计算与校验
- 指标计算边界情况

### 11.2 契约测试

- Model Adapter 协议
- Tool handler 协议
- Event Store 读写协议
- Reporter JSON schema

### 11.3 集成测试

- 9 个场景端到端执行
- Run 到 Replay 的状态一致性
- CLI 成功与失败退出码
- HTML 报告生成

### 11.4 质量门禁

```bash
ruff check .
mypy src
pytest --cov=agentlab --cov-fail-under=85
agentlab bench scenarios --fail-under 0.80
```

CI 必须执行以上命令，并阻止失败代码合并到 `main`。

## 12. GitHub 一周交付计划

不做空提交，不伪造贡献记录；每天都保持 `main` 可运行。

| 阶段 | 分支 | 主要交付 | 验收 |
| --- | --- | --- | --- |
| Day 0 | `main` | 项目设计规格 | 规格提交并审核通过 |
| Day 1 | `day-1-runtime` | 包结构、领域模型、事件模型、最小 Runtime | Runtime 单元测试通过 |
| Day 2 | `day-2-tools-policy` | 工具注册、模拟工具、Policy Engine | 越权、循环、预算测试通过 |
| Day 3 | `day-3-replay` | Event Store、快照、Replay Engine | 回放状态哈希一致 |
| Day 4 | `day-4-chaos` | Chaos Injector 与故障恢复 | 故障注入确定性测试通过 |
| Day 5 | `day-5-benchmark` | 9 个场景、Evaluator、指标 | `agentlab bench` 达到 80% |
| Day 6 | `day-6-cli-report` | CLI、JSON/HTML 报告、OpenAI-compatible Adapter | 本地 demo 和 CLI 测试通过 |
| Day 7 | `day-7-release` | 文档、架构图、CI、示例、`v0.1.0` | 全套质量门禁通过并发布 |

每个阶段使用独立分支和 PR，至少包含一个功能提交、一个测试提交和必要的文档提交。PR 合并前必须通过 CI。

## 13. 风险与应对

### 13.1 范围膨胀

风险：同时加入 Web UI、数据库、分布式队列会超出七天范围。

应对：`v0.1.0` 只做 CLI、JSONL 和本地报告；HTTP API、Web UI、PostgreSQL 留到后续版本。

### 13.2 模型不确定性

风险：真实模型输出不稳定，无法建立可靠测试。

应对：所有 CI 和基准测试默认使用 `FakeAdapter`；真实模型适配器只做可选集成测试。

### 13.3 安全风险

风险：工具调用可能读写敏感数据或产生副作用。

应对：默认禁用真实副作用工具；仓库只包含模拟工具；API Key 只读环境变量。

### 13.4 GitHub 权限风险

风险：没有远程写权限或凭据不可用。

应对：先在本地完成按天提交；远程仓库创建和推送前验证 GitHub 身份、仓库名和默认分支。

### 13.5 项目叙事过度包装

风险：README 只讲愿景，缺少可验证结果。

应对：README 首屏提供 Quick Start、架构图、基准表和真实失败恢复示例；不使用无法复现的性能数字。

## 14. 发布验收清单

- [ ] 仓库包含 MIT License。
- [ ] `pyproject.toml` 可通过 `pip install -e .` 安装。
- [ ] `agentlab demo` 无外部依赖即可执行。
- [ ] 9 个场景全部可以重复运行。
- [ ] Replay 不产生模型或工具调用。
- [ ] JSON 和 HTML 报告包含完整指标。
- [ ] CI 在 Python 3.11、3.12、3.13 上通过。
- [ ] 核心覆盖率不低于 85%。
- [ ] README 包含架构、Quick Start、场景说明、评测结果和设计取舍。
- [ ] `CHANGELOG.md` 包含 `v0.1.0`。
- [ ] Git 标签 `v0.1.0` 与发布说明一致。
- [ ] 仓库中不存在密钥、Token 或个人隐私数据。

## 15. 后续版本方向

`v0.2.0` 可以增加：

- FastAPI 查询接口
- SQLite Run Catalog
- OpenTelemetry 导出
- 多 Agent 协作轨迹
- 并行工具调用
- 远程模型成本统计
- GitHub Actions 场景插件

这些功能不进入 `v0.1.0`，以确保一周内交付完整、可运行、可验证的项目。