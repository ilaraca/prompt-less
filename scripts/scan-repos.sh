#!/usr/bin/env bash
# Prompt-less — scan de repositórios → mapa-servicos.yaml (de/para)
#
# Varre uma pasta que contém TODOS os repositórios (padrão Devin CLI workspace),
# agrupa por jornada e classifica por camada (api, gtw, bff, mfe, ms, worker…).
#
#   gestao-de-ofertas-api  ┐
#   gestao-de-ofertas-bff  ├─► serviço: gestao-de-ofertas
#   ofertas-gtw            ┘   keywords: gestao, ofertas, /ofertas, gtw…
#
# Uso:
#   ./scripts/scan-repos.sh --workspace ~/dev/repos
#   ./scripts/scan-repos.sh --workspace ~/dev/repos --dry-run
#   ./scripts/scan-repos.sh --workspace ~/dev/repos --out inputs/mapa-servicos.yaml
#   ./scripts/scan-repos.sh --workspace ~/dev/repos --tiers api,gtw,bff --no-git-check
#
# Compatível com bash 3.2 (macOS).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKSPACE=""
OUT="${PIPELINE_ROOT}/inputs/mapa-servicos.yaml"
TIERS="api,gtw,gateway,bff,mfe,ms,svc,service,worker,batch,orq,web,front"
STOPWORDS="de,da,do,das,dos,e,a,o,as,os,para,com"
DRY_RUN=0
GIT_CHECK=1
MERGE=1
UNASSIGNED="bucket"

usage() {
  cat <<'EOF'
Uso: ./scripts/scan-repos.sh --workspace DIR [opções]

  --workspace DIR   Pasta com todos os repositórios (obrigatório)
  --out FILE        Saída YAML (default: inputs/mapa-servicos.yaml)
  --tiers LISTA     Camadas reconhecidas (default: api,gtw,gateway,bff,mfe,ms,svc,service,worker,batch,orq,web,front)
  --unassigned S    bucket|drop para chunks não classificados (default: bucket)
  --no-git-check    Considera qualquer subpasta, não só repos git
  --no-merge        Não funde jornadas contidas (ex.: ofertas-gtw + gestao-de-ofertas-api)
  --dry-run         Mostra o YAML no stdout, não escreve arquivo
  -h|--help         Esta ajuda

Depois:
  python -m src.repo_index --workspace DIR   # indexa o código dos repos
  python -m src.marcar --apply               # injeta [[service:id]] nos docs
  python -m src.run historia --all-contexts
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --tiers) TIERS="${2:-}"; shift 2 ;;
    --unassigned) UNASSIGNED="${2:-bucket}"; shift 2 ;;
    --no-git-check) GIT_CHECK=0; shift ;;
    --no-merge) MERGE=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "arg desconhecido: $1" >&2; usage; exit 1 ;;
  esac
done

if [ -z "$WORKSPACE" ]; then usage; exit 1; fi
if [ ! -d "$WORKSPACE" ]; then echo "erro: workspace inválido: $WORKSPACE" >&2; exit 1; fi

TIERS_SPACED="$(echo "$TIERS" | tr ',' ' ')"
STOP_SPACED="$(echo "$STOPWORDS" | tr ',' ' ')"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/jornadas" "$TMP/aliases"

is_tier() {
  _tok="$1"
  for t in $TIERS_SPACED; do
    [ "$_tok" = "$t" ] && return 0
  done
  return 1
}

is_stop() {
  _tok="$1"
  for s in $STOP_SPACED; do
    [ "$_tok" = "$s" ] && return 0
  done
  return 1
}

REPO_COUNT=0
SKIPPED=0

