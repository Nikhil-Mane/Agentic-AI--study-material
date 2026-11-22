# 07 · LLM Fundamentals, Prompting, Fine-tuning & Reasoning Models

You don't need to derive the math, but a senior must explain *why* models behave the way they do.

## 1. How an LLM works (plain language)
1. **Tokenisation:** text → tokens (sub-word pieces) → integer ids. "unbelievable" might be `un`+`believ`+`able`. Non-English text, code and numbers often cost more tokens.
2. **Embeddings:** each token id → a vector (list of numbers) capturing meaning. Similar meanings = nearby vectors.
3. **Transformer layers:** repeated blocks, each with
   - **Self-attention:** every token looks at all earlier tokens and decides which matter ("it" attends to "the cat"). This is how context is used.
   - **Feed-forward network:** per-token processing/knowledge storage.
4. **Output:** a probability for every possible next token. One is sampled; it's appended; repeat. **The model writes one token at a time** — that's why output tokens are slower/pricier than input tokens.
5. **Training in stages:**
   - **Pre-training:** predict next token on huge text → general knowledge & language.
   - **Supervised fine-tuning (SFT):** learn from example instructions/answers → follows instructions.
   - **Preference tuning (RLHF / RLAIF / DPO):** learn what humans (or AI judges) prefer → helpful, harmless, honest.
   - **Reasoning RL:** train on verifiable tasks (math/code) so the model learns to think step by step before answering.

### Consequences you can state in interviews
- **No built-in memory or live data:** knowledge is frozen at the training cutoff; everything else must be in the prompt (or tools).
- **Hallucination is natural:** it generates plausible continuations; truthfulness isn't guaranteed.
- **Attention cost grows with context length;** very long prompts are slower/costlier and can have "lost in the middle" effects.
- **KV cache:** the model stores attention keys/values of already-processed tokens so it doesn't recompute — the mechanism behind **prompt caching** and fast streaming.
- **Non-determinism:** sampling randomness + batching/hardware effects → same prompt, slightly different output.
- **Prompt sensitivity:** wording, order and format change results → treat prompts as code and test them.

### Sampling knobs
- **Temperature:** higher = more random. **Top-p / top-k:** restrict to likelier tokens. (Several recent models fix these; check docs.)
- Agents: you want consistency → rely on schemas, validation and evals instead of fiddling with temperature.

## 2. Model families & selection
- **Frontier/large:** best reasoning, slower, costly → planning, hard coding, ambiguous tasks.
- **Mid-tier:** best default balance for agents.
- **Small/fast:** classification, routing, extraction, high-volume sub-tasks.
- **Reasoning ("thinking") models:** spend extra tokens thinking before answering. Better on hard multi-step problems; slower/costlier; tune with an **effort** setting.
- **Open-weight models (Llama, Mistral, Qwen, DeepSeek…):** run yourself → data control, fine-tuning freedom, no per-token fee but you pay infra and ops.
- **Selection method:** build an eval on *your* tasks; test 2–3 models × effort levels; compare **cost per successful task**, latency, failure types. Public benchmarks don't predict your workload.

## 3. Prompting techniques (what still matters)
| Technique | Use | Note |
|---|---|---|
| **Clear role + goal + constraints** | always | Specific beats clever |
| **Few-shot examples** | format, tricky edge cases | 2–5 diverse examples; they bias strongly |
| **Chain-of-thought** | reasoning on non-thinking models | Modern thinking models do this internally; explicit CoT is often redundant |
| **Structured output (schema)** | machine-readable output | Prefer API-enforced schemas |
| **XML/section delimiters** | separate instructions from data | Reduces injection confusion |
| **Self-consistency / voting** | accuracy on single answers | Costs N× |
| **Prompt chaining** | decompose | See file 03 |
| **Ask for uncertainty/"say unknown"** | reduce hallucination | Give the model permission to not know |
| **Positive framing + reasons** | rules | "Do X because Y" > "NEVER do Z!!!" |
Anti-patterns: giant prompts with contradictions; shouting; stuffing every edge case; prompts nobody tests.

## 4. Fine-tuning — when and how

**Decision ladder (cheapest first):** better prompt → few-shot → RAG/tools → fine-tune → train from scratch (almost never).

| Goal | Right tool |
|---|---|
| Add *knowledge* (docs, policies, fresh facts) | **RAG** (fine-tuning knowledge is unreliable and goes stale) |
| Consistent *style/format/tone* | Fine-tune (or good prompt + examples) |
| Teach a *narrow skill* a small model must do cheaply at scale (classification, extraction, routing) | Fine-tune / **distill** a big model into a small one |
| Improve *tool-calling reliability* for your tool set | Fine-tune on successful trajectories (after prompts/descriptions are fixed) |
| Lower latency/cost at huge volume | Distillation to a smaller model |

Vocabulary:
- **Full fine-tune:** update all weights; expensive.
- **PEFT / LoRA / QLoRA:** train small adapter matrices (a fraction of 1% of params) → cheap, swappable per tenant/task. QLoRA adds 4-bit quantisation of the base model for low memory.
- **SFT:** supervised on (prompt → ideal answer) pairs.
- **Preference optimisation (RLHF / DPO):** learn from "A is better than B" comparisons.
- **Distillation:** small "student" learns from a big "teacher's" outputs.
- **Catastrophic forgetting:** fine-tuning can erode general ability; mitigate with mixed data/LoRA.
- **Data quality dominates:** 500–5,000 *clean, diverse* examples beat 50k noisy ones. Hold out an eval set. Check for leakage.
- **Hosted fine-tuning vs self-hosted:** hosted = easy, limited control; self-hosted = full control, more ops.

Honest senior line: *"I'd exhaust prompting, tool design and retrieval first, with evals showing the gap. Fine-tuning is for stable, narrow, high-volume needs where a small model can match the big one."*

## 5. Embeddings & vector search (basics; deep dive in file 08)
- Embedding model turns text → vector; **cosine similarity** measures closeness.
- Use for semantic search, clustering, dedupe, classification, routing.
- Index types: **flat** (exact, small data), **HNSW** (fast approximate, default), **IVF/PQ** (huge data, compressed). Trade recall ↔ speed ↔ memory.
- Don't mix embeddings from different models; re-embed when you change models.

## 6. Multimodal
Vision (images, PDFs, screenshots), audio (speech-to-text/text-to-speech), video. Agent uses: read invoices/charts, GUI agents see screenshots, voice assistants. Costs: images consume tokens by size; resize. Risks: **injection via images** (hidden text), PII in images.

## 7. Evaluating *models* vs *systems*
Benchmarks (MMLU, GPQA, SWE-bench, τ-bench for tool-use agents, GAIA, HumanEval/LiveCodeBench, BrowseComp…) show rough capability but suffer from contamination and don't match your task. Always evaluate the **whole system** (prompt + tools + retrieval + model) on your data.

## 8. Self-check
1. Why are output tokens slower than input tokens?
2. What does the KV cache have to do with prompt caching?
3. A stakeholder says "fine-tune the model on our wiki so it knows our policies." What do you say?
4. LoRA in two sentences.
5. How do you choose among three models for an agent?
