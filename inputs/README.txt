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

Depois:
  .venv/bin/python -m src.run historia --context ms-cliente
  .venv/bin/python -m src.run historia --all-contexts
