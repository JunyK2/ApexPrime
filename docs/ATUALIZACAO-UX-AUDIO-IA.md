# ApexPrime — atualização UX, AI toggle, TradingView e sinal 440 Hz

Esta atualização parte da edição Redmi 6A que já tem as migrations 001–008. Ela acrescenta:

- correção do dimensionamento lógico dos canvas; a altura passa a ser fixa e não aumenta a cada refresh;
- layout responsivo AMOLED preto, acento branco e proteção contra overflow horizontal no login, topbar e popups;
- widget TradingView de `BINANCE:BTCUSDT.P` com 5m, 15m, 1h, 4h e 1D;
- chave independente **IA automática ON/OFF**;
- perfil experimental **Momentum + Proteção** com TP1 na primeira zona estrutural próxima e TP2 na zona seguinte;
- score estritamente de 0 a 10, com validação/correção no backend;
- contexto OI, variação de OI, Funding, LSR, ATR(14), ICT Killzones, compressão/volatilidade e Premium/Discount nos dados tabulares e também como valores medidos junto ao prompt visual;
- Chart IMG limitado a 800×600;
- Gemini com até cinco tentativas totais, aguardando 120 s entre tentativas quando a resposta for 503/429/alta demanda; se persistir, passa ao OpenRouter;
- OpenRouter `openrouter/free`, tentando visão e depois texto; Groq não participa da cadeia de análise;
- Groq reservado à saúde, relatório sob demanda e resumo pós-trade compacto (sem candles, prints ou resposta completa da IA);
- stop protetor que estima taxas de entrada/saída, funding contabilizado e buffer configurado; após TP1 recalcula a proteção para a posição restante;
- aba isolada **Sinal do aparelho**, com desbloqueio por PIN, beep quadrado de 440 Hz por 2 s, agendamento e repetição contínua, sem Telegram e sem interação com as tabelas de trading.

## Atualizar sem perder o que já foi configurado

### 1. Backup

No Termux:

```bash
cd ~/ApexPrime
cp .env ~/ApexPrime.env.backup
cp frontend/config.js ~/ApexPrime-config.js.backup
```

Não publique nem compartilhe esses backups. O `.env` contém chaves privadas. O `frontend/config.js` deve conter apenas `SUPABASE_URL` e a chave pública `anon`/publishable.

### 2. Atualizar o GitHub

Extraia o ZIP e copie o conteúdo para a raiz do repositório existente, substituindo arquivos antigos. Preserve `.git`, seu `.env` local e o `frontend/config.js` configurado. O arquivo de configuração do PWA dentro do ZIP é um exemplo vazio; restaure o arquivo local caso tenha sido substituído.

Faça commit e push para `main`. O workflow GitHub Pages publicará a versão nova.

### 3. Migrations Supabase

Se seu banco já tem as migrations 001–008, execute apenas as seguintes, nesta ordem:

1. `009_ai_toggle_prompt_profile_and_fee_stop.sql`
2. `010_device_square_wave_signal.sql`
3. `011_fee_aware_stop_and_signal_lock.sql`

Não repita migrations já aplicadas. 009 adiciona o controle de análise automática, o perfil de prompt e o buffer de stop. 010 cria o módulo do sinal sonoro isolado. 011 acrescenta a classificação de stop com custos cobertos e reforça o travamento que cancela comandos pendentes/em execução.

A migration 010 grava apenas um hash bcrypt salgado para o PIN já definido durante a configuração. O PIN em si não está gravado em texto no repositório, no banco ou no JavaScript. Há bloqueio temporário após cinco tentativas incorretas.

### 4. Atualizar o Redmi

No Termux:

```bash
cd ~/ApexPrime
bash scripts/stop-apexprime.sh
git pull --ff-only
bash android/termux/install.sh
chmod 600 .env
python -m compileall -q apexprime
python -m pytest -q
node --check frontend/app.js
node --check frontend/sw.js
bash scripts/start-apexprime.sh
bash scripts/status-apexprime.sh
```

O processo de sinal sonoro usa `Termux:API` e os comandos `termux-media-player` e `termux-volume`. Confirme que o aplicativo Termux:API está instalado pela mesma origem/assinatura do Termux e que o pacote `termux-api` está instalado dentro do terminal. Se ausente:

```bash
pkg install termux-api
```

O worker faz polling isolado aproximadamente a cada segundo para que o sinal não espere o scan, Groq ou uma resposta do Gemini. O recurso não envia Telegram e não altera trades. O painel confirma sucesso somente depois que o Redmi reporta o comando como `COMPLETED`.

