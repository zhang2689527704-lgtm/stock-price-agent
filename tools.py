# -*- coding: utf-8 -*-
"""4 инструмента для агента: find_security, get_close_price, get_history, calculate.

Данные: MOEX ISS (https://iss.moex.com). Ответы API кэшируются в cache/*.json.
Офлайн-режим: переменная окружения OFFLINE=1 (или tools.OFFLINE = True) —
тогда сеть не используется, читается только кэш.
"""

import ast
import datetime
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request

BASE_URL = "https://iss.moex.com/iss"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
OFFLINE = os.environ.get("OFFLINE", "0") == "1"
TIMEOUT = 20


# ---------------------------------------------------------------------------
# Кэш и HTTP
# ---------------------------------------------------------------------------

def _short_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _cache_path(key):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "", key)[:50]
    if len(safe) < 2:
        safe = "q"
    return os.path.join(CACHE_DIR, safe + "_" + _short_hash(key) + ".json")


def _read_cache(key):
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(key, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url, cache_key):
    """Возвращает JSON. Сначала сеть (и кэш), при ошибке — кэш; в OFFLINE — только кэш."""
    if not OFFLINE:
        try:
            data = _download(url)
            _write_cache(cache_key, data)
            return data
        except Exception as exc:
            cached = _read_cache(cache_key)
            if cached is not None:
                return cached
            raise RuntimeError("не удалось получить данные: " + str(exc))
    cached = _read_cache(cache_key)
    if cached is None:
        raise RuntimeError("офлайн-режим: нет кэша для " + cache_key)
    return cached


def _rows(data, block):
    """Преобразует блок MOEX {columns, data} в список словарей."""
    part = data.get(block) or {}
    columns = part.get("columns") or []
    rows = part.get("data") or []
    result = []
    for row in rows:
        result.append(dict(zip(columns, row)))
    return result


def _parse_date(text):
    text = str(text).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError("неверный формат даты: " + text + ". Ожидается YYYY-MM-DD, например 2026-09-15")


def _security_exists(ticker):
    try:
        url = BASE_URL + "/securities/" + ticker + ".json"
        data = _get_json(url, "security_" + ticker)
        return len(_rows(data, "description")) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Инструмент 1: поиск тикера
# ---------------------------------------------------------------------------

def find_security(query):
    """Ищет акции по названию. Возвращает список {ticker, name} (до 5) или текст ошибки."""
    try:
        query = str(query).strip()
        if not query:
            return "ОШИБКА: пустой запрос. Укажите название компании, например «сбер»."

        query_lower = query.lower()
        query_core = query_lower.rstrip("аеиоуыэюяйь")
        if len(query_core) < 3:
            query_core = query_lower

        url = (
            BASE_URL
            + "/securities.json?q="
            + urllib.parse.quote(query)
            + "&engine=stock&market=shares"
        )
        data = _get_json(url, "find_" + query_lower)
        rows = _rows(data, "securities")

        # Если исходная форма не дала результатов, пробуем основу слова:
        # «Сбербанка» → «сбербанк».
        if not rows and query_core != query_lower:
            url = (
                BASE_URL
                + "/securities.json?q="
                + urllib.parse.quote(query_core)
                + "&engine=stock&market=shares"
            )
            data = _get_json(url, "find_" + query_core)
            rows = _rows(data, "securities")

        found = []
        for row in rows:
            ticker = str(row.get("secid") or "").upper()
            name = str(row.get("shortname") or "")
            full_name = str(row.get("name") or "")
            sec_type = str(row.get("type") or "")
            if not ticker:
                continue
            if row.get("is_traded") in (0, "0"):
                continue
            if sec_type not in ("common_share", "preferred_share"):
                continue

            name_lower = name.lower()
            full_lower = full_name.lower()
            exact = ticker.lower() == query_lower
            matched = (
                query_lower in name_lower
                or query_core in name_lower
                or query_lower in full_lower
                or query_core in full_lower
            )
            if not exact and not matched:
                continue

            priority = 0 if exact else 1
            if sec_type == "preferred_share":
                priority += 2
            found.append((priority, ticker, name, sec_type))

        # Запрос по названию компании: по умолчанию оставляем обыкновенные
        # акции, чтобы модель не выбирала между обыкновенной и привилегированной.
        if not any(item[0] == 0 for item in found):
            common = [item for item in found if item[3] == "common_share"]
            if common:
                found = common

        found.sort(key=lambda item: item[0])

        result = []
        seen = set()
        for _, ticker, name, _ in found:
            if ticker in seen:
                continue
            seen.add(ticker)
            result.append({"ticker": ticker, "name": name})
            if len(result) >= 5:
                break
        return result
    except Exception as exc:
        return "ОШИБКА: " + str(exc)


