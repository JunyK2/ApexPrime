# Atualização ApexPrime — IA, fallback e painel

Esta atualização parte da instalação Redmi 6A que já executa as migrations 001–005.

## 1. Faça backup antes de substituir arquivos

No Redmi, salve uma cópia das configurações locais:

```bash
cd ~/ApexPrime
cp .env ~/ApexPrime.env.backup
cp frontend/config.js ~/ApexPrime-frontend-config.js.backup
```

Não compartilhe esses backups. O `.env` contém credenciais privadas. `frontend/config.js` contém somente a URL do Supabase e a chave pública `anon`/publishable.

## 2. Atualize o repositório

1. Baixe e extraia `ApexPrime-Atualizacao-IA-Dashboard.zip`.
2. Copie o conteúdo da pasta extraída para a raiz do repositório já existente, substituindo os arquivos do projeto.
3. Preserve a pasta `.git` do seu clone local.
4. Não substitua seu `.env` local nem seu `frontend/config.js` configurado. O arquivo `frontend/config.js` do pacote é um modelo vazio por segurança.
5. Faça commit e push para `main`. O workflow Pages publicará o novo PWA.

## 3. Atualize o Supabase (ordem obrigatória)

O pacote anterior instalado terminava na migration 005. Execute no SQL Editor, uma por vez e nesta ordem:

1. `006_ai_failover_exports_and_trade_reviews.sql`
2. `007_dashboard_permissions_and_indexes.sql`
3. `008_openrouter_dashboard_access.sql`

Não repita 001–005. A migration 006 adiciona atribuição de IA/modelo/modo do gráfico, exportações, revisões pós-trade, eventos de oportunidade, snapshots, controles e capital virtual inicial de 100 USDT. Se ela creditar o saldo de 20 para 100, registra a diferença de +80 no ledger. O bloco de atualização não credita novamente quando `initial_balance` já estiver em 100.

A migration 008 adiciona OPENROUTER ao diagnóstico e reforça as permissões de leitura usadas pelo dashboard.

## 4. Configure OpenRouter no Redmi

Crie uma API key no painel oficial do OpenRouter. No Redmi:

```bash
cd ~/ApexPrime
nano .env
```

Adicione ou atualize:

```env
OPENROUTER_API_KEY=SUA_CHAVE_OPENROUTER
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
```

Salve, depois:

```bash
chmod 600 .env
```

Não coloque a chave no GitHub, no PWA, em mensagens ou no Supabase. Gemini, Groq e Chart IMG continuam configurados como antes.

## 5. Atualize as dependências no Termux

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

O instalador atualiza `requirements.txt`, incluindo `tzdata`, para corrigir ambientes Termux em que o gerador de texto falhava com `No time zone found`. O código também faz fallback para `America/Sao_Paulo` se o fuso salvo for inválido.

## 6. Estratégia de IA

Em **Configurações → Estratégia de provedores**:

### Automática (recomendada)

1. Se o modo escolhido for Chart IMG, tenta gerar as cinco imagens 1D/4H/1H/15M/5M em 800×600.
2. Se o Chart IMG falhar, registra aviso e muda o conteúdo para candles tabulares.
3. Tenta Gemini primeiro, com imagens se disponíveis ou texto se a geração de imagens falhou.
4. Se Gemini falhar (incluindo 503/429/timeouts), tenta OpenRouter no roteador `openrouter/free`, inicialmente com imagens quando disponíveis.
5. Se o modelo gratuito selecionado pelo roteador não aceitar visão, tenta OpenRouter novamente com o gráfico em texto.
6. Se OpenRouter falhar, tenta Groq com o gráfico em texto.
7. Todas as tentativas são registradas em `ai_requests`; a análise vencedora grava provedor, modelo, origem e tipo efetivo de gráfico na execução/trade.

O roteador `openrouter/free` seleciona dinamicamente modelos gratuitos disponíveis. A lista, disponibilidade, limites e suporte a visão variam ao longo do tempo; não é garantia de que sempre haverá um modelo gratuito disponível nem de que todo modelo aceitará imagens. A API key OpenRouter é necessária.

### Provedor/modelo fixo

Escolhe um provedor e modelo específico. Nesse modo o ApexPrime não percorre a cadeia inteira de fallback; se o provedor fixo falhar, a análise falha e é registrada. Para OpenRouter fixo com imagens, o sistema ainda tenta o mesmo modelo com o gráfico em texto caso a tentativa de visão falhe.

## 7. Chart IMG 800×600

