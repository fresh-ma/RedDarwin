# Environment

This method is self-contained under `cia-context/` and follows the XSkillLib
convention:

- Python: `>=3.11`, one shared venv at the XSkillForge repo root
  (`XSkillForge/.venv`) — run everything with that interpreter (`$PY`), no
  `uv run`, no per-skill venv.
- Dependencies: `openai` (already in the shared venv).
- API: OpenRouter-compatible chat completions.
- Required variables: `OPENROUTER_API_KEY`, optional `OPENROUTER_BASE_URL`.

`scripts/cia.py` (`load_env_files`) walks up from this method directory through
every ancestor and loads the first `.env` it finds, so keys live in the global
`XSkillForge/.env` — no per-skill `.env`, no manual `export`.
