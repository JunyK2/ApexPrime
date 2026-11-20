# ApexPrime v1.0 — estado final do projeto

Esta distribuição incorpora as partes anteriores e finaliza o PWA administrativo para o worker Redmi 6A.

## Banco de dados

- `001_initial_schema.sql`: schema, configurações, prompts, conta virtual, trades, ledger, runs, Gemini, logs e fila.
- `002_pending_entries.sql`: entradas virtuais PULLBACK/CONFIRMACAO e cursor independente de candles 1m.
- `003_redmi_device_monitoring.sql`: `apex_devices`, `device_heartbeats` e `device_events`.
- `004_dashboard_individual_actions.sql`: habilita saída individual e cancelamento individual na fila.
- `005_automation_risk_controls.sql`: pausa de entradas e limite de perda diária.

Quem já executou 001–003 deve executar apenas 004 e 005.

## Worker Redmi

- Heartbeat 60s; telemetria 5min; gestão trades/pendências 60s; fila 30s; scan mercado 15min; Groq 15min.
- Detector TradingView usa candle 1H fechado e os três pilares do Pine.
- Gemini Chart IMG (1D/4H/1H/15M/5M) ou candles em texto.
- APEX_TABLE validada antes de afetar o saldo virtual.
- PaperExecutor, sem endpoints privados de conta ou ordens Binance.
- Limite risco 2%, alavancagem simulada 20x, TP1 parcial, breakeven, TP2, funding e taxas simuladas.
- Entradas pendentes expiram e podem ser canceladas pelo painel.
- Limite diário bloqueia novas entradas.

## PWA final

- Dashboard com saldo, PnL, win rate, preço BTCUSDT e último gatilho.
- Saúde Redmi, bateria, carregamento, temperatura, Wi-Fi, RSSI, uptime, timeline.
- Posições abertas, saída individual, fechar todas, entradas pendentes e cancelamento.
- Histórico de trades, eventos, detalhes e replay em intervalos de aproximadamente 3 segundos.
- Análises Gemini, APEX_TABLE, imagens armazenadas, contadores e fila de comandos.
- Configurações de modo, prompts, risco, alavancagem, taxas, fim de semana, Groq, funding, pausa e perda diária.
- Testes dos provedores e logs filtráveis.

## Segurança e limites

- Exclusivamente paper trading; `PAPER_TRADING_ONLY=true`; `APEX_REAL_TRADING_ENABLED=false`.
- O código bloqueia a inicialização se a configuração tentar ativar modo real.
- O PWA usa apenas Supabase URL e anon/public key; o service role fica no Termux.
- A simulação não garante fills reais nem rentabilidade.

## Testes no ambiente de desenvolvimento

Total: **30 testes aprovados**. CI verifica Python e sintaxe JS. Testes de provedores/credenciais, conectividade e inicialização MIUI precisam continuar sendo executados no próprio Redmi pelo menu Testes.
