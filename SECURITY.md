# Segurança — ApexPrime

1. Este worker foi projetado para paper trading. Não adicione endpoints privados de trading da Binance.
2. `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CHART_IMG_API_KEY` e `TELEGRAM_BOT_TOKEN` ficam no arquivo `.env` privado do Termux no Redmi 6A; não em GitHub Secrets nem no repositório.
3. Nunca use a chave Supabase `service_role` no frontend/PWA.
4. O token Telegram compartilhado no pedido inicial deve ser revogado e substituído.
5. Mantenha `PAPER_TRADING_ONLY=true`.
6. Não grave Authorization headers, tokens ou URLs com chave nos logs.
7. O worker é um único processo local no Redmi 6A; evite iniciar duas cópias simultâneas para não duplicar manutenção ou comandos.
8. O projeto é experimental e não constitui aconselhamento financeiro nem valida a rentabilidade da estratégia.


## Redmi 6A edition
- Local server secrets reside only in `~/ApexPrime/.env` on the phone; keep mode 600 and never commit it.
- The PWA contains only the Supabase anon public key. Never put service_role, Telegram, Gemini, Groq, Chart IMG, or Binance private keys in frontend files.
- Real Binance order placement is not implemented in this build; paper-only is enforced.
