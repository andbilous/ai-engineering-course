# Personal Finance Coach — Homework Plan

## Decisions Summary

| Decision | Choice |
|----------|--------|
| Framework | LangGraph |
| Agent count | 3 (Analyst, Advisor, Synthesizer) |
| Routing | Synthesizer as router (classifies, then routes) |
| Tools | 8 tools |
| Multi-turn | MemorySaver checkpointer |
| UI language | Ukrainian |
| Model | gemini-2.0-flash (all same) |
| LangSmith | Step-by-step guidance included |
| Plan file | `homework/PLAN.md` |
| Parallel | Analyst + Advisor fan-out in parallel |

---

## Architecture

```
START ──► Synthesizer (classify + route) ──┬──► Analyst  ──┐
                                           ├──► Advisor  ──┼──► Synthesizer (combine) ──► END
                                           └──► both (parallel) ─┘
```

**3 Agents:**

| Agent | Role | Tools |
|-------|------|-------|
| **Synthesizer** | Classifies query, routes to specialist(s), combines results, generates final answer, handles out-of-scope | None (LLM only) |
| **Analyst** | Factual spending queries: amounts, categories, merchants, trends, comparisons | `query_transactions`, `aggregate_by_category`, `aggregate_by_merchant`, `get_monthly_summary`, `compare_periods` |
| **Advisor** | Savings recommendations, subscription audit, pattern detection, fraud handling | `query_transactions`, `aggregate_by_category`, `get_subscription_report`, `detect_patterns`, `detect_fraud` |

---

## Directory Structure

```
homework/
├── .env.example
├── requirements.txt
├── Makefile
├── app.py                          # Streamlit UI (main entry)
├── PLAN.md                         # This file
├── src/
│   ├── __init__.py
│   ├── llm.py                      # OpenRouter client + LLMUsage
│   ├── schemas.py                  # Pydantic/TypedDict models
│   ├── tools/
│   │   ├── __init__.py             # TOOL_SCHEMAS + registry
│   │   └── transaction_tools.py    # 8 tool functions
│   ├── agents/
│   │   ├── __init__.py
│   │   └── workers.py              # 3 agent functions + shared helpers
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── crew.py                 # LangGraph graph (3 agents, parallel fan-out)
│   │   └── baseline.py             # Single-agent baseline
│   ├── judge.py                    # LLM-as-judge
│   └── viz.py                      # Agent flow visualization
├── eval/
│   ├── __init__.py
│   ├── golden_set.py               # 16 test cases
│   └── evaluators.py               # Custom LangSmith evaluators
└── starter/
    └── data/
        ├── generate.py             # (do NOT modify)
        └── transactions.csv        # (do NOT modify)
```

**20 new files. No files modified outside `homework/`.**

---

## Phase 1: Scaffolding (Steps 1-4)

### Step 1 — Create directories and config files
- Create `homework/src/`, `homework/src/tools/`, `homework/src/agents/`, `homework/src/graph/`, `homework/eval/`
- Create `homework/.env.example`:
  ```
  OPENROUTER_API_KEY=
  MODEL=google/gemini-2.0-flash-001
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=
  LANGCHAIN_PROJECT=finance-coach-homework
  ```
- Create `homework/requirements.txt`:
  ```
  streamlit>=1.40
  openai>=1.50
  langgraph>=0.2.50
  python-dotenv>=1.0
  pandas>=2.0
  langsmith>=0.1.0
  pydantic>=2.0
  ```
- Create `homework/Makefile` (adapted from demo/supply-chain for Windows/PowerShell)
- Create all `__init__.py` files

### Step 2 — `src/llm.py`
Follow `demo/supply-chain/src/llm.py` exactly:
- `get_client()` — OpenAI client at `https://openrouter.ai/api/v1`
- `LLMUsage` dataclass with `add(agent, input_t, output_t, cost, ms)` and `by_agent` dict
- `estimate_cost(model, input_tokens, output_tokens)` with pricing table
- `call_llm(messages, agent_name, usage, tools?, model?, temperature?)`

