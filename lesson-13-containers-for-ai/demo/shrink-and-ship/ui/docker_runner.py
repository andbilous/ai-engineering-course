"""Subprocess wrappers around docker for the Streamlit demo."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = DEMO_ROOT / "app" / "main.py"

STAGES = {
    "stage0": {
        "label": "Stage 0 · Naive",
        "dockerfile": "Dockerfile.stage0-naive",
        "image": "shrink:stage0",
        "use_dockerignore": False,
        "explainer": (
            "FROM python:3.11 (full Debian) + COPY . . + pip install. "
            "Без .dockerignore, без --no-cache-dir, без оптимізації порядку COPY. "
            "Це 80% Docker туторіалів в інтернеті."
        ),
        "details_md": """
**Dockerfile як його пишуть у 80% туторіалів:**

```dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -r app/requirements.txt
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

**Чому 1.26 GB?**
- Базовий `python:3.11` сам по собі ~1 GB — туди вже вшиті компайлери і apt-кеш
- pip складає завантажені пакети в `/root/.cache/pip` — ще +300 MB зайвого
- `COPY . .` без `.dockerignore` тягне твоє локальне `.venv`, `.git`, кеші ноутбуків

**Чому rebuild такий повільний (26 сек)?**
`COPY . .` стоїть **перед** `pip install`. Зміна одного байта в коді → Docker вирішує що все нижче треба робити заново → `pip install` йде з нуля. Замість миттєвого білду — повторне завантаження wheels.

**Чим це болить у проді:**
- Push великого image у ECR забирає хвилини, а CI робить це 50 разів на день
- Кожна правка коду = чекати повний rebuild
- Нова репліка при autoscale стартує довго (`docker pull` 1.26 GB)

Це наш baseline. Далі кожен фікс дасть наочний результат на табло.
""",
    },
    "stage1": {
        "label": "Stage 1 · Hygiene",
        "dockerfile": "Dockerfile.stage1-hygiene",
        "image": "shrink:stage1",
        "use_dockerignore": True,
        "explainer": (
            "python:3.11-slim + .dockerignore + --no-cache-dir + правильний порядок COPY. "
            "requirements.txt копіюється і встановлюється ОКРЕМО від коду — "
            "тому зміна коду не інвалідує pip install layer."
        ),
        "details_md": """
**4 простих фікси, які дають 5x менший image:**

```dockerfile
FROM python:3.11-slim                            # ← фікс 1: slim замість full
WORKDIR /app

COPY app/requirements.txt ./app/requirements.txt # ← фікс 2: спочатку лише requirements
RUN pip install --no-cache-dir \\                # ← фікс 3: без pip cache
    -r app/requirements.txt

COPY app/ ./app/                                 # ← фікс 4: код копіюється ОКРЕМО і ПІЗНІШЕ
COPY data/ ./data/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Плюс файл `.dockerignore`:
```
.venv/
__pycache__/
.git/
.env
tests/
```

**Чому це працює:**

1. **`python:3.11-slim`** — мінімальна Debian без зайвих пакетів. -800 MB одразу.
2. **`.dockerignore`** не пускає в build context твоє venv, git history, data caches. -500 MB.
3. **`--no-cache-dir`** каже pip не зберігати .whl у `/root/.cache/pip`. -200-300 MB.
4. **Порядок COPY:** requirements копіюється і встановлюється ПЕРШИМ, код — після. Тому зміна коду **не інвалідує** pip install layer → rebuild ~1.6 сек замість 26.

**Що ми отримали:**
- Image **261 MB** (vs 1.26 GB — 4.8x менше)
- Rebuild after code change **1.6 сек** (vs 26 сек — 16x швидше)
- Той самий код працює, той самий /ask відповідає
- Time витрачений на фікси: ~5 хвилин

**Це 80% результату від простої гігієни.** Multi-stage додасть ще трохи, але головну битву ми вже виграли тут.
""",
    },
    "stage2": {
        "label": "Stage 2 · Multi-stage",
        "dockerfile": "Dockerfile.stage2-multistage",
        "image": "shrink:stage2",
        "use_dockerignore": True,
        "explainer": (
            "Multi-stage: builder з компайлерами + runtime з python:3.11-slim. "
            "Plus: non-root user (useradd app), HEALTHCHECK що тестує /health → status: ok. "
            "Це production-ready Dockerfile."
        ),
        "details_md": """
**Production-ready Dockerfile з трьома додатковими шарами безпеки/контролю:**

