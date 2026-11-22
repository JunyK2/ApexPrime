# ApexPrime — estado atual do projeto

## Banco de dados

A instalação existente tem migrations 001–008. Esta atualização acrescenta:

- `009_ai_toggle_prompt_profile_and_fee_stop.sql`: IA automática ON/OFF, perfil de prompt e buffer extra do stop protetor; restringe provedores de análise a Gemini/OpenRouter.
- `010_device_square_wave_signal.sql`: RPCs, segurança e fila do sinal sonoro 440 Hz, isoladas do trading e do Telegram.
- `011_fee_aware_stop_and_signal_lock.sql`: persistência de estado de proteção fee-aware e cancelamento imediato de comandos sonoros ao travar.

## Worker Redmi

- Scan 15 min com candle 1H fechado, oportunidade deduplicada por candle.
- Gestão de operações, pendências e stops a cada minuto.
- Fila geral em thread própria; Gemini pode esperar/repetir sem parar heartbeat, manutenção ou som.
- Thread de sinal sonoro independente, polling ~1 s.
- Groq health-check configurável (4 h padrão), relatório sob demanda e resumos pós-trade compactos.
- Groq não é provedor de análise.

## IA e contexto de mercado

- Gemini até cinco tentativas totais, intervaladas por 120 s apenas para 503/429/alta demanda.
- OpenRouter `openrouter/free`: imagem, depois texto se visão não estiver disponível.
- Chart IMG 800×600; erro muda para texto.
- OI, variação de OI, Funding, LSR, ATR(14), ICT Killzones, compressão/expansão e Premium/Discount são calculados de forma best-effort.
- O bloco com valores desses indicadores é fornecido ao modelo nos modos imagem e texto.
- Score normalizado e validado no intervalo 0–10.
- Perfil Momentum + Proteção é experimental; TP1 escolhe a primeira zona estrutural observável, TP2 o próximo nível relevante.

## PWA

- Altura fixa dos canvas, correção de scroll horizontal, topbar responsiva e popup limitado ao viewport.
- Tema AMOLED preto, acento branco, foco de teclado visível e sem tap highlight azul.
- Widget TradingView perpétuo BTCUSDT e cinco intervalos.
- Chave IA automática independente do controle de novas entradas.
- Perfil de prompt, revisão de provedores, histórico por IA, relatório Groq, sinais manuais externos e exports.
- Sinal sonoro 440 Hz: enviar agora, agendar, contínuo ON/OFF e travar/destravar. Não envia Telegram.

## Segurança e limites

- Paper trading somente; não há execução real.
- `.env` local protegido; chaves privadas não entram no frontend.
- PIN do sinal só existe no banco como hash bcrypt salgado.
- O volume é elevado ao máximo durante o sinal e tenta ser restaurado ao nível anterior ao fim; faça o teste inicial com fone fora dos ouvidos.
- O PWA informa conclusão do comando, não pode comprovar fisicamente a saída de áudio.

## Testes

O conjunto de testes inclui geração WAV, restauração do volume de mídia, stop que considera custos, score 0–10, bloqueio de análises com AI OFF, compactação do relatório Groq, layout canvas e TradingView, além dos testes de estratégia, parser, mercado, storage e notificações.
