# LLMOps Crisis Room — live demo (lesson 12)

Симулятор продакшн LLM-сервісу. На парі ти натискаєш кнопки — система "ламається" і "лікується" → студенти бачать live дашборд (як у Langfuse / Datadog) і одразу розуміють для чого існує кожна категорія LLMOps стеку.

## Що показує демо (за 30 хв)

| Crisis (кнопка у sidebar) | Що відбувається | Закриває концепцію |
|---|---|---|
| **Run normal traffic** | 8 реальних LLM-викликів → traces у Langfuse | Observability |
| **Deploy v2 (bloated)** | Той самий запит, +3000 токенів у system prompt → cost ×4 | Prompt versioning + regression |
| **Rollback to v1** | Один клік повертає попередню версію | Як деплой коду, тільки для тексту |
| **Kill openai/anthropic/google** | Gateway автоматично пробує fallback chain | LLM Gateway (LiteLLM-style) |
| **Prompt caching** | Системний prompt кешується → ~75% знижка | Cost control · caching |
| **Cheap router** | Короткі запити → Flash, довгі → primary | Cost control · routing |
| **Inject off-topic + eval** | Sonnet оцінює відповіді → quality падає, halluc ↑ | Evals / LLM-as-a-judge |

## Як запустити

### 1) Поставити залежності

```bash
cd lesson-12-mlops-aiops-foundations/demo/llmops-crisis-room
make install          # створює .venv, ставить deps, копіює .env
```

### 2) Підняти Langfuse self-hosted

```bash
make langfuse-up      # запускає docker compose з Langfuse v3 стеком
```

Перший раз ~2 хв тягне образи (postgres, clickhouse, redis, minio, langfuse-server, langfuse-worker).

Коли запуститься — відкрий **http://localhost:3000**:
1. Sign up (email/password — все локально, нічого нікуди не йде)
2. Створи проект → візьми **Public Key** і **Secret Key** у Settings → API Keys
3. Заповни у `.env`:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

### 3) Додати OpenRouter ключ

```
OPENROUTER_API_KEY=sk-or-v1-...    # https://openrouter.ai/keys
```

### 4) Запустити Streamlit

```bash
make demo             # http://localhost:8504
```

У sidebar обидва бейджі мають світитись 🟢. Якщо ні — перевір `.env`.

## План на парі (30 хв)

```
[0-3]  Baseline. Натискаєш "Run normal traffic 8".
       → У Tab 1 видно 8 traces. Tab 2: cost ~$0.001. Tab 3: пусто. Tab 4: вся chain LIVE.
       → Відкрий Langfuse у браузері поряд — ті самі traces там.
       → Пояснення: це observability. Без неї cost — чорна скринька.

[3-8]  Криза #1: bloated prompt.
       → Натискаєш "Deploy v2 (bloated)". Запускаєш ще 8 traffic.
       → Tab 2: на графіку видно різке зростання cost per request у червоних точках.
       → Tab 1: input_tokens у нових traces ×3-4 порівняно з v1.
       → Натискаєш "Rollback to v1". Запускаєш traffic знову.
       → Cost повертається. Пояснення: prompt versioning + rollback як для коду.

[8-13] Криза #2: provider down.
       → У Tab 4 чек "💀 openai". Запускаєш traffic 5.
       → Gateway log: "trying gpt-4o-mini... failed → trying haiku → ok".
       → Tab 4 "Traffic per provider" показує що 100% запитів пішли через Anthropic.
       → Пояснення: це LLM Gateway з fallback chain. Без нього у тебе зараз 503.

[13-18] Криза #3: cost explosion.
       → Знімаєш kill, vrnaєш OpenAI. Toggle "Prompt caching" + "Cheap router".
       → Запускаєш 15 traffic.
       → Tab 2: cost per request впав у 3-4×, при тих самих токенах.
       → Пояснення: cache + routing = перші важелі економії.

[18-25] Криза #4: quality drift.
       → "Inject off-topic + eval" 5 запитів.
       → Tab 3: графік quality падає, hallucination risk росте.
       → Пояснення: LLM-as-a-judge ловить деградацію без user complaint.

[25-30] Підсумок.
       → Відкрий Langfuse: показуй full trace tree, dataset evals, prompt diff.
       → "Це і є LLMOps стек: observability + versioning + gateway + cost + evals."
```

## Структура

```
llmops-crisis-room/
├── Makefile, requirements.txt, .env.example, .gitignore
├── docker-compose.yml          # Langfuse v3 self-hosted
├── app.py                       # Streamlit UI з 4 вкладками
├── data/scenarios.py            # FAQ KB v1/v2, normal/off-topic queries
└── src/
    ├── llm.py                   # OpenRouter client + Langfuse tracing
    ├── observability.py         # Langfuse SDK wrapper + TraceRecord
    ├── gateway.py               # Mini LiteLLM з fallback chain
    └── evals.py                 # LLM-as-a-judge (Sonnet)
```

## Стек

- **OpenRouter** — один API для OpenAI / Anthropic / Google (сам по собі Gateway-as-a-Service)
- **Langfuse v3 self-hosted** — observability, traces, prompt versioning
- **Streamlit** — UI
- **Plotly** — графіки cost / quality
- **Pydantic** — schema валідація

## Коштує

Дешеві моделі за замовчуванням (gpt-4o-mini, haiku-4.5, gemini-2.0-flash). Повна 30-хвилинна демо ≈ **$0.10-0.30**. Підготовка з прогоном кожної кризи 2-3 рази → $0.50-1.00.

## Troubleshooting

- **`docker compose up` падає** — переконайся що Docker Desktop запущений і має ≥ 4 GB RAM.
- **Langfuse не відкривається на localhost:3000** — `make langfuse-logs` покаже шо там. Перший запуск займає ~2 хв на pull образів.
- **OPENROUTER_API_KEY not set** — `.env` має бути у тій самій папці що `app.py`.
- **Langfuse traces не показуються в UI** — перевір `LANGFUSE_HOST=http://localhost:3000` (без слешу в кінці).
- **Wipe Langfuse data** — `docker compose down -v` зносить volumes.