Todas as imagens são solicitadas em `width=800` e `height=600`, respeitando a resolução máxima do plano free que você informou. A falha de resolução deve desaparecer. Se o Chart IMG retornar outro erro, o worker registra WARN e muda automaticamente para texto; ele não deve ficar repetindo a mesma requisição de imagem no mesmo ciclo.

## 8. Groq

- Verificação de saúde do servidor: padrão de 4 horas.
- Nas configurações do PWA é possível selecionar intervalo de 1 a 48 horas.
- O daemon relê a preferência do Supabase periodicamente.
- O botão **Relatório Groq completo** solicita um relatório imediato sob demanda.
- Separadamente, quando uma operação fecha, o worker solicita uma revisão pós-trade ao Groq, pois essa análise foi pedida para cada trade. A revisão usa a tese original, o texto dos candles entre entrada e saída, os custos e o desfecho.

## 9. Funções do painel adicionadas/atualizadas

- Remoção do destaque azul de toque no celular; o foco de teclado continua visível.
- Contagem de requisições de todos os provedores (não apenas Gemini).
- Taxa de acerto geral e filtro Gemini/OpenRouter/Groq/externa.
- Análises externas: cole o texto com `[APEX_TABLE]`, confira os campos e confirme a abertura virtual.
- Botões para copiar os prompts Chart IMG e Texto.
- Exportação de candles em texto na data/hora escolhida. A data deve existir no histórico público da Binance.
- Exportação das imagens atuais do Chart IMG. O endpoint gera a visão atual, não imagens históricas da data selecionada.
- Imagens podem abrir em nova aba para salvar quando o navegador bloquear download cross-origin.
- Adição de saldo virtual com descrição e lançamento no ledger.
- Histórico de trade identifica origem/provedor/modelo/modo de gráfico e resultado completo/parcial/loss.
- Timeline do Redmi, gráfico de bateria e estimativa de autonomia calculada a partir da tendência recente. A estimativa não é previsão garantida; depende de carga, temperatura e uso.
- Gráfico dos eventos avaliados pelo detector, com controles de sensibilidade.
- Gráfico de candles durante posição aberta com entry, stop, TP1, TP2, breakeven (quando ativado) e PnL estimado pelo mark price mais recente.
- Resultado de cada operação é enviado ao Telegram com WIN/LOSS, PnL e contexto. Em seguida, uma revisão Groq pode ser enviada com análise original e contexto dos candles entre entrada e saída. Para análises externas, a origem fica identificada como EXTERNAL.

## 10. Capital e simulação do tamanho mínimo

A migration 006 atualiza o capital virtual inicial para 100 USDT. Se seu saldo existente estiver diferente por causa de trades ou depósitos, confira o ledger antes de ajustar. Para adicionar saldo extra use a seção **Adicionar saldo virtual**; cada depósito é auditável.

A opção **Simular tamanho mínimo da Binance Futures** usa o notional configurado (padrão 100 USDT) como filtro de simulação. Ela não cria margem nem capital; se o tamanho mínimo exigir risco acima do limite de 2%, a ordem é bloqueada, não aumenta o risco automaticamente. Desative a opção nas configurações para não aplicar esse filtro.

## 11. Como conferir que ficou certo

1. PWA → Testes: execute os testes e confira Gemini, OpenRouter, Groq, Chart IMG, Binance, Supabase, Telegram e gerador de texto.
2. A análise deve mostrar o provedor/modelo efetivamente usado e `chart_img` ou `text`.
3. Se Gemini retornar 503, o log deve mostrar o fallback para OpenRouter e/ou Groq.
4. Se Chart IMG falhar, a análise deve seguir com candles em texto.
5. PWA → Testes: baixe um gráfico em texto; escolha uma data passada para testar histórico.
6. PWA → Testes: gere as imagens; verifique que cada uma é 800×600.
7. PWA → Análises: copie um prompt, rode externamente e cole uma APEX_TABLE; confira a confirmação antes de criar o trade virtual.
8. Feche uma operação de teste e confira ledger, categoria do resultado, Telegram e revisão pós-trade.
9. PWA → Configurações: altere Groq para 4h e verifique o resumo de cadência.

## 12. Segurança e limitações

Esta edição permanece em **paper trading exclusivamente**. `PAPER_TRADING_ONLY=true` e `APEX_REAL_TRADING_ENABLED=false` são obrigatórios; o worker recusa inicialização fora desse modo. Não há envio de ordens reais à Binance.

O PnL no gráfico é uma estimativa com base no mark price mais recente e não inclui necessariamente cada efeito intrabar antes de a próxima atualização. Funding e tarifas continuam aproximações configuráveis. O OpenRouter free pode sofrer limites temporários e a resposta das IAs não é garantia de acerto.
