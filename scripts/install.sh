#!/bin/sh
# Install or remove Toss host-adapter symlinks without modifying the Toss CLI.
set -eu

usage() {
  cat >&2 <<'EOF'
usage: scripts/install.sh [--bin-dir DIR] [--skill-dir DIR] [--uninstall | --diagnose]

Installs toss-claude, toss-codex, toss-tfcode, and toss-recover as symlinks.
By default links are written to ~/.local/bin. The canonical `toss` executable
must already be available on PATH (for example: python3 -m pip install .).
When --skill-dir is provided, also links this repository at DIR/toss so an
agent host can discover SKILL.md.
EOF
  exit "${1:-64}"
}

mode=install
bin_dir="${HOME}/.local/bin"
skill_dir=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --bin-dir)
      [ "$#" -ge 2 ] || usage
      bin_dir=$2
      shift 2
      ;;
    --skill-dir)
      [ "$#" -ge 2 ] || usage
      skill_dir=$2
      shift 2
      ;;
    --uninstall) mode=uninstall; shift ;;
    --diagnose) mode=diagnose; shift ;;
    -h|--help) usage 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage ;;
  esac
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(CDPATH= cd -- "${script_dir}/.." && pwd -P)
adapter_dir="${root_dir}/adapters"
names='toss-claude toss-codex toss-tfcode toss-recover'
skill_link=
[ -z "$skill_dir" ] || skill_link="${skill_dir}/toss"

canonical_path() {
  # `readlink -f` is not portable on macOS. Python is already required by Toss.
  python3 - "$1" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
}

diagnose_link() {
  name=$1
  target="${adapter_dir}/${name}"
  link="${bin_dir}/${name}"
  if [ ! -e "$target" ]; then
    printf 'ERROR  source missing: %s\n' "$target" >&2
    return 1
  fi
  if [ -L "$link" ]; then
    actual=$(canonical_path "$link")
    expected=$(canonical_path "$target")
    if [ "$actual" = "$expected" ]; then
      printf 'OK     %s -> %s\n' "$link" "$actual"
    else
      printf 'BROKEN %s points to %s; expected %s\n' "$link" "$actual" "$expected" >&2
      return 1
    fi
  elif [ -e "$link" ]; then
    printf 'CONFLICT %s exists and is not a Toss adapter symlink\n' "$link" >&2
    return 1
  else
    printf 'MISSING %s\n' "$link" >&2
    return 1
  fi
}

diagnose_skill() {
  [ -n "$skill_link" ] || return 0
  if [ -L "$skill_link" ]; then
    actual=$(canonical_path "$skill_link")
    expected=$(canonical_path "$root_dir")
    if [ "$actual" = "$expected" ]; then
      printf 'OK     %s -> %s\n' "$skill_link" "$actual"
    else
      printf 'BROKEN %s points to %s; expected %s\n' "$skill_link" "$actual" "$expected" >&2
      return 1
    fi
  elif [ -e "$skill_link" ]; then
    printf 'CONFLICT %s exists and is not the Toss skill symlink\n' "$skill_link" >&2
    return 1
  else
    printf 'MISSING %s\n' "$skill_link" >&2
    return 1
  fi
}

case "$mode" in
  diagnose)
    failed=0
    for name in $names; do diagnose_link "$name" || failed=1; done
    diagnose_skill || failed=1
    exit "$failed"
    ;;
  uninstall)
    for name in $names; do
      target="${adapter_dir}/${name}"
      link="${bin_dir}/${name}"
      if [ -L "$link" ] && [ "$(canonical_path "$link")" = "$(canonical_path "$target")" ]; then
        rm -- "$link"
        printf 'Removed %s\n' "$link"
      elif [ -e "$link" ] || [ -L "$link" ]; then
        printf 'Skipped %s (not a Toss adapter symlink)\n' "$link" >&2
      fi
    done
    if [ -n "$skill_link" ]; then
      if [ -L "$skill_link" ] && [ "$(canonical_path "$skill_link")" = "$(canonical_path "$root_dir")" ]; then
        rm -- "$skill_link"
        printf 'Removed %s\n' "$skill_link"
      elif [ -e "$skill_link" ] || [ -L "$skill_link" ]; then
        printf 'Skipped %s (not the Toss skill symlink)\n' "$skill_link" >&2
      fi
    fi
    ;;
  install)
    if ! command -v toss >/dev/null 2>&1; then
      printf 'Canonical toss executable is not on PATH; install the package first.\n' >&2
      exit 1
    fi
    # Preflight every destination before creating anything so a late conflict
    # cannot leave a partial multi-adapter installation behind.
    for name in $names; do
      target="${adapter_dir}/${name}"
      link="${bin_dir}/${name}"
      [ -f "$target" ] || { printf 'Missing adapter source: %s\n' "$target" >&2; exit 1; }
      if [ -L "$link" ] && [ "$(canonical_path "$link")" != "$(canonical_path "$target")" ]; then
        printf 'Refusing to replace symlink not owned by Toss: %s\n' "$link" >&2
        exit 1
      elif [ -e "$link" ] && [ ! -L "$link" ]; then
        printf 'Refusing to replace existing file: %s\n' "$link" >&2
        exit 1
      fi
    done
    if [ -n "$skill_link" ]; then
      if [ -L "$skill_link" ] && [ "$(canonical_path "$skill_link")" != "$(canonical_path "$root_dir")" ]; then
        printf 'Refusing to replace skill symlink not owned by Toss: %s\n' "$skill_link" >&2
        exit 1
      elif [ -e "$skill_link" ] && [ ! -L "$skill_link" ]; then
        printf 'Refusing to replace existing skill path: %s\n' "$skill_link" >&2
        exit 1
      fi
    fi
    mkdir -p -- "$bin_dir"
    [ -z "$skill_dir" ] || mkdir -p -- "$skill_dir"
    for name in $names; do
      target="${adapter_dir}/${name}"
      link="${bin_dir}/${name}"
      chmod +x "$target"
      if [ -L "$link" ]; then
        if [ "$(canonical_path "$link")" = "$(canonical_path "$target")" ]; then
          printf 'Already installed %s\n' "$link"
          continue
        fi
        printf 'Refusing to replace symlink not owned by Toss: %s\n' "$link" >&2
        exit 1
      fi
      if [ -e "$link" ]; then
        printf 'Refusing to replace existing file: %s\n' "$link" >&2
        exit 1
      fi
      ln -s "$target" "$link"
      printf 'Installed %s -> %s\n' "$link" "$target"
    done
    if [ -n "$skill_link" ]; then
      if [ -L "$skill_link" ]; then
        if [ "$(canonical_path "$skill_link")" = "$(canonical_path "$root_dir")" ]; then
          printf 'Already installed %s\n' "$skill_link"
        else
          printf 'Refusing to replace skill symlink not owned by Toss: %s\n' "$skill_link" >&2
          exit 1
        fi
      elif [ -e "$skill_link" ]; then
        printf 'Refusing to replace existing skill path: %s\n' "$skill_link" >&2
        exit 1
      else
        ln -s "$root_dir" "$skill_link"
        printf 'Installed %s -> %s\n' "$skill_link" "$root_dir"
      fi
    fi
    ;;
esac
