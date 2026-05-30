# Домашнє завдання 13: Containers for AI

## Автор

**Імʼя:** Pavlo Kondes
**GitHub:** Mozenrat21

---

## 1. Опис роботи

У цьому домашньому завданні було контейнеризовано FastAPI RAG-застосунок із наданого boilerplate для Lesson 13.

Основна мета роботи:

* створити baseline Docker image через `Dockerfile.naive`;
* створити оптимізований multi-stage Docker image через `Dockerfile`;
* порівняти розмір Docker images;
* заміряти build time, rebuild time та cold start;
* додати запуск від non-root користувача;
* додати Docker `HEALTHCHECK`;
* підняти застосунок разом із Qdrant, Redis, Langfuse та Postgres через Docker Compose;
* додати скріншоти з перевірками.

---

## 2. Що додано в submission

У папці `lesson-13-containers-for-ai/homework/submissions/Mozenrat21/` додано:

```text
Dockerfile
Dockerfile.naive
docker-compose.yml
.dockerignore
README.md
screenshots/
```

Скріншоти:

```text
screenshots/
├── 01_ask_endpoint.png
├── 02_images_size.png
├── 03_container_healthy.png
└── 04_compose_services.png
```

Файл `.env` не додається до репозиторію, тому що містить секретний `OPENAI_API_KEY`.

---

## 3. Важлива примітка про build context

Dockerfile-и розроблені для запуску на основі boilerplate-застосунку, де доступні папки:

```text
app/
data/
```

Під час виконання домашнього завдання build виконувався з кореня boilerplate-проєкту, де були доступні `app/requirements.txt`, код FastAPI-застосунку та файл `data/faq.jsonl`.

У submission-папку додано саме ті файли, які вимагаються умовою домашнього завдання.

---

## 4. Dockerfile.naive

`Dockerfile.naive` використовується як baseline-варіант.

Особливості:

* використовується повний базовий image `python:3.11`;
* весь проєкт копіюється через `COPY . .`;
* залежності встановлюються прямо у фінальний image;
* немає multi-stage build;
* немає non-root користувача;
* немає healthcheck.

Build:

```powershell
docker build -f Dockerfile.naive -t lesson13-rag:naive .
```

Run:

```powershell
docker run --rm --name lesson13-rag-naive --env-file .env -p 8000:8000 lesson13-rag:naive
```

---

## 5. Optimized Dockerfile

`Dockerfile` реалізує оптимізований multi-stage build.

Що зроблено:

* використано `builder` stage;
* використано окремий `runtime` stage;
* runtime image базується на `python:3.11-slim`;
* залежності встановлюються в окремий virtual environment;
* у фінальний image копіюється тільки virtual environment, `app/` та `data/`;
* застосунок запускається від non-root користувача `appuser`;
* додано Docker `HEALTHCHECK`, який перевіряє endpoint `/health`.

Build:

```powershell
docker build -f Dockerfile -t lesson13-rag:multi .
```

Run:

```powershell
docker run --rm --name lesson13-rag-multi --env-file .env -p 8000:8000 lesson13-rag:multi
```

Перевірка healthcheck:

```powershell
docker ps
```

Очікуваний статус:

```text
Up ... (healthy)
```

---

## 6. Docker Compose

`docker-compose.yml` піднімає такі сервіси:

| Сервіс     | Призначення                       |
| ---------- | --------------------------------- |
| `app`      | FastAPI RAG service               |
| `qdrant`   | Vector database                   |
| `redis`    | Cache / допоміжний сервіс         |
| `langfuse` | Observability для LLM-застосунків |
| `postgres` | База даних для Langfuse           |

Запуск:

```powershell
docker compose up -d --build
```

Перевірка сервісів:

```powershell
docker compose ps
```

Перевірка застосунку:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

Очікуваний результат:

```text
status
------
ok
```

Перевірка `/ask`:

```powershell
curl.exe -X POST "http://localhost:8000/ask" -H "Content-Type: application/json" --data-raw '{"question":"What is Docker multi-stage build?"}'
```

Перевірка Qdrant:

```powershell
Invoke-RestMethod -Uri "http://localhost:6333/healthz"
```

Очікуваний результат:

```text
healthz check passed
```

Langfuse доступний у браузері:

```text
http://localhost:3000
```

---

## 7. Метрики

| Метрика                    |     Naive | Multi-stage |
| -------------------------- | --------: | ----------: |
| Image size                 |   1.76 GB |      367 MB |
| Build time                 | 67.06 sec |   60.33 sec |
| Rebuild after code change  | 24.90 sec |    4.78 sec |
| Cold start до `/health=ok` |  3.37 sec |    2.79 sec |

Додатково для multi-stage image налаштовано Docker `HEALTHCHECK`, який перевіряє, що endpoint `/health` повертає `status = ok`.

---

## 8. Пояснення результатів

Naive image вийшов значно більшим, тому що:

* використовується повний базовий image `python:3.11`;
* весь проєкт копіюється через `COPY . .`;
* залежності встановлюються прямо у фінальний image;
* немає окремого runtime stage.

Multi-stage image вийшов меншим і швидшим при повторному build, тому що:

* використовується легший базовий image `python:3.11-slim`;
* залежності встановлюються в окремому builder stage;
* у фінальний runtime image копіюється тільки необхідне;
* Docker cache краще використовується після зміни коду;
* застосунок запускається від non-root користувача;
* healthcheck перевіряє реальну готовність API.

Основний результат оптимізації:

* розмір image зменшився з `1.76 GB` до `367 MB`;
* rebuild після зміни коду зменшився з `24.90 sec` до `4.78 sec`;
* cold start зменшився з `3.37 sec` до `2.79 sec`.

---

## 9. Скріншоти

| Файл                       | Що підтверджує                                                         |
| -------------------------- | ---------------------------------------------------------------------- |
| `01_ask_endpoint.png`      | endpoint `/ask` повертає відповідь і sources                           |
| `02_images_size.png`       | порівняння розміру naive і multi-stage image                           |
| `03_container_healthy.png` | Docker healthcheck для optimized container                             |
| `04_compose_services.png`  | запуск сервісів через Docker Compose, `/health=ok`, Qdrant healthcheck |

---

## 10. Висновок

У результаті виконання домашнього завдання було підготовлено Docker-конфігурацію для FastAPI RAG-застосунку.

Було створено два Docker image:

* naive image для baseline-порівняння;
* optimized multi-stage image для більш production-like запуску.

Оптимізований image має менший розмір, швидший rebuild, працює від non-root користувача і має healthcheck. Також застосунок було запущено через Docker Compose разом із Qdrant, Redis, Langfuse і Postgres.

Це важливо для production AI-систем, тому що контейнер має бути легким, відтворюваним, безпечнішим і зручним для запуску в різних середовищах.