### Step 3 — `src/schemas.py`
```python
class FinanceState(TypedDict, total=False):
    query: str
    thread_id: str                    # for MemorySaver
    route_decision: str               # "stats" | "savings" | "fraud" | "multi_step" | "out_of_scope"
    stats_result: dict | None
    savings_result: dict | None
    fraud_result: dict | None
    final_answer: str
    usage: LLMUsage
```

### Step 4 — `src/tools/transaction_tools.py`
Load `transactions.csv` with pandas at module level. Implement 8 functions:

| # | Function | Parameters | Returns |
|---|----------|-----------|---------|
| 1 | `query_transactions` | `category?, merchant?, start_date?, end_date?, account?` | Filtered transaction list |
| 2 | `aggregate_by_category` | `start_date?, end_date?` | `{category: total}` sorted desc |
| 3 | `aggregate_by_merchant` | `category?, start_date?, end_date?` | `{merchant: {total, count}}` |
| 4 | `get_monthly_summary` | `year?, month?` | `{income, expenses, net, top_categories}` |
| 5 | `compare_periods` | `start1, end1, start2, end2` | `{period1: {...}, period2: {...}, changes: {...}}` |
| 6 | `get_subscription_report` | none | `{subscriptions: [...], total_monthly, forgotten: [...]}` |
| 7 | `detect_patterns` | `pattern_type?` | Late-night %, weekend spike, coffee trend, credit behavior |
| 8 | `detect_fraud` | none | Suspicious foreign transactions (Booking.com, AliExpress) |

All return dicts (JSON-serializable). Use `abs()` for expense totals (amounts are negative for expenses).

---

## Phase 2: Agents (Steps 5-7)

### Step 5 — `src/tools/__init__.py`
Export `TOOL_SCHEMAS` (OpenAI function-calling JSON format) and `TOOL_REGISTRY` dict.

### Step 6 — `src/agents/workers.py`
Shared helpers (from `demo/supply-chain/src/agents/workers.py`):
- `_execute_tool_calls(tool_calls)` — list of tool results
- `_run_agent(agent_name, system_prompt, user_prompt, tool_names, usage, max_iterations=5)` — dict

**3 agent functions:**

**`synthesizer_agent(query, conversation_history, stats_result?, savings_result?, fraud_result?, usage)`**
- System prompt includes: friendly Ukrainian tone, multi-turn context, out-of-scope rejection, fraud escalation, no hallucinations, all numbers from real data
- First call (no specialist results): classifies query and returns `route_decision`
- Second call (with specialist results): combines into final answer

**`analyst_agent(query, usage)`**
- System prompt: "Ти Financial Analyst. Відповідаєш на конкретні запити про витрати..."
- Tools: `query_transactions`, `aggregate_by_category`, `aggregate_by_merchant`, `get_monthly_summary`, `compare_periods`

**`advisor_agent(query, usage)`**
- System prompt: "Ти Savings Advisor. Даєш конкретні поради щодо економії..."
- Tools: `query_transactions`, `aggregate_by_category`, `get_subscription_report`, `detect_patterns`, `detect_fraud`

### Step 7 — `src/graph/crew.py`
LangGraph graph with 3 nodes + parallel fan-out:

```python
def build_graph():
    graph = StateGraph(FinanceState)
    graph.add_node("synthesizer_route", synthesizer_route_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("advisor", advisor_node)
    graph.add_node("synthesizer_final", synthesizer_final_node)
    
    graph.add_edge(START, "synthesizer_route")
    graph.add_conditional_edges(
        "synthesizer_route",
        route_after_synthesizer,
        ["analyst", "advisor", "synthesizer_final"],
    )
    # Parallel fan-out: both specialists -> synthesizer_final
    graph.add_edge("analyst", "synthesizer_final")
    graph.add_edge("advisor", "synthesizer_final")
    graph.add_edge("synthesizer_final", END)
    
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
```

**Routing logic:**
- `"stats"` — only Analyst
- `"savings"` or `"fraud"` — only Advisor
- `"multi_step"` — Analyst + Advisor (parallel)
- `"out_of_scope"` — directly to Synthesizer final (no specialists)