```dockerfile
# ─── Stage 1: builder ─────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt
# ↑ Встановлюємо у /deps. Builder може мати компайлери, dev tools,
#   apt cache — все це залишиться в цій стадії і НЕ потрапить у фінал.

# ─── Stage 2: runtime ─────────────────────────────
FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 1000 app    # ← non-root user
USER app                                     # ← всі наступні команди як app, не root
WORKDIR /home/app

ENV PYTHONPATH=/deps PATH=/deps/bin:$PATH

COPY --from=builder /deps /deps              # ← беремо лише installed packages
COPY --chown=app:app app/ ./app/
COPY --chown=app:app data/ ./data/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \\
  CMD python -c "import httpx, sys; \\
    r = httpx.get('http://localhost:8000/health', timeout=3); \\
    sys.exit(0 if r.json().get('status') == 'ok' else 1)"
# ↑ Перевіряє що /health повернув status:ok (не просто HTTP 200!).
#   start-period=30s — grace period поки модель/embeddings грузяться.

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Три новинки:**

**1. Multi-stage build (`FROM ... AS builder` + `FROM ... AS runtime`)**
Builder існує лише на час build. Все що в ньому (тимчасові файли, apt cache, dev tools) **викидається**. У runtime ми **явно копіюємо** тільки те що треба: `/deps`. Якщо у тебе в requirements є `torch` чи `transformers` з компіляцією C-extensions — гcc/g++ потрібні тільки в builder, у runtime їх не буде.

**2. Non-root user (`useradd app` + `USER app`)**
Якщо хтось пробʼє Python через web vulnerability — він буде в контейнері як user `app`, не root. На Kubernetes з privileged mounts це різниця між "зламаний один pod" і "compromise host VM". Безкоштовна security win.

**3. HEALTHCHECK що перевіряє `status: ok`**
Звичайний `curl /health → 200` для AI бреше — порт відкривається ПЕРЕД завантаженням моделі/embeddings. Цей HEALTHCHECK парсить JSON і чекає на `status: ok`. `start-period=30s` критичний: без нього Docker буде вважати контейнер unhealthy одразу і рестартити в loop.

**Що ми отримали:**
- Image **251 MB** (мінус ще 10 MB у порівнянні зі stage 1 — runtime layer не має pip cache, dev metadata)
- Non-root → securit win
- HEALTHCHECK → Docker / ECS / Kubernetes знають коли сервіс реально готовий
- Cold start ~1.6 сек, /health = ok, /ask повертає реальну відповідь з OpenAI

**Це той Dockerfile який ти кладеш у репозиторій і деплоїш у прод.**
""",
    },
}


@dataclass
class BuildResult:
    success: bool
    duration_s: float
    image_size: str  # human readable e.g. "251MB"
    image_size_bytes: int
    log_lines: list[str]


def _stream_subprocess(cmd: list[str], cwd: Path) -> Iterator[str]:
    """Yield stdout lines from a subprocess in real time."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip()
    finally:
        proc.wait()
        if proc.returncode != 0:
            yield f"__EXIT_CODE__:{proc.returncode}"


def get_image_size(image: str) -> tuple[str, int]:
    """Return ('251MB', bytes) or ('—', 0) if image is missing."""
    r = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Size}}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return ("—", 0)
    try:
        size_b = int(r.stdout.strip())
    except ValueError:
        return ("—", 0)
    return (_humanize_bytes(size_b), size_b)


def _humanize_bytes(b: int) -> str:
    for unit, threshold in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if b >= threshold:
            return f"{b / threshold:.2f} {unit}"
    return f"{b} B"


def remove_dockerignore() -> Path | None:
    """Temporarily hide .dockerignore. Returns backup path so caller can restore."""
    di = DEMO_ROOT / ".dockerignore"
    if di.exists():
        backup = DEMO_ROOT / ".dockerignore.bak"
        di.rename(backup)
        return backup
    return None


def restore_dockerignore(backup: Path | None):
    if backup and backup.exists():
        backup.rename(DEMO_ROOT / ".dockerignore")


def build_stage(stage_key: str, no_cache: bool = True) -> Iterator[dict]:
    """Stream build events for a stage.

    Yields dicts: {"type": "log"|"done", ...}
    """
    stage = STAGES[stage_key]
    backup = None
    if not stage["use_dockerignore"]:
        backup = remove_dockerignore()

    try:
        cmd = ["docker", "build"]
        if no_cache:
            cmd.append("--no-cache")
        cmd.extend(["-f", stage["dockerfile"], "-t", stage["image"], "."])

        start = time.monotonic()
        log_lines: list[str] = []
        exit_code = 0
        for line in _stream_subprocess(cmd, DEMO_ROOT):
            if line.startswith("__EXIT_CODE__:"):
                exit_code = int(line.split(":")[1])
                continue
            log_lines.append(line)
            yield {"type": "log", "line": line}

        duration = time.monotonic() - start
        size_str, size_b = get_image_size(stage["image"]) if exit_code == 0 else ("—", 0)

        yield {
            "type": "done",
            "success": exit_code == 0,
            "duration_s": duration,
            "image_size": size_str,
            "image_size_bytes": size_b,
        }
    finally:
        restore_dockerignore(backup)


def touch_main_py():
    """Add/remove a harmless comment on app/main.py to trigger code-change rebuilds."""
    text = MAIN_PY.read_text()
    marker = "  # rebuild test"
    if marker in text:
        text = text.replace(marker, "")
    else:
        text = text.replace(
            'app = FastAPI(title="rag-boilerplate", lifespan=lifespan)',
            'app = FastAPI(title="rag-boilerplate", lifespan=lifespan)' + marker,
            1,
        )
    MAIN_PY.write_text(text)


def run_container(image: str, name: str, host_port: int, env_file: Path) -> str | None:
    """Start a container detached. Returns container_id or None on error."""
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    r = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", name,
            "--env-file", str(env_file),
            "-p", f"{host_port}:8000",
            image,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def wait_for_health(host_port: int, timeout_s: float = 60.0) -> float | None:
    """Poll /health until status==ok. Returns elapsed seconds or None on timeout."""
    import httpx

    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            r = httpx.get(f"http://localhost:{host_port}/health", timeout=2)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return time.monotonic() - start
        except Exception:
            pass
        time.sleep(0.2)
    return None


def ask(host_port: int, question: str) -> dict | None:
    import httpx
    try:
        r = httpx.post(
            f"http://localhost:{host_port}/ask",
            json={"question": question},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def stop_container(name: str):
    subprocess.run(["docker", "stop", name], capture_output=True)
    subprocess.run(["docker", "rm", name], capture_output=True)


def healthcheck_status(name: str) -> str | None:
    r = subprocess.run(
        ["docker", "inspect", name, "--format", "{{.State.Health.Status}}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def remove_image(image: str):
    subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


def list_built_images() -> set[str]:
    r = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
    )
    return set(r.stdout.strip().splitlines())
