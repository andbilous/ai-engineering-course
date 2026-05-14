"""Push KB_V1 (lean) and KB_V2 (bloated) to Langfuse Prompt Management.

Створює один prompt 'faq-assistant' з двома версіями:
  - v1 → label "v1", "production" (активна за замовчуванням)
  - v2 → label "v2"            (доступна, але не production)

Запуск:
    cd lesson-12-mlops-aiops-foundations/demo/llmops-crisis-room
    .venv/bin/python -m scripts.upload_prompts
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Make sure we can import from project root when running as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from langfuse import Langfuse  # noqa: E402

from data.scenarios import KB_V1, KB_V2_BLOAT  # noqa: E402

PROMPT_NAME = "faq-assistant"


def main() -> None:
    lf = Langfuse()

    # Try to read existing prompt to know if anything is there
    existing_versions: list[int] = []
    try:
        existing = lf.get_prompt(PROMPT_NAME, label="latest")
        existing_versions.append(existing.version)
        print(f"ℹ️  Existing '{PROMPT_NAME}' found — latest version = {existing.version}")
    except Exception:
        print(f"ℹ️  No existing '{PROMPT_NAME}' — creating fresh.")

    # --- v1 (lean) → production ---
    v1 = lf.create_prompt(
        name=PROMPT_NAME,
        prompt=KB_V1,
        labels=["v1", "production"],
        config={"variant": "v1-lean", "owner": "lesson-12"},
        type="text",
    )
    print(f"✅ Uploaded v1: version={v1.version} · labels={v1.labels}")

    # --- v2 (bloated) → label v2 (not production yet) ---
    v2 = lf.create_prompt(
        name=PROMPT_NAME,
        prompt=KB_V2_BLOAT,
        labels=["v2"],
        config={"variant": "v2-bloated", "owner": "lesson-12"},
        type="text",
    )
    print(f"✅ Uploaded v2: version={v2.version} · labels={v2.labels}")

    print()
    print("Done. Зайди у Langfuse → Prompts → faq-assistant")
    print(f"  v1 (lean):    label = production  · {len(KB_V1)} chars")
    print(f"  v2 (bloated): label = v2          · {len(KB_V2_BLOAT)} chars")
    print()
    print("У Crisis Room кнопка '🔴 Deploy v2' переключає label 'production' з v1 на v2.")


if __name__ == "__main__":
    main()
