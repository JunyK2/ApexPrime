# ApexPrime — Parte 1/3

Base de arquitetura, segurança, prompts iniciais e schema SQL do Supabase.

> **Modo exclusivamente paper trading.** Esta base não contém integração com endpoints de criação de ordens da Binance. O módulo de execução será um simulador local no worker e persistirá os resultados no Supabase.

## Conteúdo

- `supabase/migrations/001_initial_schema.sql`: banco completo inicial.
- `docs/arquitetura.md`: desenho das camadas e decisões técnicas.
- `docs/secrets.md`: nomes de GitHub Secrets e proteção de credenciais.
- `prompts/default-chart-img.md`: prompt padrão para 5 imagens.
- `prompts/default-text.md`: prompt padrão para candles tabulares.
- `tradingview/SMC_Gemini_Trigger_Detector.txt`: Pine Script enviado para referência/portabilidade.
- `config/.env.example`: nomes de variáveis (sem valores secretos).

## Ordem de instalação

1. Crie um repositório GitHub público chamado `ApexPrime`.
2. Copie o conteúdo desta pasta para a raiz do repositório.
3. No Supabase SQL Editor, execute `supabase/migrations/001_initial_schema.sql`.
4. Crie seu usuário em Supabase Auth e adicione o UUID dele à tabela `public.apex_admins` (passos em `docs/arquitetura.md`).
5. Configure os GitHub Secrets conforme `docs/secrets.md`.

**Não publique arquivos `.env` reais, service-role keys, chaves de IA, Chart IMG ou tokens Telegram.**

## O que ainda não está nesta primeira parte

O worker, a integração com Gemini/Chart IMG/Groq/Telegram, o simulador de posições e o frontend PWA serão entregues nas partes seguintes. O schema já prevê essas funcionalidades.
