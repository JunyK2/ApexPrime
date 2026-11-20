# Estado da entrega — Edição Redmi 6A

Esta versão incorpora as partes anteriores e altera o ambiente de execução: o worker de trading deixa de rodar nos GitHub Actions e passa a rodar localmente no Redmi 6A via Termux.

## Banco de dados

- `001_initial_schema.sql`: schema original. Já executado pelo usuário; não executar novamente.
- `002_pending_entries.sql`: entradas virtuais PULLBACK/CONFIRMACAO e cursor independente de candles 1m. Já executado pelo usuário; não executar novamente.
- `003_redmi_device_monitoring.sql`: tabelas `apex_devices`, `device_heartbeats` e `device_events`. Executar uma vez para esta edição.

## Funcionalidades desta edição

- Worker local Python no Termux; scan BTCUSDT a cada 15 minutos com sinal baseado em candle 1H fechado.
- Chart IMG alinhado ao contrato perpétuo Binance (`BINANCE:BTCUSDT.P`).
- Heartbeat a cada 60 segundos, telemetria de bateria/Wi-Fi a cada 5 minutos e timeline estimada.
- Alertas Telegram de bateria abaixo de 40%, rearmados em 45%.
- Groq recebe telemetria de saúde do Redmi e produz resumo operacional a cada 15 minutos.
- Supervisor local e Termux:Boot para recuperação após reinício/encerramento do worker.
- PWA de monitoramento em GitHub Pages; Actions fica restrito a CI e deploy estático.

## Verificações

- Compilação Python dos módulos.
- Testes do detector, parser APEX_TABLE, risco e simulação, monitor de candles, armazenamento e Telegram.
- Testes adicionais de parsing de telemetria Android.
- Total no ambiente de desenvolvimento: 19 testes aprovados.

Os testes não validam credenciais, conectividade real do Redmi, permissões MIUI/Termux, nem disponibilidade dos provedores. O primeiro boot automático e a recuperação de rede devem ser testados no aparelho real.