### 5. Configuração e comportamento

**IA automática ON/OFF**

- ON: oportunidades elegíveis podem seguir para Gemini/OpenRouter.
- OFF: o detector continua, grava oportunidades, envia alertas Telegram de oportunidade, a saúde Groq e as revisões pós-trade continuam; trades manuais externos continuam disponíveis. Nenhum gráfico ou texto de mercado é enviado automaticamente (nem por “Forçar análise”) ao Gemini/OpenRouter enquanto estiver OFF.
- A opção separada de permitir novas entradas automáticas continua controlando a execução virtual. Desligar a análise IA não fecha operações abertas nem interrompe o gerenciamento dos stops/alvos.

**Provedores**

- Estratégia automática: Gemini primeiro; em erro de alta demanda são feitas até cinco tentativas totais com 120 s entre tentativas; depois OpenRouter.
- OpenRouter gratuito tenta imagem quando suportado; caso contrário tenta candles em texto.
- Groq fica fora do roteamento de análise; usa-se apenas em health-check, resumo geral e revisão de resultado com payload compacto.

**Prompt Momentum + Proteção**

É experimental. Pede entrada imediata apenas com confirmação direcional, TP1 na primeira zona estrutural objetiva (não metade arbitrária), TP2 na próxima zona com espaço para retorno adicional. Não garante que a direção estará certa nem que o stop proteja todos os custos. Compare os resultados líquidos de uma amostra suficientemente grande com o perfil original antes de escolher.

**Stop com custos**

O stop procura incluir taxas lançadas de entrada/saída, funding já debitado e buffer configurado, e após TP1 recalcula usando a parcial realizada e a quantidade remanescente. Isso é estimativa de paper trading: funding futuro, gap, slippage, taxas reais e preenchimentos não são garantidos. Se o movimento ainda não permitir cobrir custos sem colocar o stop além de TP1, o worker registra proteção defensiva na entrada e tenta recalcular depois de mais movimento.

### 6. Sinal sonoro 440 Hz

Na PWA, abra **Sinal do aparelho**:

1. Destrave a função usando o PIN fornecido pelo proprietário durante a configuração.
2. **Enviar Sinal** toca uma onda quadrada mono de 440 Hz por 2 s.
3. **Agendar sinal** cria um comando futuro; o site pode ser fechado, desde que Redmi, rede e worker estejam online no horário.
4. **Som contínuo ON/OFF** inicia/interrompe a repetição. Travar também interrompe o som contínuo e cancela comandos pendentes.
5. Esta função é separada do trading e não envia Telegram.

A saída usa a rota de mídia atual do Android. Se o Redmi reconhecer o fone conectado, o som deve sair pelo fone; o software não consegue confirmar fisicamente qual saída foi selecionada. O volume de mídia é aumentado ao máximo somente durante o sinal e depois tenta restaurar o nível anterior. Faça o primeiro teste com o fone fora dos ouvidos: áudio em volume máximo pode causar dano auditivo.

### 7. Ícones próprios

Quando adicionar seus ícones ao GitHub, substitua estes arquivos mantendo os mesmos nomes:

- `frontend/icon-192.png`
- `frontend/icon-512.png`

O `manifest.webmanifest` e o favicon já apontam para esses caminhos. Use PNG quadrado; publique o commit e limpe/atualize o cache do PWA se os ícones antigos permanecerem visíveis.

## Verificação

- Abra o dashboard e deixe pelo menos dois ciclos de refresh; os gráficos de bateria, oportunidades e trades devem manter sua altura fixa.
- Reduza a largura do navegador e confirme que o botão Sair/popups cabem sem rolagem horizontal da página.
- Alterne o widget TradingView entre os cinco timeframes.
- Desligue IA automática: os novos eventos devem continuar na timeline/Telegram, mas não devem criar chamadas de análise Gemini/OpenRouter.
- Teste colagem de APEX_TABLE externa com o switch IA OFF: a confirmação e a criação do paper trade devem continuar funcionando.
- Teste som imediato com fone fora do ouvido; o histórico deve mudar para `COMPLETED` e o site exibir confirmação. Teste agendamento, ON/OFF contínuo e travar durante a execução.
- Confira se volume de mídia retorna ao nível anterior após beep/stop contínuo.

## Limites

O PWA não pode saber se o áudio foi ouvido fisicamente; `COMPLETED` significa que o comando de reprodução do Android foi iniciado e o intervalo de duração transcorreu. Se o aparelho desligar ou perder rede, o comando não será executado até o worker voltar. O serviço de som é separado do Telegram e do motor de trades.
