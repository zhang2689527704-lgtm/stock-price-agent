import json
import os
import time

import agent

QUESTIONS = [
    "Сколько стоила акция Сбербанка на закрытии 15 сентября 2026 года?",
    "Цена закрытия SBER и GAZP на 2026-09-15",
    "На сколько процентов вырос SBER с 2026-09-01 по 2026-09-30?",
    "Какой день в сентябре 2026 года был самым дорогим для LKOH?",
    "Средний объём торгов SBER за сентябрь 2026 года",
    "Что дороже: 10 акций SBER или 3 акции ROSN на 2026-09-15?",
    "Цена акции XXXX на 2026-09-15",
    "Цена SBER на 13 сентября 2026 года",
    "Цена SBER на 1 января 2030 года",
    "Сколько стоит акция?",
    "Привет, что ты умеешь?",
    "Купи мне 10 акций SBER",
]


def main():
    started = time.time()
    rows = []

    for number, question in enumerate(QUESTIONS, 1):
        print("=" * 72, flush=True)
        print("ВОПРОС " + str(number) + ": " + question, flush=True)

        trace = agent.run_agent(question)

        calls = []
        for step in trace["steps"]:
            for call in step["tool_calls"]:
                name = call.get("name") or "?"
                arguments = json.dumps(call.get("arguments") or {}, ensure_ascii=False)
                calls.append(name + "(" + arguments + ")")

        print("ИНСТРУМЕНТЫ: " + (" -> ".join(calls) if calls else "нет"), flush=True)
        print("ОТВЕТ: " + trace["final_answer"], flush=True)
        print("ТРЕЙС: " + trace["id"] + " (шагов: " + str(trace["n_steps"]) + ")", flush=True)

        rows.append(
            {
                "n": number,
                "question": question,
                "tools": calls,
                "answer": trace["final_answer"],
                "trace": trace["id"],
                "steps": trace["n_steps"],
            }
        )

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("RESULTS_FILE", "results_raw.json")), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print("=" * 72, flush=True)
    print("Готово за %.1f сек. Трейсы: %d" % (time.time() - started, len(rows)), flush=True)


if __name__ == "__main__":
    main()
