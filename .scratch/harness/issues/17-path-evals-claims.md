# 17-path-evals-claims

**Kanban:** Done  
**Blocked by:** 16-hardening-review (Done)

## Objetivo

Fechar gaps pós-16: path traversal na policy, evals por camada (spec/artefatos), `unexpected_inferences` real, claims com SourceRef obrigatório.

## Aceite

- [x] `normalize_repo_path` rejeita absoluto, `..`, traversal
- [x] evals: HTTP/sinais a partir do Canonical Spec (+ artefatos finais), não blob global
- [x] `unexpected_inferences` calculado (defaults/inferred sem review)
- [x] `CLAIM_WITHOUT_SOURCE` + validação básica de SourceRef
- [x] remover `nfr_ids` morto

## Implementation note

### O que shipou

1. **policy.py** — `normalize_repo_path` (PurePosixPath); rejeita absoluto, drive, `..`; `check_write_allowed` só opera no canônico.
2. **evals.py** — scoring por camada (`ingestion` / `canonical_spec` / `artifacts` / `provenance`); HTTP via `collect_spec_statuses`; sinais sem rglob global; `unexpected_inferences` conta ResolvedValues `default|inferred` sem review; fixtures com `http_status_mode: subset`.
3. **validators** — `CLAIM_WITHOUT_SOURCE` / `CLAIM_SOURCE_INVALID`; removido `nfr_ids`.

### Como verificar

```bash
cd pipeline && .venv/bin/pytest -v --tb=short
```

Esperado: **47 passed**.
