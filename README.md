# ApexPrime v1.0 — Redmi 6A Edition

ApexPrime é um sistema autônomo de **paper trading BTCUSDT USDⓈ-M Futures**, executado no Redmi 6A via Termux. O GitHub hospeda o código, executa CI e publica o PWA; não executa o motor de mercado.

> **Esta distribuição é exclusivamente simulada.** O worker não contém integração para enviar ordens à Binance, não lê saldo real e bloqueia qualquer tentativa de ativar `APEX_REAL_TRADING_ENABLED=true`.

## Funcionalidades

- Scan de mercado a cada 15 minutos usando o último candle 1H fechado.
- Reprodução do gatilho TradingView SMC (volume, sweep, displacement + FVG, cooldown).
- Análises Gemini nos modos Chart IMG (1D, 4H, 1H, 15M, 5M) ou candles em texto.
- Prompts customizáveis no Supabase, com fallback aos prompts padrão do projeto.
- APEX_TABLE validada antes de qualquer mudança no saldo virtual.
- Paper trading com saldo inicial de 20 USDT, risco por trade limitado a 2%, alavancagem simulada limitada a 20x, TP1 parcial, breakeven e TP2.
- Entradas PULLBACK/CONFIRMACAO pendentes, expiração e cancelamento manual.
- Gestão de posição/stop/alvo a cada minuto, funding histórico e estimativa de taxas maker/taker.
- Proteção de perda diária configurável e pausa global de novas entradas.
- Alertas Telegram e análise operacional Groq, incluindo telemetria do Redmi.
- Telemetria de bateria, carregamento, temperatura, Wi-Fi, RSSI, uptime e timeline de heartbeat.
- PWA administrativo com dashboard, posições, histórico/replay, análises, prompts, configurações, testes e logs.
- Inicialização pelo Termux:Boot e supervisor que relança o processo Python.

## Cadência do servidor

| Tarefa | Intervalo |
|---|---:|
| Heartbeat | 60 s |
| Gestão de operações e entradas pendentes | 60 s |
| Fila de comandos do PWA | 30 s |
| Bateria/Wi-Fi/temperatura | 5 min |
| Scan de mercado com candle 1H fechado | 15 min |
| Groq — saúde do servidor | 15 min |
| Gemini | Só em novo gatilho ou análise manual |

## Instalação

Siga `docs/FINALIZACAO-PAPER-TRADING.md` para atualizar um projeto já instalado. Para instalação limpa no Redmi, consulte `docs/REDMI6A-INSTALACAO-COMPLETA.md`.

Migrations:

1. `001_initial_schema.sql` — schema base (já executada nas instalações anteriores).
2. `002_pending_entries.sql` — entradas pendentes/cursor (já executada anteriormente).
3. `003_redmi_device_monitoring.sql` — telemetria Redmi (já executada anteriormente).
4. `004_dashboard_individual_actions.sql` — comandos de saída/cancelamento por operação.
5. `005_automation_risk_controls.sql` — pausa de novas entradas e limite de perda diária.

Em quem já executou 001–003, execute somente 004 e 005 agora.

## Configuração segura

- `PAPER_TRADING_ONLY=true`
- `APEX_REAL_TRADING_ENABLED=false`
- `BINANCE_FUTURES_API_KEY` e `BINANCE_FUTURES_API_SECRET` vazias/não usadas.
- `SUPABASE_SERVICE_ROLE_KEY` permanece apenas no `.env` local do Termux.
- O PWA recebe somente Supabase URL + chave `anon`/publishable, com RLS e autenticação.
- Nunca comite `.env`, tokens Telegram ou chaves privadas.

## Uso

```bash
bash android/termux/install.sh
# configure .env, sem enviar o arquivo ao GitHub
bash scripts/start-apexprime.sh
bash scripts/status-apexprime.sh
```

Logs:

```bash
tail -f runtime/daemon.log
tail -f runtime/supervisor.log
```

Parada manual:

```bash
bash scripts/stop-apexprime.sh
```

## Testes

```bash
python -m compileall -q apexprime
python -m pytest -q
node --check frontend/app.js
node --check frontend/sw.js
```

O botão **Executar testes** no PWA envia um comando ao Redmi para testar Binance Futures público, Supabase, gerador texto, Gemini, Groq, Chart IMG e Telegram. A chamada do Telegram envia uma mensagem real de teste ao canal; provedores de IA podem consumir cota.

## Avisos operacionais

- O preço/candle de execução é obtido da Binance Futures pública. Disponibilidade de API e acesso a USDⓈ-M Futures podem variar por rede/região/conta. O teste do endpoint precisa funcionar no Redmi.
- Chart IMG e Gemini trabalham com dados/prints públicos; a IA pode interpretar imagens incorretamente. A validação do JSON impede campos inválidos, mas não prova que a análise esteja correta.
- A simulação usa candles de 1 minuto fechados e uma regra conservadora quando stop e alvo aparecem no mesmo candle: o stop é considerado primeiro.
- Maker/taker, slippage e funding são aproximações configuráveis; não equivalem a resultado real de exchange.
- O Redmi deve permanecer ventilado e com Wi-Fi estável. O software não pode ligar o aparelho se ele desligar fisicamente por falta de bateria.
- Paper trading não garante rentabilidade. Acompanhe logs, amostras e comportamento por um período prolongado antes de tirar conclusões sobre a estratégia.

## Estrutura

- `apexprime/` — motor, mercado, IA, risco, paper execution e telemetria.
- `frontend/` — PWA administrativa.
- `supabase/migrations/` — schema e atualizações.
- `prompts/` — prompts padrão Gemini.
- `android/termux/` e `scripts/` — instalação, boot e supervisor.
- `tests/` — testes unitários.
- `docs/` — arquitetura, instalação e segurança.
