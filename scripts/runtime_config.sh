#!/usr/bin/env bash
# Shared resolution and honest diagnosis for the untracked runtime configuration.
#
# Why this exists: `data/` is untracked (it holds the private source manifest, the
# private study config and the ignored runtime env), so a *fresh Git worktree* has
# no `data/config/` at all. A runtime started from `.worktrees/<name>/` therefore
# reported `missing <source manifest>` on every tick -- a true sentence about the
# wrong thing, and a dead end, because copying or generating a manifest is exactly
# what a collection wrapper must never do.
#
# Sourced, never executed, by the collect wrappers. Requires the caller to pass its
# own checkout root, so a sourced helper cannot silently adopt somebody else's.
#
#   laclaugpt_runtime_config_root <checkout-root>
#       Print the root whose `data/config/` holds the private configuration.
#       Defaults to the checkout itself, so every existing installation keeps its
#       current paths. `LACLAUGPT_RUNTIME_CONFIG_ROOT` repoints it explicitly --
#       that is how a worktree runtime uses the main checkout's configuration
#       instead of copying a manifest into the worktree.
#       It moves the *configuration* only: the record/data root stays
#       `LACLAUGPT_DATA_ROOT`, whatever this resolves to.
#
#   laclaugpt_main_checkout_root <checkout-root>
#       Print the main working tree when <checkout-root> is a linked Git worktree
#       (`.git` points at `<main>/.git/worktrees/<name>`, i.e. `rev-parse --git-dir`
#       differs from `--git-common-dir`). Return 1 for a main checkout, so callers
#       cannot mistake "no private config here" for "this checkout cannot have one".
#
#   laclaugpt_missing_runtime_config <label> <path> [checkout-root] [doc-hint]
#       Report a missing private runtime file and return 2. Fail closed either way:
#       the sampling decision stays a hard stop, and no file is ever generated,
#       copied or borrowed from a sibling checkout.

#: Absolute form of a path, resolved against a base directory.
laclaugpt_absolute_path() {
  local path="$1" base="${2:-$PWD}"
  case "$path" in
    /*) (cd "$path" && pwd) 2>/dev/null ;;
    *) (cd "$base/$path" && pwd) 2>/dev/null ;;
  esac
}

laclaugpt_runtime_config_root() {
  local root="$1"
  printf '%s\n' "${LACLAUGPT_RUNTIME_CONFIG_ROOT:-$root}"
}

laclaugpt_main_checkout_root() {
  local root="${1:-}" git_dir common_dir pointer
  [[ -n "$root" && -e "$root/.git" ]] || return 1

  git_dir=$(git -C "$root" rev-parse --git-dir 2>/dev/null) || git_dir=""
  common_dir=$(git -C "$root" rev-parse --git-common-dir 2>/dev/null) || common_dir=""
  if [[ -n "$git_dir" && -n "$common_dir" ]]; then
    git_dir=$(laclaugpt_absolute_path "$git_dir" "$root") || return 1
    common_dir=$(laclaugpt_absolute_path "$common_dir" "$root") || return 1
    # A linked worktree keeps one repository in the main checkout's common dir but
    # uses its own git dir under `.git/worktrees/<name>`.
    [[ "$git_dir" != "$common_dir" ]] || return 1
    (cd "$(dirname "$common_dir")" && pwd) || return 1
    return 0
  fi

  # Cron's minimal PATH may carry no git binary, so fall back to the pointer file a
  # linked worktree has instead of a `.git` directory.
  [[ -f "$root/.git" ]] || return 1
  pointer=$(sed -n 's/^gitdir:[[:space:]]*//p' "$root/.git" | head -n 1)
  [[ -n "$pointer" ]] || return 1
  case "$pointer" in
    */.git/worktrees/*) (cd "${pointer%%/.git/worktrees/*}" && pwd) 2>/dev/null ;;
    *) return 1 ;;
  esac
}

laclaugpt_missing_runtime_config() {
  local label="$1" path="$2"
  local root="${3:-${ROOT:-${ROOT_DIR:-$PWD}}}"
  local hint="${4:-docs/brazil26-localhost.md}"
  local main_root="" candidate="" presence=unknown

  echo "missing $label: $path" >&2

  if main_root=$(laclaugpt_main_checkout_root "$root"); then
    case "$path" in
      */data/config/*) candidate="$main_root/data/config/${path##*/data/config/}" ;;
    esac
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      presence=present
    elif [[ -n "$candidate" ]]; then
      presence=absent
    fi

    echo "$root is a linked Git worktree. Its data/ tree is untracked, so a fresh" >&2
    echo "worktree does not contain it and a runtime rooted here can never own the" >&2
    echo "private configuration above -- this is a checkout that cannot have the" >&2
    echo "file, not a sampling decision that was skipped." >&2
    echo "The private configuration belongs to the main checkout:" >&2
    echo "  $main_root" >&2
    case "$presence" in
      present) echo "  it is there: $candidate" >&2 ;;
      absent)
        echo "  it is not there either: $candidate" >&2
        echo "  so the decision is genuinely absent and still a hard stop" >&2
        ;;
    esac
    echo "Point this runtime at that configuration instead of copying a file into the" >&2
    echo "worktree:" >&2
    echo "  LACLAUGPT_RUNTIME_CONFIG_ROOT=$main_root" >&2
    echo "Set LACLAUGPT_DATA_ROOT=$main_root/data as well if the corpus must stay in" >&2
    echo "one root; the configuration root does not move the data root." >&2
    echo "See $hint." >&2
  fi

  echo "refusing to run: this wrapper never generates, copies or borrows a manifest," >&2
  echo "study config or runtime env (exit 2)." >&2
  return 2
}