### Step 8 — `src/graph/baseline.py`
Single-agent baseline following `demo/supply-chain/src/graph/baseline.py`:
- One system prompt covering all capabilities
- All 8 tools available
- Sequential tool-use loop (max 8 iterations)
- Same `LLMUsage` tracking

---

## Phase 3: UI (Steps 9-12)

### Step 9 — `src/viz.py`
Agent flow visualization following `demo/supply-chain/src/viz.py`:
```python
AGENT_INFO = {
    "user":        {"emoji": "👤", "name": "User",        "sub": "ваш запит"},
    "synthesizer": {"emoji": "🧩", "name": "Synthesizer", "sub": "класифікація + відповідь"},
    "analyst":     {"emoji": "📊", "name": "Analyst",     "sub": "дані та факти"},
    "advisor":     {"emoji": "💰", "name": "Advisor",     "sub": "поради та безпека"},
}
```

### Step 10 — `src/judge.py`
LLM-as-judge following `demo/supply-chain/src/judge.py`:
- 4 criteria (0-10 each): groundedness, specificity, actionability, tone
- JSON output format with scores, reasons, winner, verdict
- Separate model (same gemini-2.0-flash, but separate call to avoid bias)

### Step 11 — `app.py`
Streamlit UI following `demo/supply-chain/app.py`:

**Layout:**
- Sidebar: architecture selector (Crew / Baseline / Both), input field, Submit
- Main: response display, expandable trace, cost metrics
- Tabs: "Запит" (query) and "Оцінка" (eval)

**Features:**
1. Text input + Submit button
2. Response with cost/token/latency metrics
3. Expandable trace showing agent calls, tool invocations
4. Architecture selector radio: `Crew (3 агенти)` / `Baseline (1 агент)` / `Обидві`
5. Mermaid graph display in sidebar

### Step 12 — Manual testing
Test both architectures with sample queries before golden set.

---

## Phase 4: Evaluation (Steps 13-17)

### Step 13 — `eval/golden_set.py`
16 test cases:

| # | Query | Route | Difficulty |
|---|-------|-------|-----------|
| 1 | "Скільки витратив на каву минулого тижня?" | stats | easy |
| 2 | "Топ-5 категорій витрат за червень" | stats | easy |
| 3 | "Дата останнього платежу за Netflix?" | stats | easy |
| 4 | "Скільки на доставку пішло у жовтні?" | stats | easy |
| 5 | "Яка середня сума транзакції у вихідні vs будні?" | stats | medium |
| 6 | "Скільки я заробітав за весь період?" | stats | medium |
| 7 | "Де можна зекономити $200 цього місяця?" | savings | medium |
| 8 | "На які підписки витрачається найбільше та чи всі вони необхідні?" | savings | medium |
| 9 | "Як швидше виплатити кредитну картку?" | savings | hard |
| 10 | "Скільки я витрачаю на доставку після 21:00?" | savings | medium |
| 11 | "Чи є забуті підписки?" | savings | easy |
| 12 | "Порівняти витрати першого кварталу з другим" | multi_step | hard |
| 13 | "Якщо зменшити витрати на доставку вдвічі — яка економія за рік?" | multi_step | hard |
| 14 | "Заблокуй мою картку" | out_of_scope | easy |
| 15 | "На моїй карті $890 в Booking.com, я не робила цю транзакцію" | fraud | medium |
| 16 | "Купи мені акції Tesla" | out_of_scope | easy |

Each has: `query`, `category`, `expected_route`, `expected_patterns` (list), `difficulty`.

### Step 14 — `eval/evaluators.py`
Custom evaluators:
1. `groundedness` — numeric claims match actual data
2. `tool_selection_accuracy` — correct tools called for query type
3. `success_rate` — LLM-as-judge: does answer address the question?
4. `inter_agent_overhead_pct` — context-passing tokens / total tokens (crew only)
5. `cost_breakdown_by_agent` — from LLMUsage.by_agent

### Step 15 — LangSmith setup (step-by-step)
1. Create account at smith.langchain.com
2. Get API key from Settings > API Keys
3. Set environment variables in `.env`
4. Install `langsmith` package
5. Create Dataset via LangSmith UI or Python SDK
6. Upload golden set tasks as examples
7. Run Experiments: crew vs baseline on same dataset
8. Compare results in LangSmith Experiments UI

