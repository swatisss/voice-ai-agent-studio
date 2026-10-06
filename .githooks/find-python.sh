# Sourced by hooks: sets PY to a working Python 3 command (skips the Windows Store stub).
PY=""
for cand in "py -3" python3 python; do
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
