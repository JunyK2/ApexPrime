# ApexPrime — Redmi 6A · Paper Trading

Sistema autônomo de simulação BTCUSDT USDⓈ-M Futures executado no Redmi 6A via Termux. O GitHub hospeda o código, executa CI e publica o PWA; o motor de mercado funciona localmente no celular.

> **Somente paper trading.** Não envia ordens reais, não lê saldo real e bloqueia qualquer configuração de execução real.

## Recursos atuais

- Scan a cada 15 minutos usando candles 1H fechados; manutenção das posições e entradas pendentes a cada minuto.
- Detector baseado no Pine fornecido: volume, sweep, displacement + FVG, cooldown e sensibilidade configurável.
- Chave independente de IA automática ON/OFF: com OFF, detector, eventos, Telegram, Groq operacional, trades existentes e análises manuais externas continuam; nenhuma imagem/texto de mercado é enviado a Gemini/OpenRouter pela análise automática ou forçada.
- Chart IMG solicitado em 800×600; se falhar, o motor muda para candles em texto.
- Estratégia de IA automática Gemini → OpenRouter `openrouter/free`; Gemini tem até cinco tentativas com 120 s entre respostas transitórias de alta demanda. OpenRouter tenta visão e depois texto quando necessário. **Groq não participa da cadeia de análise.**
- Groq fica reservado para saúde do Redmi, relatório operacional compacto sob demanda e resumo pós-trade curto sem gráficos/candles enviados ao Groq.
- Indicadores/contexto: Open Interest e variação, Funding Rate, Long/Short Ratio, ATR(14), ICT Killzones, compressão/volatilidade e Premium/Discount; valores objetivos são anexados aos prompts de texto e também aos prompts com imagens.
- Dois perfis de prompt: Original/Institucional e Momentum + Proteção (experimental), com TP1 na primeira zona estrutural razoável e TP2 na zona seguinte; score validado entre 0 e 10.
- Stop protetor estima taxas já lançadas, funding contabilizado e buffer; após TP1 recalcula a proteção da posição remanescente. Não garante cobertura em gaps, slippage ou funding futuro.
- Chart TradingView `BINANCE:BTCUSDT.P` com 5m, 15m, 1h, 4h e 1D.
- PWA AMOLED preto, acento branco, layout mobile sem rolagem horizontal, canvas com altura fixa, operações, histórico/replay, prompts, exports, análises externas, depósitos virtuais e logs.
- Sinal sonoro isolado do Redmi: onda quadrada 440 Hz/2 s, agendamento e som contínuo, com PIN validado no servidor. Não envia Telegram nem altera trades.
- Monitoramento da bateria, carregamento, temperatura, Wi-Fi, sinal, uptime, timeline online/offline e autonomia estimada.
- Saldo virtual de 100 USDT por padrão; risco máximo por operação 2%, alavancagem simulada até 20x e filtro de tamanho mínimo opcional.
- Revisão Groq pós-trade curta e pacote Telegram com resultado WIN/LOSS, PnL líquido, análise original e gráfico textual entrada-saída (o gráfico textual vai ao Telegram, não ao Groq).

## Cadência

| Tarefa | Intervalo |
|---|---:|
| Sinal sonoro / fila isolada | Poll ~1 s |
| Heartbeat | 60 s |
| Gestão de operações/entradas | 60 s |
| Snapshot candles/mark para dashboard | 60 s |
| Fila geral PWA | 30 s |
| Telemetria do Redmi | 5 min |
| Scan de oportunidades | 15 min (candle 1H fechado) |
| Groq health-check | 4 h por padrão, 1–48 h configurável |
| Revisão Groq pós-trade | Após cada encerramento, independente do health-check |

## Atualização de instalação já existente

Para a atualização atual sobre a versão que já tem migrations 001–008, siga `docs/ATUALIZACAO-UX-AUDIO-IA.md` e execute 009, 010 e 011 no Supabase, nessa ordem. Não execute novamente migrations já aplicadas.

## Configuração segura

- `PAPER_TRADING_ONLY=true`
- `APEX_REAL_TRADING_ENABLED=false`
- `SUPABASE_SERVICE_ROLE_KEY` somente no `.env` local do Termux.
- PWA recebe somente URL Supabase e chave pública `anon`/publishable.
- Nunca comite `.env`, tokens Telegram, API keys ou chaves privadas.
- O módulo de sinal sonoro não depende de Telegram. O PIN não fica em texto no frontend ou SQL: o banco armazena hash bcrypt salgado.

## Ícones do PWA

Quando os ícones novos forem colocados no GitHub, substitua `frontend/icon-192.png` e `frontend/icon-512.png` mantendo os nomes e proporções quadradas. O manifest e favicon já usam esses caminhos.

## Testes locais

```bash
python -m compileall -q apexprime
python -m pytest -q
node --check frontend/app.js
node --check frontend/sw.js
```

## Documentação

- `docs/ATUALIZACAO-UX-AUDIO-IA.md` — atualização atual de layout, IA, stop, TradingView e sinal sonoro.
- `docs/ATUALIZACAO-IA-DASHBOARD.md` — atualização anterior de IA, exports e painel.
- `docs/REDMI6A-INSTALACAO-COMPLETA.md` — instalação/boot do servidor.
- `docs/FINALIZACAO-PAPER-TRADING.md` — arquitetura paper trading.
- `SECURITY.md` — regras de segurança.

## Limitações

Resultados virtuais não predizem rentabilidade real. Taxas, funding, slippage, preenchimento intrabar e proteção fee-aware são aproximações. O PnL de mercado usa o mark price mais recente. A autonomia do Redmi é estimativa linear e não garantia. TradingView é widget externo e depende de conexão. O áudio usa a rota de mídia Android e o PWA só confirma que o worker marcou o comando como concluído, não que o som foi fisicamente ouvido. Execução real não está implementada e permanece bloqueada.
