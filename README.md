# ApexPrime — Redmi 6A · Paper Trading

Sistema autônomo de simulação BTCUSDT USDⓈ-M Futures executado no Redmi 6A via Termux. O GitHub hospeda o código, faz CI e publica o PWA; o motor de mercado funciona no celular.

> **Somente paper trading.** Não envia ordens reais, não lê saldo real e bloqueia qualquer configuração de execução real.

## Recursos

- Scan a cada 15 minutos usando candles 1H fechados; manutenção de operações a cada minuto.
- Detector baseado no script Pine enviado: volume, sweep, displacement + FVG, cooldown e sensibilidade configurável.
- Roteamento automático Gemini → OpenRouter `openrouter/free` → Groq; visão primeiro quando há imagens e fallback para candles em texto.
- Chart IMG limitado a 800×600; quando falha, análise muda para candles tabulares.
- Configuração automática ou provedor/modelo fixo.
- Histórico registra provedor, modelo, origem manual/automática e tipo efetivo de gráfico.
- Análise externa via APEX_TABLE com confirmação antes de abrir trade virtual.
- Paper trading com saldo inicial de 100 USDT, risco máximo de 2%, alavancagem simulada até 20x, TP1, breakeven e TP2.
- Filtro opcional de notional mínimo da Binance; não aumenta o risco se o mínimo não couber no orçamento de risco.
- Depósitos virtuais auditados no ledger, win-rate geral/por provedor e histórico/replay.
- Exportação de candles em texto (inclusive data passada) e imagens atuais Chart IMG.
- Gráficos do mercado/operação aberta, eventos do detector e bateria/autonomia aproximada do Redmi.
- Groq health-check a cada 4h por padrão, ajustável entre 1 e 48h, relatório sob demanda e revisão pós-trade.
- Telegram recebe resultados WIN/LOSS, PnL, análise original, contexto de candles e revisão Groq quando disponível.
- Termux:Boot, supervisor, telemetria, timeline online/offline e fila Supabase.

## Cadência

| Tarefa | Intervalo |
|---|---:|
| Heartbeat | 60 s |
| Gestão de operações/entradas | 60 s |
| Fila do PWA | 30 s |
| Telemetria do Redmi | 5 min |
| Scan de oportunidade | 15 min (candle 1H) |
| Groq health check | 4 h por padrão (configurável) |
| Revisão Groq pós-trade | Após cada trade encerrado |

## Atualização de instalação já existente

Siga `docs/ATUALIZACAO-IA-DASHBOARD.md`. A instalação anterior deste projeto tem migrations 001–005. Para esta versão, execute 006, 007 e 008 no Supabase, na ordem apresentada no guia.

## OpenRouter

Adicione no `.env` do Redmi:

```env
OPENROUTER_API_KEY=SUA_CHAVE
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
```

No modo automático, `openrouter/free` usa o roteador de modelos gratuitos disponível no OpenRouter. Disponibilidade, limites e suporte a imagens podem variar; a cadeia tem fallback para texto e Groq.

## Configuração segura

- `PAPER_TRADING_ONLY=true`
- `APEX_REAL_TRADING_ENABLED=false`
- `SUPABASE_SERVICE_ROLE_KEY` somente no `.env` local do Termux.
- PWA recebe somente URL do Supabase e chave pública `anon`/publishable.
- Nunca comite `.env`, tokens do Telegram ou chaves privadas.

## Testes locais

```bash
python -m compileall -q apexprime
python -m pytest -q
node --check frontend/app.js
node --check frontend/sw.js
```

## Documentação

- `docs/ATUALIZACAO-IA-DASHBOARD.md` — atualização desta versão.
- `docs/REDMI6A-INSTALACAO-COMPLETA.md` — instalação/boot do servidor.
- `docs/FINALIZACAO-PAPER-TRADING.md` — arquitetura paper trading.
- `SECURITY.md` — regras de segurança.

## Limitações

Resultados virtuais não predizem rentabilidade real. Taxas, funding, slippage e fill de candles são aproximações. O PnL mostrado no gráfico usa o mark price mais recente. As estimativas de autonomia do Redmi são tendências, não garantias. A execução real de ordens está ausente e bloqueada.
