# Demo — LLM Production Monitoring & Drift

Локальний стек **Prometheus + Grafana + fake-LLM симулятор** який програє сценарій **silent model drift** (провайдер тихо оновив модель) і показує, як content-based моніторинг ловить деградацію якості — у той час як APM (latency / error rate) рапортує "все ок".

Це і є головна теза уроку 15: *для AI Engineer, який споживає чужий API, дрифт виглядає як `200 OK 500ms` з галюцинацією всередині.*

---

## Що всередині

| Сервіс | Порт | Роль |
|---|---|---|
| `simulator` | 8081 | Fake-LLM що генерує запити/відповіді/judge scores і експортує метрики у Prometheus-форматі (`/metrics`) |
| `prometheus` | 9095 | Збирає метрики кожні 5с + ганяє alert-rules з `prometheus/alerts.yml` |
| `grafana` | 3030 | Дашборд "LLM Production Monitoring — Drift Demo" провіжниться автоматично |

### Симульовані метрики

- `llm_requests_total{intent}` — лічильник запитів
- `llm_refusals_total` — скільки модель відмовила
- `llm_cost_usd_total` — кумулятивна вартість
- `llm_tokens_total{kind}` — токени prompt/completion
- `llm_request_duration_seconds` — гістограма latency (APM-шар)
- `llm_judge_score` — faithfulness від LLM-as-a-Judge (RAGAS)
- `llm_judge_relevancy` — answer relevancy
- `llm_judge_context_precision` — context precision
- `llm_drift_phase` — 0/1/2 (baseline / incident / recovered)
- `llm_model_version_info{version}` — активна версія моделі

### Сценарій дрифту (за замовчуванням)

| Час від старту | Phase | Що відбувається |
|---|---|---|
| 0–120с | **BASELINE** | `gpt-4o @ 2024-05-13`. faithfulness ≈ 0.91, refusal ≈ 2%, cost/req ≈ $0.0012 |
| 120–300с | **INCIDENT** | Провайдер silent-rolled `gpt-4o @ 2024-08-06`. faithfulness падає до 0.58, refusal до 22%, cost/req до $0.0034. **APM latency не змінилася.** |
| 300с+ | **RECOVERED** | Команда задеплоїла фікс (system prompt + retrieval threshold). Метрики повертаються до baseline. |

Тривалість керується env-змінними: `DRIFT_START_SEC` / `DRIFT_DURATION_SEC`.

---

## Запуск

**Передумови:** Docker Desktop (або docker engine + compose plugin). Жодних API-ключів.

```bash
cd "lesson 15 - production-llm-monitoring-drift/demo"
./scripts/up.sh
```

Через ~30 секунд:

- Grafana → http://localhost:3030 → Dashboards → **LLM Production Monitoring — Drift Demo**
- Prometheus → http://localhost:9095
- Симулятор → http://localhost:8081/metrics

Авторизація у Grafana вимкнена (анонімний admin) — клацай дашборд одразу.

### Що показати на лекції

1. **t ≈ 0** — відкрий дашборд. Усі стат-панелі зелені, judge score ~0.9, refusal ~2%.
2. **t ≈ 120с** — `Drift phase` стає `INCIDENT`, `Active model version` стрибає на `2024-08-06`. **Faithfulness** проседає, **refusal rate** росте, **cost / request** подвоюється.
3. **Поглянь на APM-панель (p50/p95 latency)** — вона **не зрушила**. Це і є головна теза: APM не ловить content drift.
4. **Prometheus → Alerts** (http://localhost:9095/alerts) — спрацював `JudgeScoreDrop` (severity: page) і `RefusalRateSpike` (severity: warn). Алерт `APMLooksFine` лишився info — ілюструє blind spot APM-only-моніторингу.
5. **t ≈ 300с** — phase повертається до `RECOVERED`, метрики приходять у норму.

### Скоротити очікування

Не хочеш чекати 2 хвилини на лекції:

```bash
./scripts/trigger-drift-now.sh
```

Перезапустить симулятор з `DRIFT_START_SEC=10` — інцидент почнеться за 10с.

Або вручну:

```bash
DRIFT_START_SEC=30 DRIFT_DURATION_SEC=120 ./scripts/up.sh
```

### Зупинити

```bash
./scripts/down.sh
```

---

## Як це працює (під капотом)

`simulator/app.py`:

- Стартує фоновий потік `traffic_loop()` що тікає з частотою `RPS` запитів/сек.
- Кожен "запит" — це виклик `sample_one(phase)`, який залежно від поточної фази (`baseline` / `incident` / `recovered`) семплить latency, faithfulness, relevancy, refusal, cost з різних розподілів.
- Метрики експортуються через `prometheus_client` на `:8000/metrics`.
- Prometheus скрейпить `/metrics` кожні 5 секунд (`prometheus/prometheus.yml`).
- Alert rules (`prometheus/alerts.yml`) тригерять по content-based умовах:
  - `JudgeScoreDrop`: 1m-avg faithfulness < 0.7 → severity `page`
  - `RefusalRateSpike`: refusal_rate > 15% → severity `warn`
  - `CostPerRequestSpike`: середня вартість/запит > $0.003 → severity `warn`
  - `APMLooksFine`: показовий алерт-маркер що p95 < 1.5с попри incident
- Grafana отримує datasource (`grafana/provisioning/datasources/`) і дашборд (`grafana/dashboards/llm-drift.json`) автоматично при старті — нічого імпортувати не треба.

---

## Розширення (для домашки / експериментів)

1. **Додай новий сценарій** — у `simulator/app.py` зроби нову гілку у `current_phase()` (наприклад `embedding_drift`) і власні розподіли. Перемикай через `SCENARIO=embedding_drift ./scripts/up.sh`.
2. **Прикрути Alertmanager** — додай 4-й сервіс у `docker-compose.yml`, передай у Prometheus через `alerting:` секцію, налаштуй receiver на webhook.test → побачиш як алерт реально їде у Slack-канал.
3. **Замість fake-LLM — реальний OpenAI** — заміни `sample_one()` на справжній виклик з `openai-python` + RAGAS judge на golden-dataset (~30 кейсів). Тоді faithfulness буде з реальних запитів. Потребує `OPENAI_API_KEY`.
4. **Sampling control** — додай env `JUDGE_SAMPLING_RATE=0.1` і у `sample_one()` зменши частоту `judge_*` записів. На графіку видно як рідкісний sampling розмиває детекцію.

---

## Troubleshooting

- **`Cannot connect to the Docker daemon`** — підняти Docker Desktop.
- **Порт 3030 / 9095 / 8081 зайнятий** — змінити mapping у `docker-compose.yml` (наприклад `"3031:3000"`).
- **Дашборд не з'являється у Grafana** — `docker logs drift-grafana | grep provision` і перевір що `/var/lib/grafana/dashboards/llm-drift.json` змонтований.
- **`No data` на панелях у перші 10с** — нормально, дай Prometheus зробити перший scrape.
