import json
import os
import time
import uuid

import llm
import prompt
import schemas
import tools

MAX_STEPS = 6
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACES_DIR = os.path.join(BASE_DIR, os.environ.get("TRACES_DIR", "traces"))


def _run_tool(name, arguments):
    """Выполняет инструмент по имени. Ошибки не выбрасываются наружу."""
    try:
        if name == "find_security":
            return tools.find_security(arguments.get("query", ""))
        if name == "get_close_price":
            return tools.get_close_price(
                arguments.get("ticker", ""),
                arguments.get("date", ""),
            )
        if name == "get_history":
            return tools.get_history(
                arguments.get("ticker", ""),
                arguments.get("date_from", ""),
                arguments.get("date_to", ""),
            )
        if name == "calculate":
            return tools.calculate(arguments.get("expression", ""))
        return "ОШИБКА: неизвестный инструмент: " + str(name)
    except Exception as exc:
        return "ОШИБКА: " + str(exc)


def _tool_result_text(result):
    """Строки (включая тексты ошибок) отдаём как есть, структуры — как JSON."""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def run_agent(question):
    """Запускает агента на одном вопросе и пишет трейс."""
    trace_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    messages = [{"role": "system", "content": prompt.SYSTEM_PROMPT}]
    messages.extend(prompt.FEWSHOT)
    messages.append({"role": "user", "content": question})

    steps = []
    final_answer = ""

    for step in range(1, MAX_STEPS + 1):
        response = llm.chat(messages, schemas.TOOLS, step=step)
        content = response["content"]
        calls = response["tool_calls"]

        assistant_message = {"role": "assistant", "content": content}
        if calls:
            assistant_message["tool_calls"] = []
            for call in calls:
                assistant_message["tool_calls"].append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call.get("name") or "unknown",
                            "arguments": json.dumps(
                                call.get("arguments") or {},
                                ensure_ascii=False,
                            ),
                        },
                    }
                )
        messages.append(assistant_message)

        step_log = {"step": step, "assistant": content, "tool_calls": calls}
        steps.append(step_log)

        if not calls:
            final_answer = content.strip()
            break

        for call in calls:
            if call.get("error"):
                result_text = "ОШИБКА: " + call["error"]
            else:
                result = _run_tool(call.get("name"), call.get("arguments") or {})
                result_text = _tool_result_text(result)
                if call.get("name") == "get_history" and isinstance(result, list):
                    result_text = result_text + "\nВсего строк: " + str(len(result))
                    volumes = []
                    for row in result:
                        if isinstance(row, dict) and isinstance(row.get("volume"), (int, float)):
                            volumes.append(row.get("volume"))
                    if volumes:
                        result_text = result_text + "\nСумма volume: " + str(sum(volumes))

            call["result"] = result_text
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call.get("name") or "unknown",
                    "content": result_text,
                }
            )
    else:
        final_answer = (
            "Не удалось получить ответ за "
            + str(MAX_STEPS)
            + " шагов. Пожалуйста, уточните вопрос."
        )

    trace = {
        "id": trace_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "model": llm.MODEL_NAME,
        "temperature": 0,
        "max_steps": MAX_STEPS,
        "n_steps": len(steps),
        "steps": steps,
        "messages": messages,
        "final_answer": final_answer,
    }

    os.makedirs(TRACES_DIR, exist_ok=True)
    path = os.path.join(TRACES_DIR, trace_id + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace, f, ensure_ascii=False, indent=2)

    return trace
