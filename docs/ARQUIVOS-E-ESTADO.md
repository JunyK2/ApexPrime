# ApexPrime — estado da atualização IA + Dashboard

Esta edição atualiza o worker Redmi 6A, o motor de failover e o PWA administrativo.

## Banco de dados

A instalação anterior publicada terminava em 005. Para aplicar todos os recursos desta edição, execute 006, 007 e 008, nessa ordem, depois de 001–005:

- `006_ai_failover_exports_and_trade_reviews.sql`: roteamento/atribuição de IA, modo automático/fixo, Groq configurável, análises externas, exports, snapshots, eventos do detector, revisão pós-trade e capital virtual inicial de 100 USDT.
- `007_dashboard_permissions_and_indexes.sql`: grants, índices e leitura autenticada do dashboard.
- `008_openrouter_dashboard_access.sql`: diagnóstico OPENROUTER e reforço idempotente de permissões.

## Worker Redmi

- Heartbeat 60s; telemetria 5min; gestão de trades/pendências 60s; fila 30s; scan mercado 15min usando candle 1H.
- Estratégia auto Gemini → OpenRouter `openrouter/free` → Groq. Se imagem não for possível, tenta texto. Se Chart IMG falhar, muda para gráfico tabular.
- Chart IMG solicita exatamente 800×600.
- Groq health-check padrão 4h, configurável 1–48h e com cadência recuperada do último service check no Supabase ao reiniciar o daemon.
- Revisão Groq pós-trade separada do health-check; resultado/contexto continuam sendo enviados mesmo se Groq falhar.
- APEX_TABLE validada; paper executor sem endpoints privados/ordens Binance.
- Análise externa manual exige confirmação do administrador e fica identificada como EXTERNAL.

## PWA

- Remove tap highlight azul no celular, mantendo foco de teclado.
- Saldo/PnL/win rate geral e por provider; posições, histórico, atribuição IA e replay.
- Gráfico de candles com níveis e PnL estimado por mark price.
- Gráfico da bateria/autonomia aproximada e timeline de conectividade do Redmi.
- Gráfico de oportunidades/sensibilidade, prompts copiáveis, colagem manual APEX_TABLE.
- Depósito virtual auditado, export de candles históricos em texto e imagens atuais Chart IMG.
- Relatório Groq sob demanda, configurações de provider/modelo, testes e logs.

## Segurança e limites

- Exclusivamente paper trading; `PAPER_TRADING_ONLY=true`; `APEX_REAL_TRADING_ENABLED=false`.
- O worker bloqueia a inicialização se houver tentativa de ativar execução real.
- O PWA usa Supabase URL + anon/public key; `SUPABASE_SERVICE_ROLE_KEY` e todas as chaves de IA ficam no `.env` do Termux.
- `openrouter/free` escolhe entre modelos gratuitos disponíveis, mas limites, disponibilidade e visão variam conforme o catálogo do serviço.
- O PnL da tela é estimativa com mark price, não extrato real; taxas/funding e fills são aproximações.

## Testes automatizados

Total: **35 testes aprovados**. CI verifica compilação Python, sintaxe JavaScript e testes unitários. Provedores, credenciais, rede e inicialização MIUI devem ser testados no Redmi no menu Diagnóstico.
