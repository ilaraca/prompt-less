# 29-operations-por-contexto

**Kanban:** Done  
**Blocked by:** 08-ir-openapi-mermaid (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (sem correção
> de código). Branch `feature/operations-por-contexto` na worktree
> `.worktrees/29-operations-por-contexto`, base `648f062` (`origin/main` já com
> o 08). Sem push. `27-sdd-consumer` ficou liberado pelo Done do `22`
> (08 já era Done).

Achado da implementação do `08`: as `operations` do Canonical Spec não são fatiadas
por serviço, então `--all-contexts` replica todas as actions da UI em cada contexto.
Estava visível no código, mas só virou defeito observável quando o OpenAPI e o Mermaid
passaram a ser renderizados a partir do IR.

## Comportamento entregue

Cada contexto de serviço recebe só as operações (e os erros associados) que lhe
pertencem. Renderizadores derivados — OpenAPI, Mermaid, e depois o pacote SDD —
não publicam contrato de outro serviço.

## Contexto

O IR hoje carrega `operations` no spec sem recorte por `owner`/`service_id`. Com
`--all-contexts`, cada run por serviço herda o conjunto inteiro. O README do
pipeline já registra isso como limitação da entrega do `08`.

O `06-multi-repo` (Done) já planeja por serviço; este ticket alinha o IR a essa
fronteira, em vez de deixar o renderer adivinhar.

## Aceite

- [x] cada `Operation` tem dono explícito (`owner` / `service_id`) preenchido na montagem do IR
- [x] recorte por contexto: `spec.operations` de uma run `--context <svc>` contém só as do serviço
- [x] `--all-contexts` não replica action de um serviço no OpenAPI/Mermaid de outro
- [x] erros (`ERR-*`) acompanham a operação dona; erro órfão fica `unresolved`, não é copiado
- [x] golden fixtures com dois serviços comprovam isolamento (o fixture `two_services` já existe)
- [x] operação sem dono não é emitida como resolvida: fica `unresolved` ou exige revisão
- [x] o recorte acontece no IR, não em cada renderer — OpenAPI, Mermaid e futuros consumidores leem o mesmo conjunto

## Métrica de sucesso

- zero path/status de um serviço no OpenAPI de outro, nas goldens multi-contexto;
- `27-sdd-consumer` pode assumir que o IR já chega fatiado (não precisa reimplementar o recorte).

## Relação com outros tickets

Não rebloqueia `27` automaticamente: o `27` continua esperando `08` e `22`.
Este ticket saiu de `Done` antes do `22`; quando o `22` for aprovado, o
pacote SDD já lê o IR fatiado.

Não é hardening (`15`) nem baseline de NFR (`28`): é recorte de autoridade
semântica do IR.

## Implementation note

Branch `feature/operations-por-contexto` (worktree `.worktrees/29-operations-por-contexto`),
base `648f062` (`origin/main` já com o 08). Nada foi enviado ao remoto.

> Aprovado. O `27-sdd-consumer` continua esperando o `22` — este ticket **não**
> o desbloqueia.

### O que foi entregue

O recorte de operações passou a acontecer **no Canonical Spec**, não em cada
renderer. `Operation.owner` deixa de herdar cegamente o `service_id` do spec em
construção: o dono sai de evidência (campo explícito na UI ou keywords/path do
mapa). Com `--context` / `--all-contexts`, `spec.operations` só contém as ações
daquele serviço; `ERR-*` ancora na operação dona; erro sem match único fica
`unresolved` (pergunta aberta não bloqueante) e **não** é copiado. Operação sem
dono entra em `unresolved` e `CanonicalSpec.contract_operations()` é o conjunto
que OpenAPI, Mermaid e futuros consumidores (SDD) publicam.

README+CHANGELOG atualizados conforme a regra do repo (limitação do 08 sobre
`--all-contexts` replicar actions foi removida).

### Arquivos alterados

| Arquivo | O que mudou |
|---|---|
| `src/domain/spec.py` | `Operation.is_contract()`, `CanonicalSpec.contract_operations()`; `http_statuses()` só conta erros ancorados em contrato |
| `src/spec/builder.py` | resolve `owner` por evidência, fatiar por contexto, ancora `ERR-*`, órfão/`owner` → `unresolved` |
| `src/run.py` | carrega o mapa mesmo sem split e passa `mapa=` ao builder |
| `src/preprocess.py` | propaga `owner`/`service_id` explícito da action do Figma |
| `src/renderers/openapi.py`, `mermaid.py`, `__init__.py` | publicam `is_contract()`; PRD marca erro órfão e owner ausente |
| `src/validators/__init__.py` | paths/calls permitidos vêm de `contract_operations()` |
| `tests/integration/test_derived_artifacts.py` | isolamento `two_services`, órfão, owner-less, `--context`/`--all-contexts` |
| `README.md`, `CHANGELOG.md` | recorte no IR + entrada Fixed em `[Unreleased]` |

### Comandos de verificação

```bash
cd .worktrees/29-operations-por-contexto
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
# 103 passed
```

### Resultado dos testes

- Antes: **97 passed** (baseline `648f062`, já com 08).
- Depois: **103 passed** (97 preservados + 6 novos de isolamento). Nenhum
  golden do 08 quebrou.

### Evidência por critério de aceite

| Critério | Como foi atendido | Como verificar |
|---|---|---|
| `owner` preenchido na montagem | `_resolve_operation_owner` (explícito na UI ou keyword/path do mapa); sem mapa e contexto único, fallback ao `service_id` | `test_operation_owner_preenchido_na_montagem_do_ir` |
| `--context` só ops do serviço | builder descarta `owner != context`; `run --context ms-cliente` | `test_context_contem_so_operacoes_do_servico`, `test_run_context_isola_spec_operations` |
| `--all-contexts` não replica | OpenAPI/Mermaid de `ms-cliente` sem `/pagamentos` e vice-versa | `test_all_contexts_nao_replica_action_no_openapi_mermaid_do_outro` |
| `ERR-*` segue a dona; órfão unresolved | CPF→cadastrar, saldo→pagar, 401 sem `error_ids` + pergunta aberta | `test_erros_seguem_a_operacao_dona_orfaos_nao_sao_copiados` |
| golden `two_services` | fixture existente; testes de isolamento + coerência IR↔artefatos | mesmos testes + `test_sem_divergencia_entre_ir_historia_prd_openapi_mermaid` |
| sem dono ≠ resolvido | `unresolved=["owner"]`, fora de `contract_operations()`, path vazio no OpenAPI | `test_operacao_sem_dono_nao_e_emitida_como_resolvida` |
| recorte no IR | renderers/validadores leem `is_contract()` / `contract_operations()`; SDD futuro lê o mesmo `spec.operations` já fatiado | código em `builder.py`; renderers não filtram por serviço |

### Riscos residuais — aceitos em 2026-09-18 (sem correção)

Não furam o aceite. Recorte de operations no IR está entregue; não reabrir o
worktree por isso. Follow-up opcional do item 1 (parar de pré-filtrar `regras`
no `run.py`) fica fora deste ticket.

1. **`--all-contexts` ainda filtra `regras` por keyword antes do builder**
   (`_filter_regras_for_service` em `src/run.py`). Pré-existente do 08. No
   `two_services`, “sem autenticação” (401) não casa com keywords de
   `ms-cliente` nem de `ms-pagamento`, então o 401 **não chega** ao builder
   no caminho CLI fatiado. O órfão unresolved é coberto quando o builder vê
   o `regras.yaml` completo (`--no-split` ou teste direto): fica pergunta
   aberta e **não** entra em nenhum `error_ids`. Não vaza contrato — nenhum
   OpenAPI ganha 401 do outro serviço. O que falta no `--all-contexts` é só
   a pergunta aberta. Não misturar com o recorte de operations.

2. **Schemas de input/coluna continuam globais na UI.** O fixture tem
   `inputs`/`columns` na raiz; o builder copia o conjunto inteiro para cada
   operação (`cadastrar` herda `valor`, `pagar` herda `nome`). Fora do
   aceite: este ticket recorta *operations*, não campos. Corrigir exige
   modelo de UI por ação ou ticket novo.

3. **`--context` com uma ação + um 2xx resolve `200`.** Efeito esperado do
   recorte, não regressão. O 08 deixava `two_services` unresolved porque via
   as duas actions juntas. Com uma ação dona e um único 2xx nas decisões, a
   regra de evidência única do 08 passa a aplicar. `--no-split` com dois
   donos continua `unresolved`. Reverter seria enfraquecer o contrato
   fatiado de propósito.

4. **`27-sdd-consumer` não foi implementado**; pode assumir IR já fatiado.
5. Goldens byte-exatos do 08 (`tests/fixtures/golden/`) não mudaram.

Commits: `81ee853` (feat), `56676fd` (test), `dbab638` (docs). Sem push / sem PR.

> Aprovado. `27` continua bloqueado pelo `22`.
