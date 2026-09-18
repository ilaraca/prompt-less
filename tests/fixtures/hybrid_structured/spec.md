# Cadastro de Cliente

## Regras de validação

O endpoint POST /clientes exige CPF válido.
bloqueio CPF inválido retorna HTTP 400.

## Autenticação

Quando o token estiver ausente a API responde 401.
permissão insuficiente responde 403.

## Fluxo feliz

Dado cliente autenticado Quando payload válido Então status 200.
