# Security policy

- Este repositório é público: nunca comite credenciais.
- A aplicação é paper trading; não implemente nem habilite endpoints de ordens reais.
- Chaves privilegiadas somente no GitHub Actions Secrets.
- O frontend usa exclusivamente Supabase Auth + `anon` + RLS.
- O token Telegram divulgado no pedido precisa ser revogado e substituído antes de qualquer teste.
- Não inclua tokens, headers Authorization ou payloads secretos nos logs.
