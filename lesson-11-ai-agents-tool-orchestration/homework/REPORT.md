# Personal Finance Coach — Звіт

## Архітектура

- **Framework:** LangGraph
- **Crew:** Synthesizer (router + final), Analyst, Advisor
- **Baseline:** single-agent tool-use loop
- **Multi-turn:** `MemorySaver` + окремий chat history на архітектуру в Streamlit
- **Модель:** `google/gemini-2.0-flash-001`

## Метрики

Останній зафіксований прогін: **golden set, 16 кейсів x 2 архітектури = 32 запусків**.

| Метрика | Crew | Baseline | Winner |
|---------|------|----------|--------|
| latency_p50_ms | 4398.5 | 1550.5 | Baseline |
| latency_p95_ms | 6597.5 | 3985.75 | Baseline |
| cost_per_task_usd | 0.00026644 | 0.00012123 | Baseline |
| tokens_per_task | 2121.19 | 1024.94 | Baseline |
| success_rate | 0.6875 | 0.4375 | Crew |
| route_accuracy | 0.875 | 0.875 | Tie |
| tool_selection_accuracy | 0.5365 | 0.3750 | Crew |
| groundedness | 0.7888 | 0.9583 | Baseline |
| failed_tasks | 0 | 0 | Tie |

## Multi-agent specific

| Метрика | Значення |
|---------|----------|
| inter_agent_overhead_pct | 60.6419 |
| completed_tasks | 16 |
| failed_tasks | 0 |

### Cost breakdown by agent

| Agent | Avg cost per task (USD) |
|-------|--------------------------|
| synthesizer_route | 0.00003441 |
| analyst | 0.00008427 |
| synthesizer_final | 0.00011774 |
| advisor | 0.00013378 |

### Baseline cost breakdown

| Agent | Avg cost per task (USD) |
|-------|--------------------------|
| baseline | 0.00012123 |

## Де crew виграє

- **Краще проходить golden set:** `success_rate = 68.75%` проти `43.75%` у baseline.
- **Краще підбирає інструменти:** `tool_selection_accuracy = 53.65%` проти `37.50%`.
- Дає кращу якість для сценаріїв з routing, multi-step, fraud та follow-up контекстом.

## Де baseline виграє

- **Швидший:** p50 `1550.5 ms` проти `4398.5 ms` у crew.
- **Дешевший:** `$0.00012123` на задачу проти `$0.00026644`.
- **Більш grounded:** `0.9583` проти `0.7888`.
- Простішa траєкторія для коротких factual/statistics запитів.

## Рекомендації для production

1. Лишити **crew** для `multi_step`, `savings`, `fraud` і follow-up сценаріїв, де routing дає виграш по якості.
2. Для коротких `stats` запитів використовувати **adaptive routing** на дешевший `baseline` path.
3. Зменшити overhead crew: зараз `inter_agent_overhead_pct = 60.64%`, тобто orchestration занадто дорога.
4. Підсилити groundedness crew через суворіший control над tool outputs і формулюванням фінальної відповіді.
5. Продовжити regression tracking через LangSmith Dataset + Experiments.

## LangSmith setup

1. Створи акаунт на `smith.langchain.com`.
2. Додай `LANGCHAIN_API_KEY` у `.env`.
3. Створи Dataset з `eval/golden_set.py`.
4. Запусти `python -m eval.evaluators` або Eval tab у Streamlit.
5. Порівняй crew vs baseline в Experiments UI.

## Обмеження та труднощі

- Оцінка `groundedness` реалізована евристично через звірку чисел у відповіді з числовими значеннями з tool outputs.
- `inter_agent_overhead_pct` вимірюється як частка токенів Synthesizer-викликів від загальних токенів crew.
- Для стабільності checkpointer токен-метрики зберігаються поза checkpointed state.
- Навіть після покращень golden set показує, що crew ще не достатньо стабільний для всіх кейсів: `success_rate = 68.75%`, тож система придатна для демо/навчального використання, але не як production-ready фінансовий copilot без подальшого тюнінгу.
