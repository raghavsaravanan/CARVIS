#!/usr/bin/env bash
# Preflight for /carvis-continue. Read-only apart from `git fetch --prune origin` and fetching a
# merged PR's head commit; never stashes, resets, switches, or deletes anything.
# Exit 0 = safe to start the next M2 row from origin/main; exit 1 = STOP and report the message.
set -u
REPO=raghavsaravanan/CARVIS
stop() { echo "STOP: $*"; exit 1; }

# 1. origin must be the CARVIS fork (any https/ssh spelling); pushes name origin explicitly.
case "$(git remote get-url origin 2>/dev/null)" in
  https://github.com/$REPO|https://github.com/$REPO.git|git@github.com:$REPO|git@github.com:$REPO.git) ;;
  *) stop "origin is not github.com/$REPO" ;;
esac
git fetch --quiet --prune origin || stop "cannot fetch origin"
git rev-parse --quiet --verify origin/main >/dev/null || stop "origin/main is missing after fetch"

# 2. Local work must be safe to leave with `git switch`.
[ -z "$(git status --porcelain --untracked-files=normal --ignore-submodules=none)" ] \
  || stop "uncommitted or untracked changes"
if [ -n "$(git rev-list origin/main..HEAD)" ]; then
  branch=$(git branch --show-current)
  [ -n "$branch" ] || stop "detached HEAD with commits not on origin/main"
  up=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
  # "Pushed" means pushed to origin: a local tracking branch does not count.
  if [ "$(git config "branch.$branch.remote" || true)" = origin ] && [ "${up#origin/}" != "$up" ] \
     && git rev-parse --quiet --verify "$up" >/dev/null && [ -z "$(git rev-list "$up..HEAD")" ]; then
    echo "NOTE: $branch is pushed to $up but not on main; it stays in place"
  else
    # Upstream missing, gone, or behind: safe only if a merged PR's final head contains HEAD
    # (the squash-merge case, where the branch's own commits never reach main).
    merge_ref=$(git config "branch.$branch.merge" || true)
    head_name=${merge_ref#refs/heads/}; head_name=${head_name:-$branch}
    safe=
    for pr in $(gh pr list --repo "$REPO" --head "$head_name" --base main --state merged --json number,headRefOid \
                 --jq '.[] | "\(.number):\(.headRefOid)"'); do
      n=${pr%%:*}; oid=${pr#*:}
      git cat-file -e "$oid^{commit}" 2>/dev/null || git fetch --quiet origin "pull/$n/head" || continue
      if git merge-base --is-ancestor HEAD "$oid"; then safe=$n; break; fi
    done
    [ -n "$safe" ] || stop "$branch has commits that are not pushed and not in any merged PR"
    echo "NOTE: $branch was squash-merged in #$safe; it stays in place"
  fi
fi

# 3. Roadmap-row PRs: none open, the latest merged, and its merge commit on origin/main.
# Roadmap-row PRs carry "(M2 A3)", "(M2 B1)", ... anywhere in the title, any case, so a drifted
# title such as "(M2 A3) [WIP]" still counts; other titles that merely mention M2 do not.
rows=$(gh pr list --repo "$REPO" --state all --search "M2 in:title" --limit 100 \
  --json number,title,state,mergeCommit \
  --jq '.[] | select(.title | test("\\(M2 [AB][0-9]+"; "i"))
        | "\(.number)\t\(.state)\t\(.mergeCommit.oid // "-")\t\(.title | gsub("[\t\n]"; " "))"') \
  || stop "cannot query GitHub"
rows=$(printf '%s\n' "$rows" | grep . | sort -n)
open=$(printf '%s\n' "$rows" | awk -F'\t' '$2=="OPEN"')
[ -z "$open" ] || stop "M2 row PR still open: $(printf '%s' "$open" | cut -f1,4 | tr '\t' ' ')"
latest=$(printf '%s\n' "$rows" | grep . | tail -n 1)
if [ -n "$latest" ]; then
  IFS=$'\t' read -r n state sha title <<<"$latest"
  [ "$state" = MERGED ] || stop "latest M2 row PR #$n is $state, not merged: $title"
  git merge-base --is-ancestor "$sha" origin/main || stop "merge commit of #$n is not on origin/main"
fi
echo "OK: merged M2 rows:"
printf '%s\n' "$rows" | awk -F'\t' '$2=="MERGED" {print "  #" $1 " " $4}'
