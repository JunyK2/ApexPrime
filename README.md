# ApexPrime — Redmi 6A Edition

Robô de **paper trading BTCUSDT USDⓈ-M Futures** executado localmente no Redmi 6A via Termux. O GitHub hospeda o código e o PWA; não executa o worker de mercado.

## Cadência do servidor

- Heartbeat do Redmi: 60 segundos.
- Gestão de trades virtuais e entradas pendentes: 60 segundos.
- Telemetria de bateria/Wi-Fi: 5 minutos.
- Fila de comandos PWA: 30 segundos.
- Scan do mercado: 15 minutos, usando candles 1H fechados como fonte da estratégia.
- Groq recebe o estado do Redmi e da operação: 15 minutos.
- Gemini: somente quando houver um gatilho novo ou solicitação manual.

## Instalação

Siga `docs/REDMI6A-INSTALACAO-COMPLETA.md`. Execute a migration `003_redmi_device_monitoring.sql` depois das migrations 001 e 002.

## Segurança

- Paper trading obrigatório nesta versão.
- `APEX_REAL_TRADING_ENABLED=false`.
- Não há envio de ordens reais; não adicione chaves privadas Binance nesta edição.
- `.env` é local e ignorado pelo Git. Service Role nunca vai ao PWA.
- Use um token Telegram novo: qualquer token divulgado anteriormente deve ser revogado.

## Execução local

```bash
bash android/termux/install.sh
# configure .env
bash scripts/start-apexprime.sh
```

Ver status: `bash scripts/status-apexprime.sh`. Ver logs: `tail -f runtime/daemon.log` e `tail -f runtime/supervisor.log`.

Guia detalhado: `docs/REDMI6A-INSTALACAO-COMPLETA.md`.

## Escopo atual do PWA

O PWA desta edição entrega login administrativo e monitoramento do Redmi 6A (bateria, Wi-Fi, temperatura, uptime, timeline online/offline e resumo Groq). Os controles completos do painel de trading previstos no projeto original ainda precisam de uma etapa própria de frontend; o worker de paper trading continua funcionando no Termux.
