# ApexPrime — instalação da Parte 2/3

Esta etapa acrescenta o worker Python, o detector Pine portado, a análise Gemini, Chart IMG, gerador tabular, monitoramento Groq, Telegram, simulador de posições e workflows do GitHub Actions.

> **Importante:** é somente paper trading. O projeto usa endpoints públicos de mercado da Binance. Não existe chamada para criar, alterar ou cancelar ordens reais. A alavancagem é apenas uma variável do cálculo de margem virtual.

## 1. Atualizar seu repositório

1. Baixe `ApexPrime-Parte-2.zip`.
2. Extraia o ZIP.
3. Copie o conteúdo da pasta extraída para a raiz do mesmo repositório `ApexPrime`, aceitando mesclar as pastas.
4. Não apague nem execute novamente `001_initial_schema.sql`; ele já foi instalado na Parte 1.
5. Abra `supabase/migrations/002_pending_entries.sql` no SQL Editor do Supabase e execute uma vez. Essa migration cria a tabela de entradas virtuais pendentes para PULLBACK/CONFIRMACAO e adiciona `trades.last_market_candle_at`, cursor independente para o monitor de candles de 1 minuto.
6. Faça commit e push para `main`.

A Parte 2 inclui o projeto inteiro mesclado, então também pode comparar os arquivos da Parte 1. Se o GitHub mostrar que `prompts` já existe, mantenha os dois prompts da Parte 1 (eles também estão incluídos nesta entrega).

## 2. Registrar o UID como administrador

Se você ainda não executou o cadastro de administrador, no Supabase abra **SQL Editor → New Query** e rode o comando abaixo, substituindo o valor pelo UID real do usuário que você criou em Authentication → Users:

```sql
insert into public.apex_admins (user_id)
values ('COLE-SEU-UID-AQUI')
on conflict (user_id) do nothing;
```

Não coloque o UID em arquivo público, issue ou commit. Ele não é uma senha, mas o cadastro de administrador deve ser feito apenas pelo proprietário do projeto.

## 3. Cadastrar GitHub Secrets

No repositório: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Valor |
|---|---|
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Chave `service_role` do Supabase (somente backend) |
| `GEMINI_API_KEY` | Chave Gemini API |
| `GROQ_API_KEY` | Chave Groq (opcional se Groq estiver desativado) |
| `CHART_IMG_API_KEY` | Chave Chart IMG (obrigatória quando `analysis_mode=chart_img`) |
| `TELEGRAM_BOT_TOKEN` | Token novo, já rotacionado pelo BotFather |
| `TELEGRAM_CHAT_ID` | ID do canal/grupo Telegram |

A chave `SUPABASE_ANON_KEY` será usada no PWA na Parte 3; é deliberadamente pública e sempre protegida por Auth + RLS. Nunca use `service_role` no navegador.

O token Telegram que foi colocado na primeira mensagem deve ser revogado, mesmo que o canal seja privado. Cadastre somente o token novo.

## 4. Ativar GitHub Actions

1. Abra a aba **Actions** no repositório.
2. Caso o GitHub peça, habilite workflows.
3. Abra **ApexPrime — testes** e execute `Run workflow` para rodar os testes locais sem chamar provedores externos.
4. Abra **ApexPrime — scan horário** e execute `Run workflow` para testar o worker completo.
5. Abra **ApexPrime — fila de comandos** e execute `Run workflow` para processar comandos pendentes.

Schedules configurados:

- `hourly-scan.yml`: uma vez por hora (`0 * * * *`). Monitora operações abertas, lê o último candle 1H fechado e só chama Gemini quando o gatilho Pine é ativado.
- `manual-queue.yml`: a cada cinco minutos (`*/5 * * * *`). Processa solicitações do PWA: análise forçada, fechar trade ou rodar testes. O scan horário também revisa a fila de entradas pendentes usando candles de 1 minuto fechados.
- `ci.yml`: roda testes Python a cada push/PR.

