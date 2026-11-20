# Arquitetura ApexPrime — Redmi 6A

## Componentes

### 1. Servidor local — Redmi 6A / Termux
- Termux executa o worker Python e um supervisor que relança o processo se ele encerrar inesperadamente.
- Termux:Boot inicia o supervisor após o Android reiniciar; `termux-wake-lock` mantém a CPU ativa.
- O worker usa Binance USDⓈ-M Futures apenas para dados públicos, Gemini para análise, Groq para saúde operacional, Chart IMG para os cinco gráficos, Supabase para persistência e Telegram para alertas.
- O worker faz heartbeat a cada 60 segundos, telemetria a cada 5 minutos, gestão de trades virtuais a cada 60 segundos, fila a cada 30 segundos e scan a cada 15 minutos.
- A estratégia detecta sinais com candles 1H fechados. A frequência de scan de 15 minutos só verifica se há um candle 1H recém-fechado; ela não transforma o gatilho em estratégia de 15 minutos.

### 2. GitHub
- O repositório público armazena código e frontend.
- GitHub Actions executa CI/testes e publica apenas o PWA no GitHub Pages.
- Não executa consultas Binance, análise Gemini, gestão de trades, fila de comandos nem monitoramento do Redmi.

### 3. PWA — GitHub Pages
- HTML/CSS/JavaScript com Supabase Auth e chave `anon`/publishable.
- Exibe estado online/offline estimado, bateria, carregamento, temperatura, SSID, sinal Wi-Fi, uptime, última telemetria e timeline de heartbeats.
- Mostra resumo recente do Groq e alerta visual de bateria baixa; notificações do navegador dependem de permissão e de o navegador/PWA estar ativo. Telegram é o alerta remoto.
- Apenas o usuário presente em `apex_admins` pode ler as tabelas via RLS.
- A chave `service_role` e as demais chaves privadas permanecem no `.env` local do Termux.

### 4. Supabase
- `apex_settings`, `apex_prompts`, `paper_accounts`, `trades`, `pending_entries`, logs, runs e contagem Gemini persistem o motor de paper trading.
- `apex_devices`, `device_heartbeats` e `device_events` armazenam telemetria e histórico aproximado de disponibilidade.
- O painel acessa somente leitura administrativa via Auth + RLS; worker usa service role no ambiente privado do Termux.

### 5. Dados de mercado e gráficos
- Dados de preço: endpoints públicos Binance USDⓈ-M Futures em `https://fapi.binance.com`.
- Símbolo gráfico Chart IMG: `BINANCE:BTCUSDT.P`, contrato perpétuo, para alinhar os gráficos ao mercado Futures usado pelo motor.
- Timeframes de contexto: 1D, 4H, 1H, 15M e 5M. O detector de oportunidade usa 1H fechado.

## Portabilidade do Pine Script enviado

- Explosão de volume: volume atual >= 1,5 × SMA(volume, 20).
- Bull sweep: mínima atual abaixo da menor mínima das 16 barras anteriores e fechamento acima desse nível.
- Bear sweep: máxima atual acima da maior máxima das 16 barras anteriores e fechamento abaixo desse nível.
- Deslocamento: corpo atual >= 1,5 × SMA dos corpos absolutos dos 10 candles anteriores.
- FVG bullish: low atual > high[2]. FVG bearish: high atual < low[2].
- Pontuação bullish/bearish: soma dos três pilares; gatilho quando pontuação >= 2.
- Apenas candle confirmado; cooldown de 3 candles por direção.

## Segurança e limites

- Esta edição é paper trading obrigatório; não implementa envio de ordens reais.
- `APEX_REAL_TRADING_ENABLED=false` e `PAPER_TRADING_ONLY=true` são validados na inicialização.
- Campos para chave Binance privada existem apenas como placeholders vazios e não são usados.
- O período OFFLINE é inferido pela ausência de heartbeat; não permite distinguir um telefone desligado de um telefone ligado sem internet.
- A telemetria enviada ao Groq inclui SSID do Wi-Fi, RSSI, bateria, carregamento, temperatura e uptime, mas omite IP local e payloads brutos.
- A timeline apresentada no PWA cobre as últimas 24 horas e usa um limite de ausência de 180 segundos.
