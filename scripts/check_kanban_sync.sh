#!/usr/bin/env bash
# Verifica que o Kanban do workspace aponta para pipeline/ e está
# alinhado com origin/feature/onda-frontier (ou origin/main, se já merjado).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE_ROOT="$(cd "$REPO/.." && pwd)"

die() { echo "check_kanban_sync: $*" >&2; exit 1; }

# 1) Symlink da pasta-mãe → pipeline/.scratch/harness
link="$WORKSPACE_ROOT/.scratch/harness"
[[ -L "$link" ]] || die "esperado symlink em $link"
target="$(readlink "$link")"
[[ "$target" == "../pipeline/.scratch/harness" || "$target" == "pipeline/.scratch/harness" ]] \
  || die "symlink deve apontar para ../pipeline/.scratch/harness (agora: $target)"
[[ -f "$REPO/.scratch/harness/board.md" ]] || die "faltando $REPO/.scratch/harness/board.md"

# 2) Branch do clone pipeline deve ter o harness (workspace/stable ou main)
cd "$REPO"
git fetch origin --quiet
branch="$(git branch --show-current)"
if [[ "$branch" != "workspace/stable" && "$branch" != "main" && "$branch" != "feature/onda-frontier" ]]; then
  die "pipeline está em '$branch'; use workspace/stable (onda) ou main"
fi

# 3) Working tree do Kanban limpo
dirty="$(git status --porcelain -- .scratch/harness docs/analise-engenheria-harness docs/correcoes-engenharia-harness .gitignore || true)"
[[ -z "$dirty" ]] || die "Kanban dirty em pipeline/ — commit+push antes de seguir:
$dirty"

# 4) Alinhado com o remoto da onda (ou main)
remote_ref="origin/feature/onda-frontier"
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  if git merge-base --is-ancestor "$remote_ref" origin/main 2>/dev/null; then
    remote_ref="origin/main"
  fi
fi

local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse "$remote_ref")"
if [[ "$local_sha" != "$remote_sha" ]] \
  && ! git merge-base --is-ancestor HEAD "$remote_sha" \
  && ! git merge-base --is-ancestor "$remote_sha" HEAD; then
  die "pipeline ($branch @$local_sha) divergiu de $remote_ref @$remote_sha"
fi

# 5) Se o pai existir: mesmo tip e mesmo conteúdo do Kanban (sem edição paralela)
pai="$WORKSPACE_ROOT/.worktrees/onda-merge"
if [[ -d "$pai" ]]; then
  pai_sha="$(git -C "$pai" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "$pai_sha" && "$pai_sha" != "$local_sha" ]]; then
    echo "check_kanban_sync: aviso — onda-merge @$pai_sha ≠ pipeline @$local_sha"
    echo "  no pai: git fetch && git merge --ff-only origin/feature/onda-frontier"
  fi
  if [[ -d "$pai/.scratch/harness" ]]; then
    if ! diff -rq "$REPO/.scratch/harness" "$pai/.scratch/harness" >/dev/null 2>&1; then
      die "Kanban difere entre pipeline/ e onda-merge/ — edite só em pipeline/ e faça ff-only no pai"
    fi
  fi
fi

echo "check_kanban_sync: OK (pipeline=$branch symlink→pipeline Kanban limpo vs $remote_ref)"
