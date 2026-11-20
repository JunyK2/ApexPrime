# Estado da entrega — Parte 2

Esta pasta acrescenta o worker modular Python, o motor de execução simulada, integrações externas e workflows. O ZIP mesclado contém também todos os arquivos-base da Parte 1.

## Banco de dados

- `001_initial_schema.sql`: migration inicial da Parte 1. Já executada pelo usuário; não executar novamente.
- `002_pending_entries.sql`: executar uma única vez agora. Cria `pending_entries` para PULLBACK/CONFIRMACAO e adiciona `trades.last_market_candle_at`, cursor independente para leitura incremental de candles de 1 minuto.
- Ao usar Chart IMG, o worker tenta criar o bucket público `apexprime-charts` no Supabase Storage e arquiva imagens públicas de gráficos por `run_id/timeframe`.

## Verificação local realizada

- Compilação Python de todos os módulos.
- Testes unitários de parser APEX_TABLE.
- Testes do dimensionamento de posição, taxas maker/taker e limite de risco.
- Testes de detecção do gatilho TradingView.
- Testes de preenchimento PULLBACK/CONFIRMACAO.
- Teste de retomada do monitor pelo cursor de candles, separado de `updated_at`.
- Testes de upload Storage com chamadas HTTP simuladas.
- Testes de falha de notificação Telegram sem expor o token.

Os testes unitários não validam credenciais ou disponibilidade real dos provedores. Faça os testes de integração pelo workflow depois de cadastrar Secrets válidos.
