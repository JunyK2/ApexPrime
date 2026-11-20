# ApexPrime no Redmi 6A — instalação completa

## Atualizar o repositório existente

Este ZIP substitui a versão de worker no GitHub Actions. Copie os arquivos desta edição para a raiz do seu repositório e envie um commit para `main`. **Apague** os workflows antigos `hourly-scan.yml` e `manual-queue.yml` de `.github/workflows/`; mantenha apenas `ci.yml` e `pages.yml` desta edição. Os workflows novos servem apenas para testes e publicação do PWA — o worker de mercado roda no Redmi.

Os GitHub Secrets da versão anterior deixam de ser usados pelo worker. Depois de transferir os valores necessários para o `.env` privado do Termux, você pode removê-los das configurações do GitHub. Não remova nem exponha chaves no frontend: somente a chave `anon`/publishable do Supabase pode aparecer em `frontend/config.js`.


## O que muda

O Redmi 6A executa o daemon Python local. O GitHub Actions deixa de executar scans e filas; o GitHub continua hospedando o código e o frontend PWA. O daemon usa Binance USDⓈ-M Futures público, Gemini, Groq, Chart IMG, Supabase e Telegram.

## Requisitos

- Redmi 6A com Android 8, root Magisk opcional (não é necessário para o funcionamento normal).
- Termux e Termux:API e Termux:Boot instalados pela mesma origem F-Droid.
- Wi-Fi conhecido com reconexão automática.
- Projeto Supabase e conta admin já criados.

## 1. Instalar complementos Android

1. Instale **Termux:API** e **Termux:Boot** pelo F-Droid. Não misture APKs de origens diferentes: Termux e plugins precisam ter a mesma assinatura.
2. Abra o Termux:Boot uma vez pelo ícone. Isso registra o plugin para o boot.
3. Abra Termux:API uma vez e conceda as permissões solicitadas.
4. Em Configurações do Android > Aplicativos > Termux:API > Permissões, permita Localização se o Android/MIUI pedir para mostrar SSID/RSSI. A leitura de Wi-Fi pode retornar dados vazios se a permissão/serviço de localização estiver bloqueado.
5. No Termux execute `termux-battery-status` e `termux-wifi-connectioninfo`; confirme que os comandos retornam JSON.

## 2. Preparar o código

No Termux:

```bash
termux-setup-storage
pkg update -y
pkg install -y git python termux-api
```

Clone seu repositório público em `~/ApexPrime` (substitua pela URL real):

```bash
cd ~
git clone https://github.com/SEU_USUARIO/ApexPrime.git ApexPrime
cd ~/ApexPrime
```

Se preferir transferir o ZIP do projeto, extraia a pasta do projeto para `~/ApexPrime`.

Execute:

```bash
bash android/termux/install.sh
```

## 3. Aplicar migrations

Para instalação limpa, execute 001, 002 e 003 na ordem. Para quem já configurou a edição anterior (como a instalação em andamento), não repita 001–003; execute apenas:

- `supabase/migrations/004_dashboard_individual_actions.sql`
- `supabase/migrations/005_automation_risk_controls.sql`

Essas duas migrations completam os comandos individuais do PWA, a pausa de novas entradas e o limite de perda diária.

Para atualizar o PWA/worker depois de instalado, siga também `docs/FINALIZACAO-PAPER-TRADING.md`.

## 4. Configurar segredos locais

Edite `~/ApexPrime/.env` com `nano .env`:

```bash
nano .env
```

Preencha URL/Service Role do Supabase, Gemini, Groq, Chart IMG e token NOVO do Telegram. O token exposto anteriormente deve ser revogado no BotFather.

Verifique:

```bash
chmod 600 .env
```

Nunca envie `.env` ao GitHub. A chave `SUPABASE_SERVICE_ROLE_KEY` só fica no Termux. O PWA usa apenas a chave `anon` pública, protegida por RLS.

Mantenha exatamente:

```env
PAPER_TRADING_ONLY=true
APEX_REAL_TRADING_ENABLED=false
```

Os campos `BINANCE_FUTURES_API_KEY` e `BINANCE_FUTURES_API_SECRET` ficam vazios e não são usados pelo worker de paper trading.

## 5. Testar Binance e telemetria local

Antes de iniciar o worker, teste se a conexão brasileira do Redmi consegue consultar o endpoint público Futures:

