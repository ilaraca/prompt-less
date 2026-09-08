Coloque aqui os insumos:

  figma.json             (opcional)
  regras.yaml            (opcional)
  engenharia.yaml        (stack + NFR baseline)
  mapa-servicos.yaml     (keywords/marcadores → microsserviço + repos)
  *.txt | *.md           docs (podem ter ## Serviço: id)
  *.docx | *.doc         Word

Marcadores no texto:
  ## Serviço: ms-cliente
  [[service:ms-pagamento]]
  <!-- service: ms-cliente -->

Não quer escrever o mapa nem os marcadores à mão?
  ../scripts/scan-repos.sh --workspace ~/dev/repos      # repos → mapa-servicos.yaml
  .venv/bin/python -m src.repo_index --workspace ~/dev/repos   # indexa o código
  .venv/bin/python -m src.marcar --explain              # de/para com evidência
  .venv/bin/python -m src.marcar --apply                # injeta [[service:id]] (.bak)

Depois:
  .venv/bin/python -m src.run historia --context ms-cliente
  .venv/bin/python -m src.run historia --all-contexts
