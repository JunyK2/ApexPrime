# GitHub Secrets — ApexPrime

No repositório, abra **Settings → Secrets and variables → Actions → New repository secret**.

| Nome | Conteúdo | Observação |
|---|---|---|
| `SUPABASE_URL` | URL do projeto Supabase | Não é senha, mas ficará apenas no worker também. |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key | Privilegiada; nunca colocar no PWA. |
| `GEMINI_API_KEY` | Chave da Gemini API | Somente worker. |
| `GROQ_API_KEY` | Chave da Groq API | Somente worker. |
| `CHART_IMG_API_KEY` | Chave Chart IMG | Somente worker. |
| `TELEGRAM_BOT_TOKEN` | Token novo do bot | Revogar o token exposto antes de usar. |
| `TELEGRAM_CHAT_ID` | ID do canal | Não é senha, mas manter como secret simplifica a configuração. |

## Configuração pública do PWA

Um frontend estático precisa conhecer `SUPABASE_URL` e `SUPABASE_ANON_KEY` para inicializar o cliente Supabase. A chave `anon` é deliberadamente pública: ela não é a service-role key e sua segurança depende de Auth + RLS. Na etapa de build, as duas variáveis serão injetadas no bundle público; portanto, qualquer pessoa poderá inspecionar a chave `anon`. Nunca use a `service_role` no navegador.

## Segurança do token Telegram exposto

O token incluído no pedido inicial deve ser considerado comprometido:
1. Abra o `@BotFather` no Telegram.
2. Use `/revoke` para o bot afetado (ou gere um token novo pelo fluxo do BotFather).
3. Atualize `TELEGRAM_BOT_TOKEN` no GitHub Secret com o token novo.
4. Não cole o token novo em issues, código, commits ou mensagens públicas.

## Regras do repositório público

- Não versionar `.env`, `.env.local`, tokens, arquivos de configuração reais nem respostas contendo credenciais.
- Habilitar secret scanning e push protection no GitHub, quando disponíveis.
- Não registrar headers de autorização ou URLs que contenham chaves.
- Redigir erros de API antes de gravar em `apex_logs`.
- Se uma chave for publicada, revogá-la/rotacioná-la; apagar o commit sozinho não a torna segura.
