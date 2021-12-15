#!/bin/bash

# exit immediately upon failure, unset vars
set -e -u

function usage() {
  echo "Usage: $(basename "$0") [-i] [-p <PY_PLATFORM>]" >&2
  echo "Note that <PY_PLATFORM> is the whole platform tag (e.g., cp310-cp310-macosx_10_9_x86_64, not just macos)." >&2
  echo "(This is just a hook for future expansion, in case we want to do platform-specific builds.)" >&2
}

INIT=false

shift $((OPTIND - 1))
if (($# != 0)); then usage && exit 1; fi

function log() {
  local FORMAT="$1"
  shift
  local MESSAGE
  MESSAGE=$(printf "$FORMAT" "$@")
  echo "$MESSAGE" >&2
}

function run() {
  local ARGS=("$@")
  log "$ %s" "${ARGS[*]}"
  eval "${ARGS[@]}"
}

function init() {
  log "Install dependencies"
  run pip install wheel
}

function build() {

  log "Build bdist"
  run \(python setup.py bdist_wheel -d wheelhouse\)

  log "Restore README.md"
  run git restore python/README.md
}

if [[ $INIT == true ]]; then
  log "***** INITIALIZING *****"
  init
fi

log "***** RUNNING BUILD *****"
build