O GitHub Actions pode atrasar execuções programadas em períodos de alta demanda. Não trate o horário do cron como execução garantida ao segundo.

## 5. Cron-job.org

Não configure o token do GitHub nem a `service_role` no cron-job.org. Isso contrariaria a regra de deixar credenciais privilegiadas somente no GitHub Secrets. Os dois cron schedules do GitHub Actions já executam a automação. O cron-job.org pode ser usado apenas para monitorar disponibilidade por URL pública, sem enviar comandos privilegiados; o watchdog externo será opcional.

## 6. Como a estratégia opera

### Gatilho 1H — portado do TradingView

- Volume: volume do candle fechado >= 1,5 × SMA(20), incluindo o candle atual na média, igual ao Pine.
- Sweep: rompe e recupera a mínima/máxima dos 16 candles anteriores.
- Displacement: corpo >= 1,5 × SMA(10) dos corpos, incluindo o candle atual.
- FVG: low atual > high[2] para bullish; high atual < low[2] para bearish.
- Pontuação: 2 de 3 pilares.
- Cooldown: 3 candles por direção, com a comparação estrita `bar_index - last_signal > cooldown`, como no seu script.
- Se LONG e SHORT forem disparados no mesmo candle, o worker bloqueia o conflito e não solicita execução automática. Isso é uma proteção conservadora: o Pine original desenha os dois rótulos e prioriza COMPRA no texto do dashboard.
- Apenas candles fechados são considerados.

### Análise multi-timeframe

O worker busca candles fechados de 1D, 4H, 1H, 15M e 5M via USDⓈ-M Futures REST. O Binance Vision tem um módulo adicional de download dos arquivos históricos diários para backfill/pesquisa; seus arquivos são publicados após o dia fechar, então não são usados para preço em tempo real.

### Modos Gemini

- `chart_img`: solicita cinco imagens ao endpoint `POST /v2/tradingview/advanced-chart` da Chart IMG, tenta arquivá-las no bucket público `apexprime-charts` do Supabase Storage (por `run_id/timeframe`) e envia as imagens inline ao Gemini. O bucket é criado automaticamente pelo worker. Ele contém somente prints de mercado público; os links podem ser exibidos pelo histórico do PWA. Se o Storage falhar, a análise Gemini ainda continua, mas o replay visual daquela execução ficará sem a imagem correspondente.
- `text`: monta tabelas cronológicas com OHLCV, RSI(14), MACD e horário local, e envia ao Gemini.
- O valor `apex_settings.analysis_mode` decide o modo. Prompt personalizado não vazio substitui integralmente o prompt padrão; campo NULL/vazio usa o arquivo padrão.

### Execução virtual e risco

- Saldo inicial 20 USDT.
- O tamanho parte de risco máximo de 2% do saldo atual, incluindo estimativa de comissão de entrada e stop; em seguida é limitado pela margem disponível × alavancagem máxima.
- Alavancagem fica limitada a 20x. Ela restringe o notional/margem, não multiplica o risco permitido.
- Entradas imediatas e de confirmação usam taker; entradas PULLBACK preenchidas exatamente no limite são simuladas como maker, enquanto fills com gap são taker. TP1/TP2 são simulados como ordens limite maker; stop, breakeven e saída manual usam taker. As taxas vêm de `apex_settings.maker_fee_rate` e `apex_settings.taker_fee_rate`. O dimensionamento considera taxa de entrada correspondente e taxa taker de stop.
- O cursor de leitura de candles de 1 minuto é persistido em `trades.last_market_candle_at` e `pending_entries.last_checked_at`. Ele é separado de `updated_at`, para não perder candles entre execuções horárias.
- Funding é consultado no histórico público Binance e aplicado nos períodos publicados depois da abertura. É uma aproximação por mark price e quantidade remanescente no momento da verificação; após longos atrasos, a alocação por intervalo pode ser aproximada.
- Ao tocar 1R, o stop é movido ao breakeven.
- TP1 fecha 50% da quantidade inicial; TP2 fecha o restante.
- Se um candle de 1 minuto tocar stop antes do fechamento, o simulador fecha pelo stop; se stop e alvo forem tocados no mesmo intervalo, o stop vence por conservadorismo, já que OHLC não revela a sequência intrabar.
- Operações são monitoradas nas execuções horárias usando candles 1m fechados.

