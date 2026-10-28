# RECORDING.md — Campaign Record Rules

Every victim attempt produces one `trail_NNN.json` in the goal directory,
numbered consecutively per goal (`trail_001.json`, ...). Records conform to
`schemas/trail.schema.json`.

## Per-attempt fields

- `trail_id`, `goal_id`, `attempt` (1-based within the goal)
- `timestamp` (ISO-8601, written before dispatch), `duration_s`
- `target`: model, provider route, temperature, max_tokens
- `attack`: skill id, variant, parameters, modules reused, and a `rationale`
  written **before dispatch** explaining why this approach fits this attempt
- `prompt`: the exact messages sent to the victim (full content)
- `response`: the exact victim output text (or `error` object on failure)
- `victim_calls`: always 1 for a dispatched attempt; the reservation is
  persisted (this file, with `response: null`) before the request is sent
- `judge`: model, score, success, rationale (filled after judging)
- `outcome`: `success` | `refusal` | `partial` | `error` | `infra_error`

## Rules

1. Persist the trail file (with rationale and prompt, response null) BEFORE
   sending the victim request. Fill the response after it returns.
2. Automatic victim retries are disabled. A failed/uncertain dispatch still
   consumes its budget unit; a retry is a NEW attempt with a new trail file.
3. Preserve refusals and errors verbatim; never delete or rewrite a trail.
4. Judge calls are separate from victim budget. Judge inputs are built from
   stored trails (`judge_input.json` per goal); interrupted judging resumes
   with `--retry-missing`, never by re-calling the victim.
5. All paths in records are relative to `redteaming/` so the folder is
   portable.

## Resume

Budget is reconstructed from existing trail files: `victim_calls_used` =
number of trails with `victim_calls: 1`. An attempt whose trail has
`response: null` and no error was interrupted mid-dispatch — it counts as
consumed and is not silently re-sent.
