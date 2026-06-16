#!/usr/bin/env bash
# Post-task cleanup (wired as a Stop hook). Conservative + safe:
#   1. git worktree prune (drop stale admin records)
#   2. remove worktrees under .claude/worktrees that are REDUNDANT:
#        clean working tree  AND  no live process rooted in them
#        AND every commit is already in the default branch (by patch-id, so
#        rebased/merged work counts as redundant). git cherry failure => keep.
#   3. kill processes orphaned by a deleted worktree dir (cwd shows "(deleted)"
#        under .claude/worktrees).
# NEVER touches: the main checkout, dirty worktrees, unmerged worktrees,
#   worktrees with a live process, or any process outside a deleted worktree.
# Deliberately matches NOTHING by command-line pattern (no pgrep -f / pkill -f)
#   so it can never match or kill itself.
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root" 2>/dev/null || exit 0
wt_base="$repo_root/.claude/worktrees"

db=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
[ -z "$db" ] && db=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
upstream="origin/$db"
git rev-parse --verify -q "$upstream" >/dev/null 2>&1 || upstream="$db"

git worktree prune 2>/dev/null

proc_cwd_under() {
  local d="$1" p c
  for p in /proc/[0-9]*; do
    c=$(readlink "$p/cwd" 2>/dev/null) || continue
    [ "$c" = "$d" ] && return 0
    case "$c" in "$d"/*) return 0 ;; esac
  done
  return 1
}

removed=0
while IFS= read -r wt; do
  case "$wt" in "$wt_base"/*) ;; *) continue ;; esac
  [ -d "$wt" ] || continue
  git -C "$wt" rev-parse HEAD >/dev/null 2>&1 || continue
  proc_cwd_under "$wt" && continue
  [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ] && continue
  cherry=$(git -C "$wt" cherry "$upstream" HEAD 2>/dev/null); rc=$?
  [ "$rc" -ne 0 ] && continue
  [ "$(printf '%s\n' "$cherry" | grep -c '^+')" -gt 0 ] && continue
  git worktree remove --force "$wt" 2>/dev/null && removed=$((removed + 1))
done < <(git worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')

killed=0
for p in /proc/[0-9]*; do
  c=$(readlink "$p/cwd" 2>/dev/null) || continue
  if [[ "$c" == *"/.claude/worktrees/"* && "$c" == *" (deleted)" ]]; then
    kill -TERM "${p#/proc/}" 2>/dev/null && killed=$((killed + 1))
  fi
done

git worktree prune 2>/dev/null

if [ $((removed + killed)) -gt 0 ]; then
  printf '{"systemMessage":"🧹 worktree cleanup: removed %d redundant worktree(s), killed %d orphaned process(es)"}\n' "$removed" "$killed"
fi
exit 0
