# 股票价格智能体（DeepSeek API + MOEX ISS）

通过 LLM tool-calling 回答股票价格问题：问题 → 模型选择工具和参数 → Python 调用 MOEX ISS API → 结果返回模型 → 回答。模型本身不知道行情数据，也不做心算，所有数字来自工具。

最终运行：**12/12 全部正确，耗时 38.6 秒**，使用 DeepSeek `deepseek-chat`（API 实际返回的 `model` 字段为 `deepseek-flash`），本地 CPU 运行，无需 GPU。

## 1. 项目结构

```text
LLM/
├── tools.py          # 4 个工具 + MOEX 请求 + cache/ + 离线模式
├── schemas.py        # 4 个工具的 JSON Schema（俄语描述）
├── functions.py      # 兼容文件名：从 schemas.py 重新导出 TOOLS
├── prompt.py         # 俄语 system prompt + few-shot 示例
├── llm.py            # DeepSeek OpenAI 兼容后端（temperature=0）
├── agent.py          # 6 步循环、并行 tool_calls、role="tool"、写 traces/
├── run_eval.py       # 12 题评测入口
├── cache/            # MOEX API 原始响应的 JSON 缓存（9 个文件）
├── traces/           # 12 份运行日志（消息、工具、参数、结果）
└── README.md
```

`run_eval.py` 运行后会生成 `results_raw.json`（12 题汇总，非必需）。

## 2. 运行方法

### 依赖

只需要 **Python 3.10+ 标准库**，不需要 torch / transformers / requests / jinja2。

### 运行 12 题

```bash
export DEEPSEEK_API_KEY=...   # 推荐方式：只放在环境变量里
python run_eval.py
```

本地演示也可以把 key 放在 `config.py`，这样不需要设置环境变量：

```python
DEEPSEEK_API_KEY = "..."
```

环境变量优先；没有环境变量时才读取 `config.py`。`config.py` **不属于交付物**，提交前请删除或清空。

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | API key，必须设置 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `DEEPSEEK_API_URL` | `https://api.deepseek.com/chat/completions` | 接口地址 |
| `TRACES_DIR` | `traces` | 轨迹输出目录 |
| `RESULTS_FILE` | `results_raw.json` | 汇总结果文件名 |
| `OFFLINE` | `0` | `1` 时工具只读 `cache/`，不访问 MOEX |

### 离线模式

`tools.py` 在 `OFFLINE=1`（或 `tools.OFFLINE = True`）时完全不访问 MOEX，只读 `cache/*.json`；缓存缺失时返回俄语错误文本，不会崩溃。注意：离线模式只覆盖行情数据，调用 DeepSeek API 仍然需要网络。

```bash
OFFLINE=1 python -c "import tools; print(tools.get_close_price('SBER','2026-09-15'))"
```

已验证：`find_security('сбер')`、`get_close_price('SBER','2026-09-15')`、`get_history('SBER','2026-09-01','2026-09-30')`、`calculate('511357570/28')` 在离线模式下都可正常返回。

## 3. 工具

| 工具 | 参数 | 返回 |
| --- | --- | --- |
| `find_security` | `query: str` | `{ticker, name}` 列表（最多 5 个）。公司名查询默认只返回普通股；精确 ticker（如 `SBERP`）仍可查优先股 |
| `get_close_price` | `ticker: str`, `date: str` (YYYY-MM-DD) | `{ticker, date, close}`；非交易日返回最近的前一交易日，并带 `requested_date` 和 `note` |
| `get_history` | `ticker: str`, `date_from: str`, `date_to: str` | `{date, close, volume}` 列表；支持分页 |
| `calculate` | `expression: str` | 数字；仅 `+ - * / ( )`，基于 `ast` 白名单，不使用 `eval` |

工具描述（JSON Schema）在 `schemas.py` 中，全部为俄语，包含参数格式和示例。工具出错时返回 `"ОШИБКА: ..."` 文本，不会抛出异常。

### 缓存与错误处理

- 每次 MOEX 请求成功后把原始 JSON 写入 `cache/<可读前缀>_<hash>.json`。
- 网络失败时自动回退到缓存；缓存也没有才返回错误文本。
- `find_security` 会做俄语词尾回退（`Сбербанка` → `сбербанк`），并过滤掉 ETF/基金等非股票类型。
- `get_history` 的工具消息在列表末尾附带 `Всего строк` 和 `Сумма volume`，模型只需调用 `calculate` 做除法，避免抄写长列表出错。

## 4. 智能体循环

`agent.py` 的 `run_agent(question)`：

1. messages = system prompt + few-shot + 用户问题；
2. 调用 `llm.chat()`，DeepSeek 返回结构化的 `tool_calls`；
3. 有工具调用时，把 assistant 消息（含 `tool_calls`）追加到 messages，再逐个执行工具，追加 `role="tool"`、`tool_call_id` 对应的结果；
4. 没有工具调用即为最终回答；
5. 最多 6 个 LLM 步；超过则返回 `"Не удалось получить ответ за 6 шагов..."`。

其他要求：

- 并行调用：一次响应里有多个 `tool_calls` 时会全部执行；Q2/Q6 实测为单轮并行取价。
- 非法 JSON 参数：解析失败时把错误文本作为工具结果回传，让模型自行纠正。
- `temperature=0`：请求中固定为 0。
- 每题写 `traces/<id>.json`：包含全部 messages、tool_calls（id/name/arguments）、工具结果、最终回答、步数。

### few-shot 格式转换

`prompt.py` 的示例使用文本标签 `<tool_call>{...}</tool_call>`。`llm.py` 在发送前会把它们转换成 OpenAI 格式的 `tool_calls`（带 `id`），并把后续的 tool 消息补上对应的 `tool_call_id`；实际运行中的 assistant/tool 消息本来就有 id，直接透传。

