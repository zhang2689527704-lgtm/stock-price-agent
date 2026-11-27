TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_security",
            "description": (
                "Ищет акции по названию компании или по тикеру. "
                "Возвращает до 5 результатов в виде {ticker, name}. "
                'Пример: query="сбер" → [{"ticker": "SBER", "name": "Сбербанк"}].'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Название компании или тикер. "
                            'Примеры: "сбер", "Сбербанк", "GAZP".'
                        ),
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_close_price",
            "description": (
                "Возвращает цену закрытия акции на указанную дату. "
                'Формат даты: YYYY-MM-DD, пример: "2026-09-15". '
                "Если день неторговый (выходной или праздник), возвращается "
                "ближайший предыдущий торговый день, а в поле note — пояснение."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": 'Тикер акции, например "SBER" или "GAZP".',
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            'Дата в формате YYYY-MM-DD, например "2026-09-15".'
                        ),
                    },
                },
                "required": ["ticker", "date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_history",
            "description": (
                "Возвращает дневные свечи за период: список {date, close, volume}. "
                'Формат дат: YYYY-MM-DD. Пример: ticker="SBER", '
                'date_from="2026-09-01", date_to="2026-09-30".'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": 'Тикер акции, например "SBER".',
                    },
                    "date_from": {
                        "type": "string",
                        "description": 'Начало периода в формате YYYY-MM-DD, например "2026-09-01".',
                    },
                    "date_to": {
                        "type": "string",
                        "description": 'Конец периода в формате YYYY-MM-DD, например "2026-09-30".',
                    },
                },
                "required": ["ticker", "date_from", "date_to"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Вычисляет арифметическое выражение. Разрешены только числа "
                "и операции + - * / ( ). "
                'Пример: expression="(103 - 100) / 100 * 100".'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Арифметическое выражение, например "
                            '"(103 - 100) / 100 * 100" или "10 * 234.56".'
                        ),
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
]
