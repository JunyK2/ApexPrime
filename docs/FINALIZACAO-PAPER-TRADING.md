# Finalização ApexPrime — ativação do paper trading automático

Este guia é para quem já instalou a edição Redmi 6A e executou as migrations 001, 002 e 003. A atualização completa o painel PWA e adiciona proteções/controles do paper trading.

## 0. Escopo desta versão

O sistema fica apto a executar **operações virtuais automáticas** com dados públicos Binance USDⓈ-M Futures. Não há chamadas privadas de conta ou envio de ordens reais. O código bloqueia a inicialização quando `PAPER_TRADING_ONLY` não for `true` ou `APEX_REAL_TRADING_ENABLED` for `true`.

Não adicione chaves privadas de futuros ao `.env`. A API Key/Secret Binance não é necessária para candles, mark price ou histórico público de funding.

## 1. Atualizar o repositório sem perder sua configuração

1. Baixe e extraia o ZIP `ApexPrime-Completo-Redmi6A.zip`.
2. Copie os arquivos extraídos para a raiz do repositório que você já usa, mesclando/substituindo os arquivos do projeto.
3. **Preserve a pasta `.git`** do repositório local.
4. **Preserve o seu `frontend/config.js` que já está funcionando.** O ZIP não contém sua URL/chave anon particular. Se o arquivo for substituído pelo modelo vazio, restaure apenas:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY` ou publishable key pública
5. Confirme que `frontend/config.js` não contém `service_role`, `SUPABASE_SERVICE_ROLE_KEY`, chaves de IA ou token Telegram.
6. Faça commit e push para `main`.

O diretório `.github/workflows/` deve conter somente `ci.yml` e `pages.yml`. O primeiro roda os testes Python/JavaScript; o segundo publica o frontend. O worker e os scans rodam exclusivamente no Redmi.

## 2. Executar as migrations finais

No Supabase Dashboard > SQL Editor, execute, uma por vez, nesta ordem:

1. `supabase/migrations/004_dashboard_individual_actions.sql`
2. `supabase/migrations/005_automation_risk_controls.sql`

Não repita migrations 001, 002 ou 003. As migrations 004/005 são idempotentes em seus campos/constraints principais, mas ainda assim execute cada uma apenas uma vez e confira se o SQL Editor informa sucesso.

A migration 004 habilita na fila de comandos:

- `close_trade`: fechar uma operação virtual individual.
- `cancel_pending_entry`: cancelar uma entrada virtual individual.

A migration 005 acrescenta:

- `auto_trading_enabled`: pausa/retoma novas entradas virtuais.
- `max_daily_loss_pct`: limite diário calculado sobre o saldo inicial da conta virtual. Considera valores já lançados no `balance_ledger` (PnL realizado, taxas e funding); não considera PnL flutuante de posições ainda abertas.

## 3. Atualizar o Redmi pelo Termux

Confirme que o projeto continua em `~/ApexPrime`. Se estiver executando, pare-o:

```bash
cd ~/ApexPrime
bash scripts/stop-apexprime.sh
```

Depois atualize o repositório:

```bash
git pull --ff-only
```

Reinstale/verifique dependências sem sobrescrever seu `.env`:

```bash
bash android/termux/install.sh
chmod 600 .env
```

O instalador preserva o `.env` existente. Confira os valores essenciais:

```env
PAPER_TRADING_ONLY=true
APEX_REAL_TRADING_ENABLED=false
BINANCE_FAPI_BASE=https://fapi.binance.com
CHART_IMG_SYMBOL=BINANCE:BTCUSDT.P
MARKET_SCAN_INTERVAL_SECONDS=900
MAINTENANCE_INTERVAL_SECONDS=60
QUEUE_POLL_INTERVAL_SECONDS=30
DEVICE_HEARTBEAT_INTERVAL_SECONDS=60
DEVICE_TELEMETRY_INTERVAL_SECONDS=300
```

Deixe vazias e sem uso:

```env
BINANCE_FUTURES_API_KEY=
BINANCE_FUTURES_API_SECRET=
```

Não copie `.env` ao GitHub nem envie os segredos no chat. O token Telegram previamente exposto deve estar revogado e substituído por um token novo.

## 4. Publicar o novo PWA

O push que altera `frontend/**` inicia `Deploy ApexPrime PWA` automaticamente. Confira em GitHub > Actions.

No Supabase Authentication > URL Configuration, mantenha a URL do GitHub Pages na lista de URLs permitidas. Abra o app no endereço HTTPS e entre com o administrador Supabase já cadastrado em `apex_admins`.

Se o navegador mostrar a versão antiga:

1. Feche todas as abas do PWA.
2. Abra o endereço no navegador e atualize a página.
3. Se continuar antigo, remova o app instalado e os dados/cache do site; abra novamente e instale de novo.

A cache do service worker foi atualizada para `apexprime-pwa-v4`.

## 5. Conferir configurações antes de liberar o paper trading automático

No PWA > Configurações:

- Modo: `Chart IMG` ou `Gráfico em Texto`.
- Par: `BTCUSDT`.
- Risco: nunca acima de `2%`.
- Alavancagem simulada: no máximo `20x`.
- Máximo de posições: comece em `1`.
- Evitar finais de semana: escolha conforme sua estratégia.
- Groq e alertas: escolha se deseja manter habilitados.
- Funding: deixe habilitado se quiser contabilizar as taxas históricas da Binance.
- Limite diário de perda contabilizada: padrão `6%` do saldo virtual inicial. A proteção usa PnL/taxas/funding já lançados no ledger e não inclui lucro ou prejuízo flutuante de posições abertas.
- Permitir novas entradas automáticas: marque para autorizar novas entradas de paper trading.

O botão de pausa bloqueia **novas entradas**, inclusive as solicitadas por análise forçada. Posições abertas continuam sendo monitoradas e seus stops/alvos simulados continuam ativos. Pausar não fecha posições existentes.

Os prompts podem ser editados nas caixas Chart IMG e Gráfico em Texto. Campo vazio usa o prompt padrão versionado no repositório.

## 6. Teste final dos serviços

No PWA > Testes > Executar testes. O Redmi processará o comando em até aproximadamente 30 segundos se a rede/daemon estiverem ativos.

O painel deverá registrar verificações de:

- Binance: hora do servidor, candles Futures 1H fechados e mark price (o teste verifica as mesmas rotas de mercado usadas pelo worker).
- Supabase.
- Gerador de texto.
- Gemini.
- Groq.
- Chart IMG.
- Telegram.

O teste Telegram envia uma mensagem ao canal. Gemini/Groq/Chart IMG podem consumir quota/créditos. Um serviço sem chave pode aparecer como WARN, não como sucesso.

## 7. Como o automático decide e executa

1. O Redmi busca candles 1H fechados a cada 15 minutos.
2. O detector reproduz o gatilho Pine: volume explosivo, sweep e displacement+FVG; pelo menos dois pilares, cooldown por direção e candle confirmado.
3. Sem gatilho, salva o scan e não chama Gemini.
4. Com gatilho, prepara os cinco gráficos Chart IMG ou as tabelas de candles em texto, conforme a configuração.
5. Gemini devolve o bloco APEX_TABLE; o motor valida enums, preços, direção, R:R e score.
6. O sinal da IA precisa concordar com a direção do gatilho horário.
7. O motor consulta limites de risco, saldo, número de posições, pausa automática, fim de semana e perda diária já contabilizada no ledger (não inclui PnL flutuante).
8. Entrada IMEDIATA abre um trade virtual; PULLBACK/CONFIRMACAO fica em fila pendente e é avaliada com candles 1m fechados.
9. A cada minuto o monitor verifica entradas pendentes, stops, TP1, breakeven, TP2 e funding.
10. Logs, runs, contagem Gemini, eventos, ledger e notificações ficam registrados.

A simulação usa uma regra conservadora: quando stop e alvo são ambos tocados no mesmo candle 1m, considera o stop primeiro, pois o OHLC não informa a ordem intrabar. PULLBACK e TP1/TP2 podem ser contabilizados como maker sob hipótese de execução passiva; stops e saídas manuais usam taker. Isso é uma aproximação, não uma previsão garantida de fill real.

## 8. Controles do PWA

- **Forçar análise Gemini:** envia um comando ao Redmi para analisar agora. É uma chamada cobrada pelo provedor. O motor ainda respeita pause, perda diária e limites de risco.
- **Sair desta operação:** cria saída virtual pelo mark price obtido quando o Redmi processar a fila.
- **Fechar todas:** fecha as posições virtuais abertas e cancela entradas pendentes.
- **Cancelar entrada:** cancela apenas a entrada virtual escolhida.
- **Histórico / Replay:** mostra eventos gravados em sequência, com aproximadamente 3 segundos entre etapas.
- **Logs:** permite filtrar INFO, WARN e ERROR.
- **Testes:** consulta o histórico dos provedores e o resultado dos comandos.

Comandos dependem do Redmi estar online e conseguir falar com Supabase/Binance. Um comando enfileirado não significa que já foi executado; confira o status em Análises > Fila recente.

## 9. Checklist antes de deixar em operação contínua

- [ ] Migration 004 executada.
- [ ] Migration 005 executada.
- [ ] PWA atualizado e login funcionando.
- [ ] `.env` local correto, permissão `600` e fora do Git.
- [ ] Teste Binance retorna candles Futures e mark price.
- [ ] Todos os testes de serviço necessários estão OK.
- [ ] Telegram recebeu o teste.
- [ ] Redmi aparece ONLINE e a telemetria muda ao alterar Wi-Fi/carregador.
- [ ] Boot automático foi testado reiniciando o Redmi sem abrir Termux.
- [ ] `PAPER_TRADING_ONLY=true` e `APEX_REAL_TRADING_ENABLED=false`.
- [ ] Auto trading virtual está ligado apenas depois de revisar risco e prompts.
- [ ] O painel mostra saldo de 20 USDT e nenhuma entrada desconhecida.

Depois de iniciar, acompanhe alguns dias de paper trading, compare amostras e verifique taxas, funding, stops e logs. Resultados simulados não garantem rentabilidade nem correspondência exata a fills reais.

## 10. Diagnóstico rápido

**Redmi offline no PWA:** confira `bash scripts/status-apexprime.sh`, `runtime/daemon.log`, Wi-Fi e a última linha em `apex_devices`.

**Comando fica pending:** worker parado, Supabase sem conexão ou daemon sem conseguir consultar `run_requests`.

**Binance com 451/403:** trate como bloqueio de endpoint/região/rede. Não tente falsificar localização ou contornar a restrição; pause o motor até existir uma fonte acessível e autorizada.

**Gemini não é chamado:** pode não haver gatilho novo no último candle 1H; scans sem gatilho não consomem Gemini.

**Trade não abriu:** veja o log `execution`; possíveis motivos incluem direção Gemini divergente do Pine, desvio > 0,25%, posições pendentes, margem/risco, auto trading pausado, limite diário ou weekend filter.

**PWA sem dados:** confira `frontend/config.js` (somente URL + anon key), usuário em `apex_admins`, autenticação Supabase e RLS.
