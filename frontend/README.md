# ApexPrime PWA — painel administrativo

O PWA administra **paper trading virtual** e monitora o Redmi 6A.

## Configuração

1. Preserve/preencha `config.js` com `SUPABASE_URL` e `SUPABASE_ANON_KEY` (somente chave pública).
2. Nunca inclua `service_role`, chaves de IA, Binance secrets ou Telegram token no frontend.
3. Publique a pasta no GitHub Pages pelo workflow `pages.yml`.
4. Adicione a URL do Pages em Supabase Authentication > URL Configuration.
5. Entre com usuário criado no Supabase e provisionado em `apex_admins`.

## Painel

- Visão geral: saldo virtual, PnL, taxa de acerto, preço BTCUSDT, gatilho recente, saúde Redmi e timeline.
- Operações: posições abertas, entradas pendentes, saída individual, fechar todas e cancelar entrada.
- Histórico: trades fechados, detalhes e replay de eventos.
- Análises: runs Gemini, contadores, detalhe APEX_TABLE/imagens e fila de comandos.
- Configurações: modo Chart IMG/Text, risco, alavancagem virtual, taxas, perda diária, pausa de entradas, weekend filter, Groq, funding e prompts customizados.
- Testes: resultados dos provedores e comandos.
- Logs: auditoria INFO/WARN/ERROR.

O PWA usa Supabase Auth + RLS e chave pública anon. O worker local do Termux usa `SUPABASE_SERVICE_ROLE_KEY`; essa chave nunca deve ser distribuída ao navegador.

A interface não envia ordens reais. Toda ação de trade é encaminhada para o worker local e processada na conta virtual.