### Tipos de entrada e setups pendentes

A migration `002_pending_entries.sql` adiciona uma tabela separada para entradas pendentes e a coluna `trades.last_market_candle_at`; as operações em `trades` continuam usando apenas `OPEN` e `CLOSED`. `updated_at` não é usado como cursor de mercado porque o trigger SQL o atualiza em qualquer mudança do trade.

- `IMEDIATA`: abre posição virtual no mark price atual se estiver até 0,25% da entrada sugerida (configurável por `MAX_ENTRY_DEVIATION_PCT`). Os níveis estruturais são deslocados pelo preço de preenchimento real.
- `PULLBACK`: cria entrada virtual pendente; LONG procura toque do preço de entrada em retração e SHORT aplica a lógica inversa. Se o stop estrutural ou TP1 for alcançado antes do preenchimento, o setup é cancelado por segurança.
- `CONFIRMACAO`: cria entrada virtual pendente; LONG exige candle de 1 minuto abrir abaixo/no preço-gatilho e fechar acima/no gatilho; SHORT exige o inverso. O preenchimento usa o fechamento do candle e continua sujeito ao limite de desvio e ao dimensionamento de risco.
- Entradas pendentes expiram em 12 horas por padrão (`PENDING_ENTRY_EXPIRY_HOURS`, limitado de 1 a 72 horas). O monitor percorre todos os candles 1m fechados desde a última verificação. Se stop ou TP1 for tocado antes do preenchimento, inclusive no mesmo candle de um possível toque de entrada, o setup é cancelado porque OHLC não revela a sequência intrabar.

A execução continua virtual; a tabela `pending_entries` representa apenas estados simulados, sem ordens enviadas à Binance.

### Fim de semana

`avoid_weekends` é lido no Supabase e avaliado usando o fuso configurado em `apex_settings.timezone` (padrão `America/Sao_Paulo`). O sistema pode analisar no fim de semana, mas não abre trade novo nem preenche uma entrada pendente em candles de fim de semana quando a opção está ativada.

## 7. Testar manualmente no seu computador (opcional)

Requer Python 3.11+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Para testar o worker localmente, copie `config/.env.example` para `.env`, preencha apenas no computador e rode:

```bash
python -m apexprime.main tests
python -m apexprime.main hourly
python -m apexprime.main queue
```

Não envie `.env` ao GitHub.

## 8. Problemas comuns

- **`GEMINI_API_KEY ausente`**: confira o nome exato do Secret.
- **`404 model not found`**: confirme se a chave pertence ao projeto Gemini API/AI Studio e se o modelo configurado em `apex_settings.gemini_model` está habilitado para essa conta.
- **`CHART_IMG_API_KEY ausente`**: necessário quando `analysis_mode=chart_img`; no modo `text` não é necessário.
- **`permission denied` no Supabase**: confirme `SUPABASE_SERVICE_ROLE_KEY` no GitHub Secret. Nunca substitua pela `anon` no worker.
- **Gemini analisou, mas não abriu trade**: veja `apex_logs` e `pending_entries`; causas comuns são NO_TRADE, divergência da direção do gatilho, setup pendente já existente, expiração, fim de semana bloqueado, desvio de preço ou limite de posições/margem.
- **Sem execução programada**: confira se Actions está habilitado, se o repositório não desabilitou schedules por inatividade e se o workflow teve execução recente.