# ---------------------------------------------------------------------------
# Инструмент 2: цена закрытия на дату
# ---------------------------------------------------------------------------

def get_close_price(ticker, date):
    """Цена закрытия. Если день неторговый — ближайший предыдущий торговый день + note."""
    try:
        ticker = str(ticker).strip().upper()
        if not re.match(r"^[A-Z0-9]+$", ticker):
            return "ОШИБКА: неверный тикер: " + ticker

        day = _parse_date(date)
        today = datetime.date.today()
        if day > today:
            return "ОШИБКА: данных за " + day.isoformat() + " нет — дата в будущем, торгов ещё не было."

        start = day - datetime.timedelta(days=30)
        url = (
            BASE_URL
            + "/engines/stock/markets/shares/boards/TQBR/securities/"
            + ticker
            + "/candles.json?from="
            + start.isoformat()
            + "&till="
            + day.isoformat()
            + "&interval=24&limit=500"
        )
        cache_key = "close_" + ticker + "_" + day.isoformat()

        try:
            data = _get_json(url, cache_key)
        except Exception as exc:
            if not _security_exists(ticker):
                return "ОШИБКА: тикер " + ticker + " не найден."
            return "ОШИБКА: " + str(exc)

        rows = _rows(data, "candles")
        if not rows:
            if not _security_exists(ticker):
                return "ОШИБКА: тикер " + ticker + " не найден."
            return "ОШИБКА: нет данных за " + day.isoformat() + " (нет торгов или данные не опубликованы)."

        rows.sort(key=lambda row: str(row.get("begin")))
        last = rows[-1]
        actual = str(last.get("begin"))[:10]
        close = float(last.get("close"))

        result = {"ticker": ticker, "date": actual, "close": close}
        if actual != day.isoformat():
            result["requested_date"] = day.isoformat()
            result["note"] = (
                day.isoformat()
                + " — неторговый день, использована ближайшая предыдущая торговая дата "
                + actual
            )
        return result
    except Exception as exc:
        return "ОШИБКА: " + str(exc)


# ---------------------------------------------------------------------------
# Инструмент 3: история за период
# ---------------------------------------------------------------------------

def get_history(ticker, date_from, date_to):
    """Дневные свечи за период: список {date, close, volume} или текст ошибки."""
    try:
        ticker = str(ticker).strip().upper()
        if not re.match(r"^[A-Z0-9]+$", ticker):
            return "ОШИБКА: неверный тикер: " + ticker

        start = _parse_date(date_from)
        end = _parse_date(date_to)
        if start > end:
            return "ОШИБКА: дата начала больше даты конца."
        if (end - start).days > 366:
            return "ОШИБКА: период больше 366 дней, сузьте диапазон."

        all_rows = []
        offset = 0
        while True:
            url = (
                BASE_URL
                + "/engines/stock/markets/shares/boards/TQBR/securities/"
                + ticker
                + "/candles.json?from="
                + start.isoformat()
                + "&till="
                + end.isoformat()
                + "&interval=24&limit=500&start="
                + str(offset)
            )
            cache_key = (
                "history_" + ticker + "_" + start.isoformat() + "_" + end.isoformat()
                + "_" + str(offset)
            )
            data = _get_json(url, cache_key)
            rows = _rows(data, "candles")
            all_rows.extend(rows)
            if len(rows) < 500:
                break
            offset += 500

        if not all_rows:
            if not _security_exists(ticker):
                return "ОШИБКА: тикер " + ticker + " не найден."
            return "ОШИБКА: нет данных за период " + start.isoformat() + " — " + end.isoformat() + "."

        result = []
        for row in all_rows:
            result.append(
                {
                    "date": str(row.get("begin"))[:10],
                    "close": float(row.get("close")),
                    "volume": row.get("volume"),
                }
            )
        return result
    except Exception as exc:
        return "ОШИБКА: " + str(exc)


# ---------------------------------------------------------------------------
# Инструмент 4: калькулятор (без eval)
# ---------------------------------------------------------------------------

def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("bad constant")
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise ValueError("bad unary op")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        raise ValueError("bad binary op")
    raise ValueError("bad node")


def calculate(expression):
    """Считает выражение только с + - * / ( ). Возвращает число или текст ошибки."""
    try:
        expr = str(expression).strip().replace(",", ".")
        if not expr:
            return "ОШИБКА: пустое выражение."
        if not re.match(r"^[0-9+\-*/(). ]+$", expr):
            return "ОШИБКА: недопустимые символы. Разрешены только цифры и + - * / ( )."

        tree = ast.parse(expr, mode="eval")
        value = _eval_node(tree.body)
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return "ОШИБКА: результат не является числом."
        return value
    except ZeroDivisionError:
        return "ОШИБКА: деление на ноль."
    except Exception:
        return "ОШИБКА: неверное выражение. Разрешены только + - * / ( )."
