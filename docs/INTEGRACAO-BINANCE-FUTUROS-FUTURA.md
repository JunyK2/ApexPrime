# Binance Futures — configuração futura, não habilitada nesta edição

O ApexPrime Redmi usa agora apenas endpoints públicos USDⓈ-M Futures (`/fapi/v1/klines`, `/fapi/v1/premiumIndex`, `/fapi/v1/fundingRate`). Isso não requer API Key.

As variáveis reservadas são:

```env
BINANCE_FUTURES_API_KEY=
BINANCE_FUTURES_API_SECRET=
APEX_REAL_TRADING_ENABLED=false
PAPER_TRADING_ONLY=true
```

Nesta edição, o motor recusa `APEX_REAL_TRADING_ENABLED=true` e não contém um caminho que envie ordens. Não preencha as chaves ainda. Qualquer etapa futura exigirá confirmar elegibilidade/termos diretamente com a Binance, verificar a legislação aplicável, ter idade legal para a conta e rever a implementação com testnet, ordens de proteção no servidor da corretora, reconciliação de posições e limites de perda.

Se a conta for autorizada no futuro, crie uma API dedicada, sem permissão de saque, com permissões mínimas e whitelist de IP se disponível. Nunca salve chave privada no frontend, GitHub ou Supabase. Uma resposta HTTP 451 deve ser tratada como restrição de acesso, não contornada com proxy ou falsificação de localização.