```bash
pkg install -y curl
curl -sS -w '\nHTTP %{http_code}\n' 'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=3'
```

O esperado é HTTP 200 e um array JSON com três candles. **Mudar do GitHub Actions para o Redmi não garante que a Binance aceite a consulta**: a própria disponibilidade de produtos Futures para residentes brasileiros pode estar sujeita a restrições da Binance. Se retornar 451/403, não tente contornar com proxy ou falsificação de localização; pare o scan e escolha uma fonte de mercado autorizada e acessível.

Depois teste a telemetria:

```bash
bash android/termux/health-check.sh
python -m apexprime.main device
```

Se bateria e Wi-Fi aparecerem, confira no Supabase as tabelas `apex_devices`, `device_heartbeats` e `device_events`.

Se Wi-Fi vier vazio, verifique a permissão Localização do Termux:API, ative Localização do Android e teste novamente. O RSSI é normalmente negativo em dBm: por exemplo -45 é forte; -80 é fraco.

## 6. Iniciar o daemon manualmente

```bash
bash scripts/start-apexprime.sh
bash scripts/status-apexprime.sh
```

Logs:

```bash
tail -f runtime/daemon.log
```

Parar:

```bash
bash scripts/stop-apexprime.sh
```

Use `bash scripts/status-apexprime.sh` para ver separadamente o estado do supervisor e do worker.

O supervisor mantém o daemon vivo e o reinicia se o processo Python encerrar. O daemon faz heartbeat a cada 60 s, coleta telemetria a cada 5 min, gerencia trades virtuais a cada 60 s, consulta a fila a cada 30 s e verifica o mercado a cada 15 min. O detector usa candles 1H FECHADOS; a chave única no banco evita reanalisar o mesmo candle em cada varredura.

## 7. Ativar início automático após reiniciar

1. Abra Termux:Boot pelo ícone pelo menos uma vez.
2. No Termux, instale o script:

```bash
bash android/termux/copy-boot-script.sh
```

Esse script de boot inicia um **supervisor**. Se o processo Python encerrar inesperadamente, o supervisor tenta iniciá-lo novamente após 15 segundos. A queda de internet, por si só, não encerra o worker: ele continua vivo e repete as chamadas remotas nos ciclos seguintes.

3. Deixe a pasta do projeto exatamente em `~/ApexPrime`, com `.env` existente.
4. No MIUI 10: Segurança > Permissões > Inicialização automática (o nome pode variar) > permita **Termux** e **Termux:Boot**.
5. Em Configurações > Bateria/Economia de bateria, defina Termux e Termux:Boot como **Sem restrições**. Não use Economia de bateria para esses apps.
6. Abra a tela de apps recentes e, se o MIUI permitir, bloqueie o Termux no cadeado para evitar limpeza automática. Faça o mesmo para Termux:API se o MIUI oferecer essa opção.
7. Em Wi-Fi > Configurações avançadas, selecione manter Wi-Fi ligado durante suspensão / sempre ligado, se essa opção existir.
8. Mantenha o telefone ventilado e evite deixá-lo sob sol ou coberto enquanto carrega.

**Teste obrigatório:** reinicie o Redmi sem abrir Termux manualmente. Aguarde 2–3 minutos e confira no Supabase `apex_devices.last_seen_at` e no Telegram a mensagem APEXPRIME ONLINE. O Termux:Boot usa o mecanismo de boot do Android e o `termux-wake-lock` para evitar suspensão da CPU. O Android pode restringir dados do usuário antes do primeiro desbloqueio em dispositivos com Direct Boot; sem PIN/padrão o comportamento precisa ser validado no aparelho específico, não há garantia universal para todas as ROMs MIUI. Se a MIUI ainda exigir deslizar a tela de bloqueio, o plugin poderá só iniciar depois dessa interação. E, se o telefone estiver totalmente desligado por falta de bateria, alguém precisará pressionar o botão Power: o software não consegue ligar fisicamente o aparelho só porque o carregador voltou a receber energia.

## 8. Publicar o PWA no GitHub Pages