## 5. 12 题结果

12 道题按作业要求用俄语提问，`run_eval.py` 中保存的是俄语版本。12 份轨迹在 `traces/`。

| № | 调用的工具 | 参数 | 智能体的回答 | 正确（是/否） |
| --- | --- | --- | --- | --- |
| 1 | `find_security` → `get_close_price` | `{"query":"Сбербанк"}`；`{"ticker":"SBER","date":"2026-09-15"}` | Акция Сбербанка на закрытии 15 сентября 2026 года стоила **284.91** рубля. | 是 |
| 2 | `get_close_price` ×2（单轮并行） | SBER / 2026-09-15；GAZP / 2026-09-15 | SBER — **284.91** рубля, GAZP — **96.69** рубля. | 是 |
| 3 | `get_history` → `calculate` | SBER 2026-09-01…30；`(273.92 - 272.21) / 272.21 * 100` | Выросла на **0.63%**. | 是 |
| 4 | `get_history` | LKOH 2026-09-01…30 | Максимум **5496.5** — **14 сентября 2026**, среди 28 торговых дней. | 是 |
| 5 | `get_history` → `calculate` | SBER 2026-09-01…30；`511357570 / 28` | Около **18 262 770** акций в день. | 是 |
| 6 | `get_close_price` ×2（并行）→ `calculate` ×2 | SBER 284.91；ROSN 372.65；`10 * 284.91`；`3 * 372.65` | 10 SBER = **2849.1**, 3 ROSN = **1117.95**；дороже **10 акций SBER**. | 是 |
| 7 | `find_security` | `{"query":"XXXX"}` | Тикер **XXXX не найден**, цену указать невозможно. | 是 |
| 8 | `get_close_price` | SBER / 2026-09-13 | 13 сентября — **неторговый день**, использована **11 сентября**, цена **283.32** рубля. | 是 |
| 9 | `get_close_price` | SBER / **2030-01-01** | Данных нет — **дата в будущем**, торгов ещё не было. | 是 |
| 10 | — | — | Уточняющий вопрос: какая акция (название/тикер) и на какую дату. | 是 |
| 11 | — | — | 介绍价格、历史、均值、比较等能力，未调用工具。 | 是 |
| 12 | — | — | Отказ: «покупка и продажа акций невозможна». | 是 |

12 份轨迹的 `tool_call_id` 与 assistant `tool_calls` 已逐一校验，全部一致。

## 6. 失败分析与改进建议

最终运行 12/12 全部正确；以下是开发过程中真实遇到并修复的问题。

1. **few-shot 的格式与 API 不兼容。**
   `prompt.py` 的示例是文本标签 `<tool_call>...</tool_call>`，而 DeepSeek 的 OpenAI 接口要求 assistant 消息带结构化 `tool_calls`、tool 消息带 `tool_call_id`。直接发送会被拒绝或丢失上下文。
   改进：`llm.py` 的 `_to_openai_messages()` 在发送前解析标签、生成带 id 的 `tool_calls`，并给后续 tool 消息补上 id。

2. **并行 tool_calls 的处理。**
   Q2 和 Q6 中模型一次返回两个 `get_close_price` 调用。如果循环只处理第一个，或者给每个调用重复追加 assistant 消息，`tool_call_id` 就会错位。
   改进：一个 assistant 消息只追加一次，里面包含全部 `tool_calls`；然后按顺序为每个 id 追加一条 `role="tool"` 消息。Q2 用 2 步、Q6 用 4 步完成，均在上限 6 步内。

3. **Q9 未来日期不能编造。**
   `get_close_price` 在日期晚于今天时直接返回 `"ОШИБКА: ... дата в будущем"`，不请求行情。模型据此回答无数据，没有编造价格。
   改进：未来日期检查放在工具入口，而不是依赖模型判断；同时 system prompt 要求工具报错必须如实转述。

4. **Q8 非交易日必须解释 `note`。**
   工具对 2026-09-13（周日）返回 `date=2026-09-11`、`requested_date=2026-09-13` 和 `note`。如果模型只看 `close`，会误说成 "13 日的价格"。
   改进：system prompt 明确要求"有 note 必须解释"，并加入周末 few-shot；最终回答明确说明使用了 11 日的数据。

5. **Q5 长列表求平均容易抄错。**
   9 月有 28 个交易日，把 28 个 volume 逐个抄进 `calculate` 很容易漏数或除数写错。
   改进：`get_history` 的工具消息附带 `Всего строк` 和 `Сумма volume`，模型调用 `calculate("511357570 / 28")` 即可。Q6 的步数偏紧（4/6），few-shot 让模型对显式 ticker 不再额外调用 `find_security`，避免超步。

## 7. 技术说明

- 模型：DeepSeek `deepseek-chat`（API 实际返回 `deepseek-flash`），`temperature=0`，`tool_choice="auto"`，`max_tokens=512`。
- 运行：本地 Windows，Python 3.12，仅标准库；无需 GPU。
- 耗时：12 题共 38.6 秒（含网络请求）。
- 工具调用协议：DeepSeek 返回 OpenAI 格式的 `tool_calls`；`agent.py` 用 `role="tool"` + `tool_call_id` 回传结果。
- 评测：12 题顺序执行，每题独立会话；`traces/` 下 12 个 JSON 为最终一次运行的日志。
- 缓存：9 个 MOEX 原始响应文件；离线模式已验证。
- 安全：API key 可通过 `DEEPSEEK_API_KEY` 环境变量或本地 `config.py` 提供；`config.py` 只是本地演示文件，提交前请删除或清空。演示后建议在 DeepSeek 控制台轮换 key。
