# Segredos do ApexPrime — Redmi 6A

Nesta edição, o worker roda no Termux. Portanto, as chaves privadas do servidor ficam em `~/ApexPrime/.env`, no armazenamento privado do Termux, e **não** em GitHub Actions Secrets. O GitHub Actions não executa análise de mercado nem trades.

## Configuração local

1. Copie `config/.env.redmi6a.example` para `.env` na raiz do projeto.
2. Preencha `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CHART_IMG_API_KEY`, `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Proteja o arquivo com `chmod 600 .env`.
4. Nunca envie `.env` ao GitHub ou ao PWA.

## PWA

O frontend estático só recebe `SUPABASE_URL` e `SUPABASE_ANON_KEY` em `frontend/config.js`. A chave `anon`/publishable é pública por definição e deve ser restringida por Auth + RLS. Nunca use `SUPABASE_SERVICE_ROLE_KEY` no navegador.

## Telegram

O token de bot divulgado no pedido inicial deve ser considerado comprometido. Revogue-o pelo `@BotFather` e use um token novo apenas no `.env` local.

## Binance

Esta edição utiliza apenas endpoints públicos de mercado USDⓈ-M Futures. Não preencha `BINANCE_FUTURES_API_KEY` nem `BINANCE_FUTURES_API_SECRET`. A execução real de ordens não está implementada nem habilitada; `PAPER_TRADING_ONLY=true` e `APEX_REAL_TRADING_ENABLED=false` devem permanecer assim.

## Repositório público

O arquivo `.env` é ignorado pelo Git. Confira antes de cada commit que não está adicionando tokens, chaves, arquivos SQLite, logs ou outros dados privados. Se uma chave for publicada, revogue/rotacione-a: apagar o commit não é suficiente.
