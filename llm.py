import json
import os
import re
import urllib.error
import urllib.request

API_URL = os.environ.get(
    "DEEPSEEK_API_URL",
    "https://api.deepseek.com/chat/completions",
)
MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def _parse_tool_call_tags(text):
    """Извлекает <tool_call>{...}</tool_call> из few-shot примеров."""
    calls = []
    for match in TOOL_CALL_RE.finditer(text or ""):
        try:
            obj = json.loads(match.group(1))
        except Exception:
            continue
        name = obj.get("name")
        arguments = obj.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append({"name": name, "arguments": arguments})
    return calls


def _to_openai_messages(messages):
    """Приводит сообщения агента к формату OpenAI tool-calling.

    Few-shot примеры используют текстовые теги: assistant содержит
    <tool_call>..., а tool-сообщения без tool_call_id. Здесь они
    преобразуются в настоящие tool_calls с id.
    """
    result = []
    pending_ids = []

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""

        if role == "assistant":
            if message.get("tool_calls"):
                clean = TOOL_CALL_RE.sub("", content).strip()
                result.append(
                    {
                        "role": "assistant",
                        "content": clean or None,
                        "tool_calls": message["tool_calls"],
                    }
                )
                pending_ids = []
                continue

            demo_calls = _parse_tool_call_tags(content)
            if demo_calls:
                openai_calls = []
                ids = []
                for index, call in enumerate(demo_calls, 1):
                    call_id = "demo_" + str(len(result)) + "_" + str(index)
                    ids.append(call_id)
                    openai_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(
                                    call["arguments"], ensure_ascii=False
                                ),
                            },
                        }
                    )
                clean = TOOL_CALL_RE.sub("", content).strip()
                result.append(
                    {
                        "role": "assistant",
                        "content": clean or None,
                        "tool_calls": openai_calls,
                    }
                )
                pending_ids = ids
                continue

            result.append({"role": "assistant", "content": content})
            pending_ids = []
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not call_id and pending_ids:
                call_id = pending_ids.pop(0)
            item = {"role": "tool", "content": content}
            if call_id:
                item["tool_call_id"] = call_id
            result.append(item)
        else:
            result.append({"role": role, "content": content})

    return result


def _headers():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        try:
            from config import DEEPSEEK_API_KEY as local_key
            key = str(local_key).strip()
        except Exception:
            key = ""
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY не задан (ни в env, ни в config.py)")
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    }


def chat(messages, tools, step=1):
    """Один шаг DeepSeek: возвращает {content, tool_calls}."""
    payload = {
        "model": MODEL_NAME,
        "messages": _to_openai_messages(messages),
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 512,
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError("DeepSeek HTTP " + str(exc.code) + ": " + detail)
    except Exception as exc:
        raise RuntimeError("DeepSeek request failed: " + str(exc))

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(
            "DeepSeek: пустой ответ: "
            + json.dumps(body, ensure_ascii=False)[:500]
        )

    message = choices[0].get("message") or {}
    content = message.get("content") or ""

    calls = []
    for index, tool_call in enumerate(message.get("tool_calls") or [], 1):
        function = tool_call.get("function") or {}
        raw = function.get("arguments")
        call = {
            "id": tool_call.get("id") or ("call_" + str(step) + "_" + str(index)),
            "name": function.get("name"),
            "arguments": {},
            "raw": raw,
        }
        if isinstance(raw, dict):
            call["arguments"] = raw
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    call["arguments"] = parsed
            except Exception:
                call["error"] = "неверный JSON в аргументах: " + raw
        calls.append(call)

    return {"content": content, "tool_calls": calls}
