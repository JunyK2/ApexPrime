# Segurança ApexPrime

- Esta distribuição é exclusivamente paper trading. Não contém envio de ordem real.
- `PAPER_TRADING_ONLY=true` é obrigatório; `APEX_REAL_TRADING_ENABLED=true` causa bloqueio na inicialização.
- Não cadastre ou distribua credenciais privadas Binance nesta edição.
- Nunca comite `.env`, tokens Telegram, API keys Gemini/Groq/Chart IMG ou chave Supabase service role.
- `SUPABASE_SERVICE_ROLE_KEY` fica apenas no Redmi/Termux em arquivo `.env` com permissão 600.
- O PWA contém apenas Supabase URL e chave `anon`/publishable; RLS, Auth e `apex_admins` restringem o painel.
- Revogue imediatamente qualquer token Telegram que tenha sido compartilhado publicamente e crie outro.
- Não publique dumps de banco, logs com headers de autenticação ou snapshots que contenham segredos.
- Não faça upload de chaves/segredos ao Supabase Storage. O bucket de gráficos serve apenas imagens de mercado.
- Uma chave de conta real, se usada em outro software no futuro, deve ter permissões mínimas e nunca permissão de saque; essa implementação não a utiliza.
- Os sinais Gemini/OpenRouter são sugestões não confiáveis. O motor valida formato e limites, mas isso não garante qualidade preditiva ou rentabilidade.
- O módulo 440 Hz é isolado do trading e Telegram; o PIN é comparado por RPC contra hash bcrypt no servidor, com bloqueio temporário após tentativas incorretas.
- O sinal usa o volume de mídia do Android no máximo durante a reprodução e tenta restaurar o nível anterior. O volume máximo pode causar dano auditivo; testar com fone fora dos ouvidos.
- O status COMPLETED comprova que o worker iniciou e aguardou o intervalo da reprodução, não que o som foi ouvido nem qual saída física foi selecionada.
