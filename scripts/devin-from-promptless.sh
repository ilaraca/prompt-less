#!/usr/bin/env bash
# Prompt-less → Devin CLI
# Gera artefatos comprimidos e inicia (ou prepara) uma sessão Devin no repo de implementação.
#
# Uso:
#   ./scripts/devin-from-promptless.sh /caminho/do/app
#   ./scripts/devin-from-promptless.sh /caminho/do/app --full
#   ./scripts/devin-from-promptless.sh /caminho/do/app --dry-prep   # só gera + copia, sem chamar devin
#
# Docs: https://docs.devin.ai/  |  https://github.com/ilaraca/prompt-less

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_ROOT="${1:-}"
MODE="${2:---run}"

usage() {
  cat <<'EOF'
Uso: ./scripts/devin-from-promptless.sh <APP_ROOT> [--run|--full|--dry-prep]

  APP_ROOT     Caminho do repositório onde o Devin vai implementar (BFF/MFE/API)
  --run        (default) gera historia+PRD, copia para APP_ROOT/docs/prompt-less, chama `devin -- …`
  --full       também gera openapi + mermaid antes do Devin
  --dry-prep   só gera e copia artefatos; não chama o Devin CLI

Requisitos:
  - Python venv em PIPELINE/.venv (pip install -r requirements.txt)
  - `devin` no PATH (exceto em --dry-prep)
    curl -fsSL https://cli.devin.ai/install.sh | bash
EOF
}

if [[ -z "$APP_ROOT" || "$APP_ROOT" == "-h" || "$APP_ROOT" == "--help" ]]; then
  usage
  exit 1
fi

if [[ ! -d "$APP_ROOT" ]]; then
  echo "erro: APP_ROOT não é um diretório: $APP_ROOT" >&2
  exit 1
fi

PYTHON="${PIPELINE_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "erro: venv não encontrado em ${PIPELINE_ROOT}/.venv — rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

DOC_DIR="${APP_ROOT}/docs/prompt-less"
mkdir -p "$DOC_DIR"

echo "==> Prompt-less: gerando artefatos em ${PIPELINE_ROOT}"
cd "$PIPELINE_ROOT"

if [[ "$MODE" == "--full" ]]; then
  "$PYTHON" -m src.run openapi --dry-run
  "$PYTHON" -m src.run mermaid --dry-run
fi

"$PYTHON" -m src.run historia --dry-run

echo "==> Copiando outputs → ${DOC_DIR}"
cp -f outputs/PRD.md outputs/historia.md "$DOC_DIR/"
[[ -f outputs/openapi.yaml ]] && cp -f outputs/openapi.yaml "$DOC_DIR/" || true
[[ -f outputs/sequence.mmd ]] && cp -f outputs/sequence.mmd "$DOC_DIR/" || true
[[ -f inputs/engenharia.yaml ]] && cp -f inputs/engenharia.yaml "$DOC_DIR/" || true

# Prompt enxuto: Devin lê os artefatos, NÃO os inputs brutos
PROMPT_FILE="${DOC_DIR}/DEVIN_PROMPT.md"
cat > "$PROMPT_FILE" <<EOF
# Tarefa Devin (fonte: Prompt-less)

Implemente neste repositório conforme os artefatos em \`docs/prompt-less/\`.

## Fontes da verdade (somente estas)
- \`docs/prompt-less/PRD.md\` — RF, AC, NFR-R/O/S, handoff SDD
- \`docs/prompt-less/historia.md\` — BDD funcional + DoD técnico
- \`docs/prompt-less/openapi.yaml\` — contrato (se existir)
- \`docs/prompt-less/sequence.mmd\` — fluxo Frontend → BFF → API (se existir)
- \`docs/prompt-less/engenharia.yaml\` — stack e baseline NFR v1

## Regras
1. **Não** releia specs brutas, dumps longos ou arquivos fora de \`docs/prompt-less/\` para descobrir requisitos.
2. Respeite RF/AC e NFR (timeout/retry, logs estruturados + correlation_id, sem PII, validar input).
3. Entregue código alinhado ao stack em engenharia.yaml.
4. Ao final: resumo do que foi feito mapeando \`RF-xx\` / \`AC-xx\` / \`NFR-*\` e abra um PR se o repo usar git remoto.

## Contexto
Gerado por Prompt-less (https://github.com/ilaraca/prompt-less) — contexto já comprimido de propósito.
EOF

echo "==> Artefatos prontos:"
ls -la "$DOC_DIR"

if [[ "$MODE" == "--dry-prep" ]]; then
  echo "==> --dry-prep: pulando Devin CLI"
  echo "    Para rodar depois: cd \"$APP_ROOT\" && devin -- \"\$(cat docs/prompt-less/DEVIN_PROMPT.md)\""
  exit 0
fi

if ! command -v devin >/dev/null 2>&1; then
  echo "erro: comando \`devin\` não encontrado no PATH." >&2
  echo "      Instale: curl -fsSL https://cli.devin.ai/install.sh | bash" >&2
  echo "      Ou use --dry-prep e rode o Devin manualmente." >&2
  exit 1
fi

echo "==> Iniciando Devin CLI em ${APP_ROOT}"
cd "$APP_ROOT"
# shellcheck disable=SC2046
exec devin -- "$(cat "$PROMPT_FILE")"
