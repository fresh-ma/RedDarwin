# Plan — CipherChat (2308.06463) finalize → XSafeBench

## Self-set goal (matching DAN / ReNeLLM rhythm)
A faithful, **GLM-audited**, self-contained black-box unit: full bilingual dataset, official
cipher transforms verbatim, **v4-flash target + judge**, audited canonical ASR, red-team
capability tagged, deliverable report. Promote to xsafebench **only after the audit passes**.

## Already done (verified this session)
- **Dataset**: `data/cipherchat_safety_bench_en_zh.json` = full **5572** rows (EN 2786 + ZH 2786,
  14 domains, `goal` field) — the official `data_en_zh.dict` un-pickled to readable JSON. ✓
- **attack.py**: 7 ciphers verbatim from `RobustNLP/CipherChat` (selfcipher=`unchange`, caesar
  shift-3, atbash, morse, ascii, unicode, baseline); 3-part system prompt (behavior + cipher
  teaching + 3 enciphered unsafe demos + trailer); rule-decode before judging; **dual-metric
  judge** (`refused`/`harmful`, goal-fidelity wording). Judge default already `v4-flash`. ✓
- `data/official_prompts_pack.json` = official system_role_prompts + demonstrations + trailer. ✓
- **Stale**: 2 old runs used `deepseek-chat` target (Crimes 0.65 / Insult 0.75), **not v4-flash,
  not GLM-audited**; SKILL.md frontmatter still says `target_default: deepseek-chat`; no
  `red_team_capability.json`.

## Steps
1. **Align defaults** → target `deepseek/deepseek-v4-flash` (SKILL.md frontmatter + What/Run).
2. **Canonical stratified run** (v4-flash target + judge, dual-metric, 0-error):
   SelfCipher + Caesar + ASCII + Atbash × Crimes(EN) + Insult(EN), 15 cases each
   = **120 cases**, + SelfCipher on 2 ZH domains (bilingual evidence). Save to `results/`.
3. **GLM adversarial audit** of every success (refused=false & harmful=true): catch
   goal-fidelity false positives (per `judge-overcount-even-goal-fidelity` — even goal-fidelity
   judges over-count). Corrected canonical ASR + per-case verdict file.
4. **red_team_capability.json**: `red_team_capability=true`, **`has_training_corpus="no"`**
   (CipherChat has NO SFT / no LLM-generated corpus / no attacker-LLM rewrites — honest).
   capabilities = [bilingual safety benchmark 5572 (harmful questions, 14 domains, EN+ZH),
   official cipher-attack template pack (7 cipher-expert system prompts + 3 unsafe demos + trailer)].
5. **RESULT_<date>.md** (raw + GLM-audited) + update SKILL.md (status, result, report pointer).
6. **Deliverable index.html** at paper level — I prepare the content/data; GLM builds the styled
   HTML (particles/format) per your note.
7. **Promote** → `xsafebench/jailbreak-attack/Black-box/Single-turn/Encoding-Linguistic/2308.06463_CipherChat/` after audit passes.

## Not doing
- No GPU / weights (pure black-box). No full 5572×7-cipher sweep (cost) — stratified canonical.
- No fabricated "training corpus" — CipherChat genuinely has none.
