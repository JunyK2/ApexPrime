# Arquitetura ApexPrime

## Componentes

### 1. Frontend PWA (GitHub Pages)
- HTML/CSS/JavaScript leve, tema escuro AMOLED, fonte Inter e ícones Lucide.
- Usa Supabase Auth e a chave pública `anon` com Row Level Security.
- Lê configurações, prompts, saldo, operações, estatísticas, logs e histórico.
- Para forçar uma análise, insere uma solicitação em `public.run_requests`.
- Nunca recebe `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CHART_IMG_API_KEY` ou `TELEGRAM_BOT_TOKEN`.

### 2. GitHub Actions
- `hourly-scan`: execução programada uma vez por hora; avalia apenas candles fechados e aplica o gatilho do script.
- `manual-queue-worker`: verifica a fila de solicitações em intervalos curtos e executa análises forçadas. A cadência exata será configurada no workflow da parte 2.
- O `GITHUB_TOKEN` automático do Actions será usado apenas para operações do próprio workflow, sem ser exposto ao browser.

### 3. Supabase
- Auth restringe o painel ao(s) administrador(es) cadastrado(s).
- RLS protege todas as tabelas.
- Chaves privilegiadas só são usadas no worker do GitHub Actions.
- `run_requests` funciona como fila entre o PWA e o worker.
- `balance_ledger` mantém trilha auditável de alterações do saldo virtual.

### 4. Dados de mercado
- Binance Vision é apropriado para backfill/histórico arquivado; os arquivos diários ficam disponíveis no dia seguinte.
- Para candles recentes, preço de marcação e funding atual, o worker também deverá consultar os endpoints públicos REST de USDⓈ-M Futures da Binance. Não se deve tratar o arquivo diário do Vision como cotação em tempo real.
- A estratégia de gatilho será calculada em candles de 1H fechados, enquanto os timeframes 1D, 4H, 1H, 15M e 5M serão usados na análise multi-timeframe.

### 5. Provedores de IA e imagens
- Gemini `gemini-4-hydrogen`: análise. O modo selecionado no Supabase determina se o worker envia cinco imagens Chart IMG ou dados tabulares.
- Chart IMG: endpoint avançado v2, com `x-api-key` no header; as imagens serão obtidas no worker, nunca no navegador.
- Groq `openai/gpt-oss-120b`: verificação de saúde/alertas, quando ativada.

## Portabilidade do Pine Script enviado

O arquivo `tradingview/SMC_Gemini_Trigger_Detector.txt` foi recebido como referência. A regra do detector é:

- Explosão de volume: volume atual >= 1,5 × SMA(volume, 20).
- Bull sweep: mínima atual abaixo da menor mínima das 16 barras anteriores e fechamento acima desse nível.
- Bear sweep: máxima atual acima da maior máxima das 16 barras anteriores e fechamento abaixo desse nível.
- Deslocamento: corpo atual >= 1,5 × SMA dos corpos absolutos dos 10 candles anteriores.
- FVG bullish: low atual > high[2]. FVG bearish: high atual < low[2].
- Pontuação bullish/bearish: soma dos três pilares; gatilho quando pontuação >= 2.
- Apenas candle confirmado; cooldown de 3 candles por direção.

Observações para a implementação:
- A comparação de corpo deve usar o mesmo alinhamento de janela do Pine Script e candles fechados.
- O cooldown é independente para LONG e SHORT.
- O robô não deve duplicar análise para a mesma vela/sinal; `system_runs` e identificadores de candle devem permitir idempotência.
- O script é um detector de gatilho, não uma estratégia completa nem garantia de rentabilidade.

## Gestão de risco pretendida

- Saldo virtual inicial: 20 USDT.
- Risco nominal por trade: 2% do saldo atual.
- Alavancagem máxima: 20x (limite de margem/notional, não aumento do risco permitido).
- O tamanho será limitado pelo menor entre o tamanho calculado pelo risco até o stop e o notional máximo permitido pela margem disponível × alavancagem.
- Taxas de entrada/saída e funding serão debitados no simulador. As taxas padrão no schema são apenas valores iniciais configuráveis; devem ser verificadas conforme o tipo de conta/nível VIP e o tipo de ordem.
- TP1 fecha 50% da quantidade inicial; o stop passa a breakeven após a regra definida no motor; TP2 fecha o restante.
- Se o limite de margem reduzir a posição, o risco efetivo ficará abaixo de 2%; nunca se aumenta a posição para forçar 2% quando isso ultrapassa o teto de alavancagem.

## Primeiro administrador

Após criar o usuário em Supabase Auth:

1. Abra **Authentication → Users** e copie o UUID do seu usuário.
2. No SQL Editor, execute substituindo o UUID:

```sql
insert into public.apex_admins (user_id)
values ('COLE-O-UUID-DO-USUARIO-AQUI')
on conflict (user_id) do nothing;
```

Somente usuários cadastrados em `apex_admins` terão acesso ao painel.

## Cron-job.org

A execução horária será feita pelo agendador do GitHub Actions. Para preservar o requisito de segredo apenas no GitHub, o cron-job.org não receberá token de GitHub nem token de serviço. Seu uso será opcional como watchdog externo/monitor de disponibilidade, configurado na parte de automação sem credenciais privilegiadas. O worker também terá `workflow_dispatch` para testes manuais pelo próprio GitHub.
