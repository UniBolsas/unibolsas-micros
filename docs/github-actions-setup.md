# Agendamento via GitHub Actions — guia passo a passo

Este projeto usa **GitHub Actions** como cron externo para disparar o scraping em intervalos regulares. Essa abordagem foi escolhida porque o **Render Free Tier** suspende a aplicação quando não há tráfego — um scheduler interno (ex: APScheduler dentro do FastAPI) simplesmente não rodaria enquanto a app estivesse dormindo. O GitHub Actions resolve isso: a cada X horas ele faz uma requisição HTTP para a sua app, o que **acorda** o serviço no Render e dispara o scraping.

O workflow está definido em `.github/workflows/scrape.yml`.

---

## Como funciona (visão geral)

1. O GitHub Actions roda no horário agendado (`cron: "0 */6 * * *"` = a cada 6h UTC).
2. Ele executa um único `curl`: `POST https://SEU-APP.onrender.com/scrape/run` com o header `X-Scrape-Token: <token>`.
3. Essa chamada:
   - Acorda a app no Render (cold start de ~30s na primeira vez).
   - A app valida o token.
   - Se o token bate, ela agenda **todos os scrapers registrados** (FUNCAP, e no futuro CAPES, CNPq…) como _background tasks_ e responde `200 {"status": "scheduled"}` imediatamente.
   - O `curl` termina rápido (não precisa esperar o scraping acabar), e os scrapers continuam rodando em segundo plano até concluir.
4. Resultados vão para o MongoDB; status de cada run vai para a coleção `scrape_runs`; você pode inspecionar em `GET /scrape` (HTML) ou `GET /scrape/status` (JSON).

---

## O que é o "token"?

`SCRAPE_TOKEN` é só um **segredo compartilhado** — uma string qualquer que você inventa (ex: um UUID aleatório). Ele serve como autenticação simples do endpoint `/scrape/run`, para que qualquer pessoa que descubra a URL da sua app **não consiga disparar scrapings aleatoriamente**.

- O **mesmo valor** precisa estar em dois lugares:
  1. Variável de ambiente `SCRAPE_TOKEN` no **Render** (a app lê e compara).
  2. Secret `SCRAPE_TOKEN` no **GitHub** (o workflow envia no header).
- Se os dois baterem, o disparo funciona. Se não, o endpoint retorna `401`.

Para gerar um token bom:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Não basta só o token, preciso de mais alguma coisa?

Quase. Você precisa de **duas** informações configuradas no GitHub:

| Nome | Tipo | Onde configurar no GitHub | Exemplo |
|---|---|---|---|
| `SCRAPE_URL` | Variable (pública) | Settings → Secrets and variables → Actions → **Variables** | `https://unibolsas.onrender.com` |
| `SCRAPE_TOKEN` | **Secret** (privado) | Settings → Secrets and variables → Actions → **Secrets** | `xYz...` (o token gerado) |

A URL do Render **não é sensível** (qualquer um pode ver em DNS), então é uma _variable_ comum. O token **é sensível**, então vira _secret_ e nunca aparece nos logs.

> Alternativa mais simples: se você não se importa de ter a URL do Render no histórico do repo, pode editar `.github/workflows/scrape.yml` e substituir `${{ vars.SCRAPE_URL }}` pela URL literal. Aí só precisa do secret do token.

---

## Setup — passo a passo

### 1. Gere o token

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copie o valor. Você vai usá-lo em dois lugares a seguir.

### 2. Configure o token no Render

1. Abra o dashboard do Render → seu serviço `unibolsas-micros`.
2. Aba **Environment** → **Add Environment Variable**.
3. Nome: `SCRAPE_TOKEN`. Valor: o token que você gerou.
4. Salve. O Render vai fazer redeploy automático.
5. Anote a URL pública do serviço (algo como `https://unibolsas-micros.onrender.com`).

### 3. Configure a variable e o secret no GitHub

1. No repositório → **Settings** → **Secrets and variables** → **Actions**.
2. Aba **Variables** → **New repository variable**:
   - Name: `SCRAPE_URL`
   - Value: a URL do Render (ex: `https://unibolsas-micros.onrender.com`) — **sem barra no final**.
3. Aba **Secrets** → **New repository secret**:
   - Name: `SCRAPE_TOKEN`
   - Value: o mesmo token que você colocou no Render.

### 4. Teste o disparo manual

O workflow tem `workflow_dispatch`, então dá para rodar sem esperar o cron.

1. No repositório → aba **Actions**.
2. Selecione o workflow **scrape** na barra lateral.
3. Clique em **Run workflow** → **Run workflow**.
4. Espere o job rodar (uns 10-30s dependendo do cold start do Render).
5. Verifique:
   - O log do step "Trigger all scrapers" deve mostrar o curl respondendo com `{"status":"scheduled",...}`.
   - Abra `https://SEU-APP.onrender.com/scrape` no navegador — a tabela deve mostrar a última run.
   - Ou abra `https://SEU-APP.onrender.com/scrape/status` para ver o JSON.

### 5. Pronto

A partir daqui o cron roda automaticamente a cada 6h. Você pode mudar o intervalo editando a linha:

```yaml
- cron: "0 */6 * * *"
```

Exemplos:
- `"0 */3 * * *"` — a cada 3h
- `"0 2 * * *"` — uma vez por dia às 02:00 UTC
- `"0 8,20 * * *"` — 08:00 e 20:00 UTC

Nota: `schedule` no GitHub Actions pode atrasar até alguns minutos (às vezes mais em horários de pico). Para 6h de janela isso é irrelevante.

---

## Como adicionar um novo scraper (ex: CAPES)

A ideia do refator é que você **não precisa mexer no workflow** nem nas rotas quando adiciona um scraper novo.

1. Implemente `scrapers/capes/scraper.py` com uma função `run_and_persist()` que persiste no Mongo usando os repositórios de `shared/db.py` (siga o padrão do FUNCAP).
2. Registre em `scrapers/registry.py`:
   ```python
   from scrapers.capes.scraper import run_and_persist as capes_run

   SCRAPERS = {
       "funcap": funcap_run,
       "capes": capes_run,
   }
   ```
3. Faça deploy. Pronto — `POST /scrape/run` passa a disparar FUNCAP + CAPES, `/scrape` mostra as duas, e o cron do GitHub já cobre as duas sem mudança.

---

## Endpoints disponíveis

| Método | Rota | Protegido? | O que faz |
|---|---|---|---|
| GET  | `/health` | não | Status geral + lista de scrapers registrados |
| POST | `/scrape/run` | sim (token) | Dispara **todos** os scrapers em background |
| POST | `/scrape/run/{institution}` | sim (token) | Dispara apenas um scraper |
| GET  | `/scrape/status` | não | JSON com a última run de cada instituição |
| GET  | `/scrape/status/{institution}` | não | JSON da última run de uma instituição |
| GET  | `/scrape` | não | Página HTML com tabelas de todas as instituições |

---

## Solução de problemas

- **`401 invalid or missing token`**: os valores de `SCRAPE_TOKEN` no Render e no GitHub não batem. Gere de novo e reaplique nos dois lados.
- **`curl: (28) Operation timed out`**: cold start do Render passou de 60s. Aumente `--max-time` no workflow ou mantenha o serviço aquecido com um ping a mais.
- **Cron não dispara**: workflows agendados no GitHub Actions são pausados se o repo ficar 60 dias sem atividade. Qualquer push reativa.
- **Quero ver os logs do scraping**: `GET /scrape/status` mostra status/erro da última run por instituição. Logs detalhados estão no stdout do Render (aba Logs).
