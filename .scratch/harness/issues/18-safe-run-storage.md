# 18-safe-run-storage

**Kanban:** Done  
**Blocked by:** 02-runtime-execucao (Done)

> Aprovado por humano em 2026-09-17. Branch `feature/safe-run-storage` publicada,
> PR [#4](https://github.com/ilaraca/prompt-less/pull/4) aberto em `ilaraca/prompt-less`.
> Desbloqueia `19-contextual-provenance` e `11-stages-yaml`.

Fonte de escopo: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `18-safe-run-storage`.

## Comportamento entregue

Uma execução, inclusive concorrente ou retomada, só escreve dentro do diretório
autorizado e nunca deixa state parcialmente publicado.

## Contexto: o que já existe

| Camada | Onde | Estado |
|---|---|---|
| Identidade e diretórios da run | `src/runtime/run_context.py` | `run_id` vindo do chamador é aceito sem validação (`run_id or new_run_id()`), e `run_dir = root / "runs" / run_id` |
| Escrita de manifest/provenance/state | `src/runtime/run_store.py` | `path.write_text(...)` direto, sem temp + rename |
| Ponteiro da última run | `run_store._write_latest_pointer` | `latest.json` escrito direto |
| Espelho de compatibilidade | `run_store.mirror_artifacts_to_outputs` | copia para `outputs/` sem publicação atômica por manifest |

Ou seja: os dois gaps do §6 são verificáveis hoje no código — `run_id` não validado
(escape de path) e escrita não atômica (JSON parcial se o processo morrer no meio).

## Aceite

- [x] `run_id` aceita somente formato canônico gerado/validado
- [x] `run_dir.resolve()` deve permanecer sob `<root>/runs`
- [x] manifest, state, provenance e `latest.json` usam write-temp + atomic rename
- [x] transições de status usam controle de versão
- [x] o espelho em `outputs/` é publicado atomicamente por manifest
- [x] artefatos obsoletos do espelho são removidos com segurança
- [x] `contexts/` passa a ter contrato único e consistente
- [x] testes cobrem traversal, colisão de ID, interrupção e duas runs concorrentes

## Métrica de sucesso

- zero escrita fora de `runs/` em testes adversariais;
- zero JSON parcial após interrupção simulada;
- duas runs concorrentes preservam seus artefatos e provenances.

## Por que é a entrada da série 3

É blocker de `19`, `20`, `23`, `25` e, pelo rebloqueio da §5, também de `09` e `11`.
O `11-stages-yaml` foi tirado da frontier justamente para não definir formato de
checkpoint/manifest antes deste ticket.

## Implementation note

Branch `feature/safe-run-storage`, worktree `.worktrees/18-safe-run-storage`,
base `701fe0b`.

### O que foi entregue

`runs/` virou fronteira de segurança da execução. Todo identificador que entra
na composição de caminho é validado, todo estado publicado passa por
write-temp + `os.replace`, o diretório da run é reservado com `mkdir` exclusivo
e o espelho em `outputs/` tem manifesto próprio como ponto de commit.

### Commits

| Hash | Mensagem |
|---|---|
| `798a4e0` | feat: valida run_id canonico e adiciona escrita atomica |
| `ccfd880` | feat: publica run e espelho sem estado parcial |
| `ed3a289` | test: cobre traversal, colisao, interrupcao e runs concorrentes |
| `bd21f41` | docs: documenta storage seguro da run e contrato de contextos |

### Arquivos alterados

| Arquivo | O quê |
|---|---|
| `src/runtime/atomic_io.py` (novo) | `atomic_write_bytes/text/json`, `atomic_copy`, `read_json`, `sha256_of`, `resolve_within` e `UnsafePath` |
| `src/runtime/run_context.py` | `validate_run_id` / `validate_context_id` / `context_subdir`, `UnsafeRunPath`, containment de `run_dir`, `contexts_dir` = `artifacts/contextos`, `context_artifacts_dir`, `context_validations_dir`, `new_run_id` com 8 hex |
| `src/runtime/run_store.py` | `bootstrap(resume=)` com `mkdir` exclusivo, `RunIdCollision`, `set_status` versionado (`RunStateConflict`, `InvalidStatusTransition`, `status_history`), escrita atômica de manifest/provenance/`latest.json`, espelho por `.mirror-manifest.json` com prune seguro |
| `src/runtime/event_store.py` | deixa de criar arquivo/diretório no construtor (senão o `mkdir` exclusivo nunca detecta colisão) |
| `src/runtime/__init__.py` | reexporta a API nova |
| `src/state_store.py` | `write_state` grava `state.json` atomicamente |
| `src/emit.py` | artefato por contexto usa `context_subdir` (valida o id) |
| `src/run.py` | `canonical-spec.yaml`, `spec-validation.json` e `llm_package_*.json` atômicos; contrato `contextos/<id>/`; `finish("failed")` não reabre estado terminal |
| `tests/integration/test_safe_run_storage.py` (novo) | 36 testes adversariais |
| `README.md`, `CHANGELOG.md` | tabela do runtime, seção "Storage seguro da run", contrato de contexto, Unreleased |

### Resultado dos testes

```
.venv/bin/python -m pytest -q
# antes: 47 passed   depois: 83 passed  (+36, nenhuma regressão)
```

Sem flakiness: `test_safe_run_storage.py` rodado 3× seguidas, 36 passed.
Smokes: `python -m src.run historia --dry-run`, `python -m src.plan_repos --help`,
`python -m src.improve --out /tmp/imp-18` e `compileall src` — todos OK.

### Evidência por critério de aceite

| Critério | Como foi atendido | Teste |
|---|---|---|
| `run_id` só em formato canônico | `validate_run_id` em `RunContext.__post_init__`: `[A-Za-z0-9_][A-Za-z0-9_-]*`, ≤64, reservados (`latest`, `runs`, `tmp`) | `test_run_id_fora_do_formato_canonico_e_rejeitado` (17 casos), `test_run_id_gerado_e_canonico`, `test_run_com_run_id_de_traversal_nao_escreve_fora` |
| `run_dir.resolve()` sob `<root>/runs` | `resolve_within` resolve os dois lados, então pega `..` e symlink plantado | `test_symlink_plantado_em_runs_nao_permite_escapar` |
| manifest/state/provenance/`latest.json` atômicos | tudo via `atomic_io` (temp + fsync + `os.replace` + fsync do diretório) | `test_interrupcao_no_commit_nao_deixa_manifest_parcial`, `test_interrupcao_nao_corrompe_state_json`, `test_interrupcao_no_provenance_preserva_relatorio_anterior`, `test_leitor_concorrente_nunca_ve_manifest_parcial` |
| Transições de status versionadas | `manifest.version` monotônica + `status_history`; `expected_version` obsoleto = `RunStateConflict`; transição inválida = `InvalidStatusTransition` | `test_transicoes_de_status_usam_controle_de_versao`, `test_status_final_desconhecido_e_recusado` |
| Espelho publicado atomicamente por manifest | cada arquivo por `atomic_copy`; `.mirror-manifest.json` (run_id + sha256) escrito atomicamente como commit | `test_espelho_publica_por_manifesto_e_remove_obsoletos` |
| Obsoletos removidos com segurança | só apaga o que consta do manifesto anterior e resolve sob `outputs/`; ignora symlink e caminho adulterado; poda diretório vazio | `test_espelho_publica_por_manifesto_e_remove_obsoletos`, `test_remocao_de_obsoletos_ignora_manifesto_adulterado`, `test_espelho_ignora_symlink_e_nao_escreve_fora` |
| `contexts/` com contrato único | tudo por serviço em `contextos/<id>/` (run `artifacts/`, run `validations/`, espelho `outputs/`) via `context_subdir`; `runs/<id>/contexts/` morto deixou de existir | `test_contexts_tem_contrato_unico`, `test_run_multi_contexto_grava_no_contrato_unico` |
| Testes de traversal/colisão/interrupção/concorrência | arquivo novo com as 4 famílias | `test_colisao_de_run_id_preserva_a_run_existente`, `test_run_com_run_id_repetido_falha_sem_sobrescrever`, `test_retomada_explicita_reaproveita_o_diretorio`, `test_duas_runs_concorrentes_preservam_artefatos_e_provenance` |

Métricas: zero escrita fora de `runs/` nos testes adversariais, zero JSON
parcial após interrupção simulada (inclusive com leitor concorrente em 120
escritas) e duas runs concorrentes com artefatos, manifest e provenance
próprios preservados.

### Comandos de verificação

```bash
cd .worktrees/18-safe-run-storage
.venv/bin/python -m pytest -q                                   # 83 passed
.venv/bin/python -m pytest -q tests/integration/test_safe_run_storage.py
.venv/bin/python -m src.run historia --dry-run
cat outputs/.mirror-manifest.json                               # run_id + sha256 por arquivo
.venv/bin/python -c "import json,pathlib; \
  p=sorted(pathlib.Path('runs').glob('*/manifest.json'))[-1]; \
  m=json.loads(p.read_text()); print(m['version'], m['status'], m['status_history'])"
```

### Riscos e decisões que precisam de revisão humana

1. **Colisão de `run_id` agora é fail-closed.** Reexecutar com um `run_id` já
   usado levanta `RunIdCollision` em vez de sobrescrever. Se algum fluxo
   externo dependia de reaproveitar o id, ele precisa passar
   `bootstrap(resume=True)` — que também exige que a run não esteja em estado
   terminal.
2. **`run_dir` passou a ser resolvido.** `result["run_dir"]` e
   `latest.json["run_dir"]` agora trazem o caminho canônico (em macOS,
   `/private/var/...` em vez de `/var/...`). Comparação literal de string com
   `output_root` em consumidor externo pode quebrar.
3. **Formato de `run_id` rejeita ponto.** `run.2026.01` deixa de ser aceito;
   ids existentes nos testes/evals (`eval-happy_path`, `run-aaaa-0001`) seguem
   válidos.
4. **Espelho é last-writer-wins e agora poda.** Uma segunda run publica por
   cima e remove o que a publicação anterior tinha deixado em `outputs/`.
   Arquivo que nunca passou pelo manifesto (ex.: `outputs/.gitkeep`) nunca é
   tocado, mas quem lia `outputs/` esperando acúmulo de várias runs precisa
   passar a ler `runs/<id>/`.
5. **Layout de validação por contexto mudou** de `validations/<svc>/` para
   `validations/contextos/<svc>/`, para ficar igual ao de artifacts e ao do
   espelho. Nenhum teste lia o caminho literal (usam `rglob`), mas é quebra de
   contrato para consumidor externo.
6. **`EventStore` ficou lazy.** `events.jsonl` só existe depois do primeiro
   evento; quem instanciava `EventStore` só para criar o arquivo não recebe
   mais esse efeito colateral.
7. `fsync` por escrita tem custo. Irrelevante no volume atual (suíte roda em
   ~2,4s), mas vale lembrar se `13-parallel-exec` multiplicar as escritas.
