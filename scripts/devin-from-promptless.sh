#!/usr/bin/env bash
# Prompt-less → Devin CLI
#
# Uso:
#   ./scripts/devin-from-promptless.sh /caminho/do/app
#   ./scripts/devin-from-promptless.sh /caminho/do/app --full
#   ./scripts/devin-from-promptless.sh /caminho/do/app --dry-prep
#   ./scripts/devin-from-promptless.sh /caminho/do/app --context ms-cliente --dry-prep
#   ./scripts/devin-from-promptless.sh /caminho/do/app --all-contexts --dry-prep
#
# Docs: https://docs.devin.ai/  |  https://github.com/ilaraca/prompt-less

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

APP_ROOT=""
MODE="--run"
CONTEXT=""
ALL_CONTEXTS=0

usage() {
  cat <<'EOF'
Uso: ./scripts/devin-from-promptless.sh <APP_ROOT> [opções]

  APP_ROOT          Repo onde o Devin implementa
  --run             (default) gera + copia + chama devin
  --full            também openapi + mermaid
  --dry-prep        só gera e copia (sem devin)
  --context ID      só este microsserviço (ex.: ms-cliente)
  --all-contexts    gera todos os serviços do mapa (copia o escolhido com --context
                    ou o primeiro; para multi-repo rode o script N vezes)

Com --context, artefatos vêm de outputs/contextos/<ID>/.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run|--full|--dry-prep) MODE="$1"; shift ;;
    --context) CONTEXT="${2:-}"; shift 2 ;;
    --all-contexts) ALL_CONTEXTS=1; shift ;;
    *)
      if [[ -z "$APP_ROOT" ]]; then APP_ROOT="$1"; shift
      else echo "arg desconhecido: $1" >&2; usage; exit 1
      fi
      ;;
  esac
done

if [[ -z "$APP_ROOT" ]]; then usage; exit 1; fi
if [[ ! -d "$APP_ROOT" ]]; then echo "erro: APP_ROOT inválido: $APP_ROOT" >&2; exit 1; fi

PYTHON="${PIPELINE_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "erro: venv ausente em ${PIPELINE_ROOT}/.venv" >&2
  exit 1
fi

DOC_DIR="${APP_ROOT}/docs/prompt-less"
mkdir -p "$DOC_DIR"

echo "==> Prompt-less em ${PIPELINE_ROOT}"
cd "$PIPELINE_ROOT"

RUN_ARGS=(--dry-run)
if [[ -n "$CONTEXT" ]]; then
  RUN_ARGS+=(--context "$CONTEXT")
elif [[ "$ALL_CONTEXTS" -eq 1 ]]; then
  RUN_ARGS+=(--all-contexts)
fi

if [[ "$MODE" == "--full" ]]; then
  if [[ -n "$CONTEXT" ]]; then
    "$PYTHON" -m src.run openapi --context "$CONTEXT" --dry-run || \
      "$PYTHON" -m src.run openapi --dry-run
    "$PYTHON" -m src.run mermaid --context "$CONTEXT" --dry-run || \
      "$PYTHON" -m src.run mermaid --dry-run
  else
    "$PYTHON" -m src.run openapi --dry-run
    "$PYTHON" -m src.run mermaid --dry-run
  fi
fi

"$PYTHON" -m src.run historia "${RUN_ARGS[@]}"

# Origem dos arquivos
if [[ -n "$CONTEXT" && -d "outputs/contextos/$CONTEXT" ]]; then
  SRC_DIR="outputs/contextos/$CONTEXT"
elif [[ "$ALL_CONTEXTS" -eq 1 ]]; then
  # pega o primeiro contexto gerado
  SRC_DIR="$(find outputs/contextos -mindepth 1 -maxdepth 1 -type d | head -1 || true)"
  if [[ -z "${SRC_DIR:-}" ]]; then
    echo "erro: nenhum outputs/contextos/* gerado" >&2
    exit 1
  fi
  echo "==> --all-contexts: copiando $SRC_DIR (rode de novo com --context p/ outro repo)"
else
  SRC_DIR="outputs"
fi

echo "==> Copiando $SRC_DIR → ${DOC_DIR}"
cp -f "$SRC_DIR/PRD.md" "$SRC_DIR/historia.md" "$DOC_DIR/" 2>/dev/null || {
  # fallback raiz
  cp -f outputs/PRD.md outputs/historia.md "$DOC_DIR/"
}
[[ -f "$SRC_DIR/openapi.yaml" ]] && cp -f "$SRC_DIR/openapi.yaml" "$DOC_DIR/" || true
[[ -f "$SRC_DIR/sequence.mmd" ]] && cp -f "$SRC_DIR/sequence.mmd" "$DOC_DIR/" || true
[[ -f outputs/openapi.yaml && ! -f "$DOC_DIR/openapi.yaml" ]] && cp -f outputs/openapi.yaml "$DOC_DIR/" || true
[[ -f outputs/sequence.mmd && ! -f "$DOC_DIR/sequence.mmd" ]] && cp -f outputs/sequence.mmd "$DOC_DIR/" || true
[[ -f inputs/engenharia.yaml ]] && cp -f inputs/engenharia.yaml "$DOC_DIR/" || true
[[ -f inputs/mapa-servicos.yaml ]] && cp -f inputs/mapa-servicos.yaml "$DOC_DIR/" || true

PROMPT_FILE="${DOC_DIR}/DEVIN_PROMPT.md"
CTX_LABEL="${CONTEXT:-único/legado}"
cat > "$PROMPT_FILE" <<EOF
# Tarefa Devin (fonte: Prompt-less)

Implemente neste repositório conforme \`docs/prompt-less/\` (contexto: **${CTX_LABEL}**).

## Fontes da verdade (somente estas)
- \`docs/prompt-less/PRD.md\` — RF, AC, NFR, ownership (service_id + repos)
- \`docs/prompt-less/historia.md\` — BDD + DoD técnico
- \`docs/prompt-less/openapi.yaml\` / \`sequence.mmd\` — se existirem
- \`docs/prompt-less/engenharia.yaml\` — stack + NFR v1
- \`docs/prompt-less/mapa-servicos.yaml\` — mapa de microsserviços (se existir)

## Regras
1. **Não** releia specs brutas fora de \`docs/prompt-less/\`.
2. Respeite RF/AC e NFR-R/O/S; implemente só o ownership deste contexto/repos.
3. Ao final: mapeie \`RF-xx\` / \`AC-xx\` / \`NFR-*\` e abra PR se houver remoto.

Gerado por https://github.com/ilaraca/prompt-less
EOF

echo "==> Artefatos:"
ls -la "$DOC_DIR"

if [[ "$MODE" == "--dry-prep" ]]; then
  echo "==> --dry-prep: Devin não iniciado"
  exit 0
fi

if ! command -v devin >/dev/null 2>&1; then
  echo "erro: \`devin\` não está no PATH. Use --dry-prep ou instale o CLI." >&2
  exit 1
fi

cd "$APP_ROOT"
exec devin -- "$(cat "$PROMPT_FILE")"
