Coloque aqui os insumos:

  figma.json          (opcional)
  regras.yaml         (opcional)
  *.txt | *.md        documentos de texto
  *.docx              Word moderno
  *.doc               Word legado (macOS: textutil; senão antiword)

A pipeline NÃO envia o arquivo bruto ao LLM.
Fluxo docs: chunk (40 linhas) → resumo extrativo → consolidado ≤ ~800 chars (~200 tokens).

Depois:
  .venv/bin/python -m src.run openapi --dry-run