1. Edite `frontend/config.js` (use `config.js.example` como referência).
2. Coloque somente `SUPABASE_URL` e a chave `anon` pública do Supabase. Nunca use service_role.
3. Envie o projeto para a branch `main`.
4. No GitHub, abra Settings > Pages e escolha **GitHub Actions** como Build and deployment source.
5. No Supabase, em Authentication > URL Configuration, adicione a URL pública do GitHub Pages às URLs permitidas, por exemplo `https://SEU_USUARIO.github.io/SEU_REPOSITORIO/`.
6. Execute o workflow `Deploy ApexPrime PWA` na aba Actions, ou faça um push que altere `frontend/**`.
7. Abra a URL publicada no Chrome Android, faça login com o usuário Supabase que já está cadastrado em `apex_admins` e use Menu > Instalar app.

O GitHub Actions agora só publica os arquivos estáticos e roda CI. Ele não consulta Binance nem executa trades.

## 9. Recuperação depois de queda da internet

Não é preciso executar nada manualmente. O daemon continua vivo, falha de forma controlada nas chamadas remotas e tenta novamente no próximo intervalo. Se o processo Python sair por outro motivo, o supervisor local tenta reiniciá-lo após 15 segundos. Quando o Wi-Fi retornar, a próxima tentativa publica heartbeat/telemetria, processa a fila pendente e registra um `OFFLINE_GAP` aproximado.

No MIUI, ative reconexão automática para sua rede Wi-Fi. Não force parada do Termux. O aparelho precisa ter uma conexão de dados ativa com o Supabase para aparecer online no PWA.

## 10. Alertas da bateria

- Abaixo de 40%: o daemon envia um único alerta Telegram e marca `low_battery_alert_active`; o painel PWA mostra um alerta visual.
- Para notificação do navegador, entre no PWA e toque em **Ativar alertas**, autorizando as notificações. O alerta do navegador só pode aparecer quando o PWA/navegador está ativo ou quando o navegador permite a entrega; Telegram continua sendo o canal remoto.
- Ao atingir 45%: rearma o alerta para um próximo ciclo.
- Temperatura enviada é a temperatura reportada pelo sensor da bateria, em °C; não é a temperatura da CPU.

Para alterar os limites, edite `DEVICE_LOW_BATTERY_THRESHOLD` e `DEVICE_BATTERY_REARM_THRESHOLD` no `.env` e reinicie o daemon.

## 11. Binance Futures / Trading real

Esta edição usa apenas endpoints públicos de mercado USDⓈ-M Futures e paper trading. Não envia ordens reais. As variáveis de API privada estão reservadas e vazias; a chave/secret não devem ser criadas nem adicionadas nesta etapa. O caminho real exige revisão legal/etária, autorização da conta, implementação separada, testes e proteções. Não tente contornar resposta 451 nem restrições geográficas.

## Escopo desta tela PWA

Esta edição inclui login de administrador e o painel de saúde do Redmi (bateria, carga, temperatura, Wi-Fi, RSSI, uptime, online/offline e resumo Groq). Os controles completos de trading da especificação inicial — forçar análise, fechar trade, editar prompts, gráfico/histórico com replay, contador Gemini e painel de testes de todos os provedores — ainda não fazem parte desta tela de monitoramento. O worker e as tabelas de trading continuam no projeto; não confunda esta tela com a entrega final de todo o painel operacional.

## Privacidade da telemetria

O Supabase guarda os dados de bateria, Wi-Fi e heartbeat para o painel. O Groq recebe apenas os dados necessários ao resumo de saúde: nome/modelo, bateria, estado de carga, temperatura, SSID, RSSI, velocidade/frequência Wi-Fi e uptime. O IP local e os payloads brutos do Termux não são enviados ao Groq.

## 12. Resolução de problemas

- `termux-battery-status: command not found`: `pkg install termux-api` e instale/abra o app Termux:API da mesma origem.
- `API_ERROR` no Wi-Fi: habilite Localização e a permissão do Termux:API; reinicie o Termux:API.
- Daemon para com a tela apagada: desative economia de bateria para Termux/Boot, use `termux-wake-lock`, mantenha Wi-Fi sempre ligado; confirme `scripts/status-apexprime.sh` e consulte `runtime/daemon.log`.
- Não inicia depois de reiniciar: abra Termux:Boot uma vez, refaça o script de boot e permita autostart no MIUI.
- Supabase sem dados: confira `.env`, execute migration 003 e rode `python -m apexprime.main device` para ver erro no terminal.
- Gemini/Groq indisponíveis: confira chaves, cota do provedor, data/hora do Android e TLS.