for dir in "$WORKSPACE"/*; do
  [ -d "$dir" ] || continue
  name="$(basename "$dir")"
  case "$name" in .*) continue ;; esac
  if [ "$GIT_CHECK" -eq 1 ] && [ ! -e "$dir/.git" ]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # normaliza separadores e minúsculas
  norm="$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr '_.' '--')"
  tokens="$(echo "$norm" | tr '-' ' ')"

  tier=""
  journey_tokens=""
  for tok in $tokens; do
    [ -z "$tok" ] && continue
    if is_tier "$tok"; then
      [ -z "$tier" ] && tier="$tok"
    else
      journey_tokens="$journey_tokens $tok"
    fi
  done

  journey="$(echo "$journey_tokens" | sed 's/^ *//;s/ *$//' | tr ' ' '-')"
  if [ -z "$journey" ]; then
    journey="$norm"
  fi
  [ -z "$tier" ] && tier="app"

  echo "${name}|${tier}" >> "$TMP/jornadas/$journey"
  REPO_COUNT=$((REPO_COUNT + 1))
done

if [ "$REPO_COUNT" -eq 0 ]; then
  echo "erro: nenhum repositório encontrado em $WORKSPACE (use --no-git-check?)" >&2
  exit 1
fi

# --- Fusão de jornadas contidas -------------------------------------------
# "ofertas-gtw" (jornada: ofertas) entra em "gestao-de-ofertas" porque todos os
# seus tokens significativos estão contidos na jornada maior.
significant_tokens() {
  _out=""
  for tok in $(echo "$1" | tr '-' ' '); do
    is_stop "$tok" && continue
    [ ${#tok} -lt 3 ] && continue
    _out="$_out $tok"
  done
  echo "$_out" | sed 's/^ *//'
}

contains_all() {
  # contains_all "<tokens_alvo>" "<tokens_candidato>"
  _target="$1"; _cand="$2"
  for t in $_target; do
    _found=0
    for c in $_cand; do
      [ "$t" = "$c" ] && _found=1 && break
    done
    [ "$_found" -eq 0 ] && return 1
  done
  return 0
}

if [ "$MERGE" -eq 1 ]; then
  for jfile in "$TMP/jornadas"/*; do
    [ -f "$jfile" ] || continue
    j="$(basename "$jfile")"
    echo "$(significant_tokens "$j" | wc -w | tr -d ' ') $j"
  done | sort -n > "$TMP/ordered"

  while read -r _count small; do
    [ -n "${small:-}" ] || continue
    [ -f "$TMP/jornadas/$small" ] || continue
    small_tokens="$(significant_tokens "$small")"
    [ -z "$small_tokens" ] && continue

    best=""
    best_n=0
    for cfile in "$TMP/jornadas"/*; do
      [ -f "$cfile" ] || continue
      cand="$(basename "$cfile")"
      [ "$cand" = "$small" ] && continue
      cand_tokens="$(significant_tokens "$cand")"
      cand_n="$(echo "$cand_tokens" | wc -w | tr -d ' ')"
      [ "$cand_n" -le "$(echo "$small_tokens" | wc -w | tr -d ' ')" ] && continue
      if contains_all "$small_tokens" "$cand_tokens"; then
        if [ "$cand_n" -gt "$best_n" ]; then
          best="$cand"
          best_n="$cand_n"
        fi
      fi
    done

    if [ -n "$best" ]; then
      cat "$TMP/jornadas/$small" >> "$TMP/jornadas/$best"
      echo "$small" >> "$TMP/aliases/$best"
      rm -f "$TMP/jornadas/$small"
      echo "==> fundido: '$small' → '$best'" >&2
    fi
  done < "$TMP/ordered"
fi

YAML="$TMP/mapa.yaml"
{
  echo "# Gerado por scripts/scan-repos.sh"
  echo "# workspace: $WORKSPACE"
  echo "# repos: $REPO_COUNT  |  ignorados (sem .git): $SKIPPED"
  echo "#"
  echo "# Marcadores aceitos nos docs:"
  echo "#   ## Serviço: <id>   |   [[service:<id>]]   |   <!-- service: <id> -->"
  echo "# Injete automaticamente com: python -m src.marcar --apply"
  echo ""
  echo "version: 1"
  echo ""
  echo "unassigned:"
  echo "  strategy: $UNASSIGNED"
  echo ""
  echo "servicos:"

  for jfile in "$TMP/jornadas"/*; do
    [ -f "$jfile" ] || continue
    journey="$(basename "$jfile")"

    # nome legível: "gestao-de-ofertas" → "Gestao de Ofertas"
    nome="$(echo "$journey" | tr '-' '\n' | awk -v stop="$STOPWORDS" '
      BEGIN { n = split(stop, s, ","); }
      {
        low = tolower($0);
        is_stop = 0;
        for (i = 1; i <= n; i++) if (low == s[i]) is_stop = 1;
        if (is_stop && NR > 1) printf "%s ", low;
        else printf "%s%s ", toupper(substr(low, 1, 1)), substr(low, 2);
      }
    ' | sed 's/ *$//')"

    echo "  ${journey}:"
    echo "    nome: \"${nome}\""
    echo "    repos:"
    sort -u "$jfile" | while IFS='|' read -r rname rtier; do
      echo "      - ${rname}"
    done

    # camadas: tier → repos (alimenta ownership/arquitetura no PRD e na história)
    echo "    camadas:"
    for t in $(cut -d'|' -f2 "$jfile" | sort -u); do
      repos_tier="$(grep "|${t}\$" "$jfile" | cut -d'|' -f1 | sort -u | tr '\n' ',' | sed 's/,$//' | sed 's/,/, /g')"
      echo "      ${t}: [${repos_tier}]"
    done

    # keywords: slug + tokens significativos + path do último token (+ jornadas fundidas)
    KW="$TMP/kw.tmp"
    : > "$KW"
    echo "$journey" >> "$KW"
    last_tok=""
    for tok in $(significant_tokens "$journey"); do
      echo "$tok" >> "$KW"
      last_tok="$tok"
    done
    if [ -f "$TMP/aliases/$journey" ]; then
      while read -r merged; do
        [ -n "$merged" ] || continue
        echo "$merged" >> "$KW"
        for tok in $(significant_tokens "$merged"); do
          echo "$tok" >> "$KW"
        done
      done < "$TMP/aliases/$journey"
    fi
    [ -n "$last_tok" ] && echo "/${last_tok}" >> "$KW"

    echo "    keywords:"
    awk '!seen[$0]++' "$KW" | while read -r kw; do
      [ -n "$kw" ] && echo "      - ${kw}"
    done

    AL="$TMP/al.tmp"
    : > "$AL"
    echo "$journey" >> "$AL"
    [ -n "$last_tok" ] && echo "$last_tok" >> "$AL"
    [ -f "$TMP/aliases/$journey" ] && cat "$TMP/aliases/$journey" >> "$AL"
    cut -d'|' -f1 "$jfile" >> "$AL"

    echo "    aliases:"
    awk '!seen[$0]++' "$AL" | while read -r al; do
      [ -n "$al" ] && echo "      - ${al}"
    done
    echo ""
  done
} > "$YAML"

if [ "$DRY_RUN" -eq 1 ]; then
  cat "$YAML"
  echo "==> --dry-run: nada escrito (destino seria $OUT)" >&2
  exit 0
fi

if [ -f "$OUT" ]; then
  cp -f "$OUT" "${OUT}.bak"
  echo "==> backup: ${OUT}.bak"
fi

mkdir -p "$(dirname "$OUT")"
cp -f "$YAML" "$OUT"

echo "==> mapa gerado: $OUT"
awk '
  /^servicos:/ { inside = 1; next }
  inside && /^  [a-z0-9_-]+:[[:space:]]*$/ {
    gsub(/[ :]/, "", $0); print "    serviço: " $0
  }
' "$OUT"
echo ""
echo "Próximos passos:"
echo "  python -m src.repo_index --workspace $WORKSPACE   # indexa o código (assertividade)"
echo "  python -m src.marcar --explain       # de/para com evidência (dry-run)"
echo "  python -m src.marcar --apply         # injeta marcadores nos docs"
echo "  python -m src.run historia --all-contexts"
