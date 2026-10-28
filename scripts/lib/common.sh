#!/usr/bin/env bash
# Mechanical options shared by the independent skill wrappers.
# Attack logic stays in scripts/<skill>.sh.

xsf_parse_args() {
  while (($#)); do
    case "$1" in
      --victim) VICTIM="$2"; shift 2 ;;
      --goals) GOALS_FILE="$2"; shift 2 ;;
      --n-goals) N_GOALS="$2"; shift 2 ;;
      --results) ATTACK_RESULTS_DIR="$2"; shift 2 ;;
      --workers) GOAL_WORKERS="$2"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
Usage: <skill-script> [options]
  --victim MODEL       target model id
  --goals FILE         benchmark CSV/JSON path
  --n-goals N          number of goals from the benchmark
  --results DIR        output directory for judged JSON
  --workers N          goal-level concurrency when the skill supports it
Environment variables with the same names remain supported.
EOF
        XSF_HELP=1
        export XSF_HELP
        return 0
        ;;
      *) printf 'unknown option: %s\n' "$1" >&2; return 2 ;;
    esac
  done
  : "${GOAL_WORKERS:=5}"
  [[ "$N_GOALS" =~ ^[1-9][0-9]*$ ]] || { echo "N_GOALS must be positive" >&2; return 2; }
  [[ "$GOAL_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "workers must be positive" >&2; return 2; }
  export VICTIM GOALS_FILE N_GOALS ATTACK_RESULTS_DIR GOAL_WORKERS
}