### Step 16 — Run golden set
- Execute all 16 tasks through both architectures
- Collect all metrics
- Generate comparison tables

### Step 17 — `REPORT.md`
```markdown
# Personal Finance Coach — Звіт

## Архітектура
- 3 агенти: Synthesizer (router + final), Analyst, Advisor
- Parallel fan-out для multi-step запитів
- MemorySaver для multi-turn контексту

## Метрики (LangSmith)
| Метрика | Crew | Baseline | Ratio |
|---------|------|----------|-------|
| latency_p50 | ... | ... | ... |
| latency_p95 | ... | ... | ... |
| cost_per_task | ... | ... | ... |
| tokens_per_task | ... | ... | ... |

## Якість
| Метрика | Crew | Baseline | Winner |
|---------|------|----------|--------|
| success_rate | ... | ... | ... |
| tool_selection_accuracy | ... | ... | ... |
| groundedness | ... | ... | ... |

## Multi-agent specific
| Метрика | Значення |
|---------|----------|
| inter_agent_overhead_pct | ... |
| cost_breakdown_by_agent | ... |

## Висновки
- Де multi-agent виграє
- Де baseline виграє
- Рекомендації для production

## Обмеження та труднощі
- Що не вдалося і чому
```

---

## Implementation Order

| Step | Task | Creates |
|------|------|---------|
| 1 | Scaffold dirs + config | .env.example, requirements.txt, Makefile, __init__.py files |
| 2 | LLM client | src/llm.py |
| 3 | Schemas | src/schemas.py |
| 4 | Transaction tools (8 tools) | src/tools/transaction_tools.py, src/tools/__init__.py |
| 5 | Agent workers (3 agents) | src/agents/workers.py, src/agents/__init__.py |
| 6 | LangGraph crew | src/graph/crew.py, src/graph/__init__.py |
| 7 | Baseline | src/graph/baseline.py |
| 8 | Manual test | — |
| 9 | Viz | src/viz.py |
| 10 | Judge | src/judge.py |
| 11 | Streamlit UI | app.py |
| 12 | Test UI | — |
| 13 | Golden set | eval/golden_set.py, eval/__init__.py |
| 14 | Evaluators | eval/evaluators.py |
| 15 | LangSmith setup | .env updated with keys |
| 16 | Run golden set | — |
| 17 | Report | REPORT.md |

---

## Files to Create (Summary)

| File | Purpose |
|------|---------|
| `homework/.env.example` | Environment template |
| `homework/requirements.txt` | Dependencies |
| `homework/Makefile` | Build/run targets |
| `homework/app.py` | Streamlit UI (main entry point) |
| `homework/src/__init__.py` | Package init |
| `homework/src/llm.py` | OpenRouter LLM client |
| `homework/src/schemas.py` | Pydantic/TypedDict models |
| `homework/src/tools/__init__.py` | Tool exports + TOOL_SCHEMAS |
| `homework/src/tools/transaction_tools.py` | Data query functions |
| `homework/src/agents/__init__.py` | Agent exports |
| `homework/src/agents/workers.py` | 3 agent functions |
| `homework/src/graph/__init__.py` | Graph exports |
| `homework/src/graph/crew.py` | LangGraph multi-agent graph |
| `homework/src/graph/baseline.py` | Single-agent baseline |
| `homework/src/judge.py` | LLM-as-judge evaluator |
| `homework/src/viz.py` | Agent flow visualization |
| `homework/eval/__init__.py` | Eval exports |
| `homework/eval/golden_set.py` | 16 test cases |
| `homework/eval/evaluators.py` | Custom LangSmith evaluators |
| `homework/REPORT.md` | Final report with metrics |

**Total: 20 new files** inside `homework/` only. No files modified outside `homework/`.

---

## Files NOT to Touch

- `homework/README.md` — the assignment prompt (read-only)
- `homework/starter/data/generate.py` — data generator (read-only)
- `homework/starter/data/transactions.csv` — transaction data (read-only)
- Any file outside `lesson-11-ai-agents-tool-orchestration/homework/`
