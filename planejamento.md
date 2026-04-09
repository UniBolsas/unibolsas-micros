# Planejamento — Scraper periódico + dashboard mínimo

## 1. Visão geral

Evoluir o `unibolsas-micros` para que o scraper da FUNCAP (e futuros: CAPES, CNPq) rode em intervalos regulares (~6h), persista novidades em MongoDB sem reprocessar conteúdo já visto, e exponha uma rota web simples mostrando últimos resultados, horário da última execução, contagem de novos itens e status.

A solução precisa funcionar de forma sustentável no **Render free tier**, que **suspende a app por inatividade** após ~15 min sem tráfego HTTP — premissa central deste plano.

---

## 2. Diagnóstico do cenário atual

- **Entrypoint** `main.py`: cria `FastAPI`, `MongoClient(MONGO_URI)`, `db = client.get_default_database()`, expõe apenas `/health`.
- **Scraper FUNCAP** (`scrapers/funcap/scraper.py`):
  - `parse_funcap_open_editais(html)` produz `list[Edital]` (sha1 truncado de `pdf_url` como `id`).
  - `run(output_path)` baixa HTML, parseia, baixa cada PDF, extrai `registration_deadline`, e **grava JSON em disco** — não toca no MongoDB.
  - TODO já existente: paralelizar downloads de PDF.
- **Modelo** `shared/models.Edital` (dataclass) já em inglês (`registration_deadline`, etc.).
- **Persistência**: cliente Mongo existe em `main.py`, mas nenhum scraper escreve nele ainda. Não há coleções formalizadas (convenção do CLAUDE.md: uma por instituição).
- **Web**: só `/health`. Sem templates, sem rota de inspeção.
- **Estado entre execuções**: inexistente. Cada `run()` reprocessa tudo, inclusive baixa todos os PDFs.
- **Infra**: Render free + Mongo Atlas em prod; docker-compose só dev.

---

## 3. Análise — agendamento no Render free tier

### Restrição

Render free **suspende web services** após inatividade. Quando dorme:
- Schedulers in-process (APScheduler, `asyncio.create_task` com loop) **param de executar** — o processo não está rodando.
- Render free **não oferece Cron Jobs nem Background Workers** (esses são pagos).
- Ao receber request, há cold start de ~30–60s; o scheduler reinicia mas perde os ticks que ocorreram durante o sono.

Conclusão: **scheduler interno sozinho não é confiável** no free tier. Precisa de algo externo que “acorde” o serviço.

### Alternativas avaliadas

| Opção | Como funciona | Prós | Contras |
|---|---|---|---|
| **A. APScheduler interno puro** | `BackgroundScheduler` no startup do FastAPI roda a cada 6h. | Simples, zero infra extra. | Não roda enquanto a app dorme. Ticks perdidos. |
| **B. Cron externo gratuito** (cron-job.org, GitHub Actions `schedule`, UptimeRobot, EasyCron) bate em `POST /scrape/run` a cada 6h | Cron externo dispara HTTP → acorda Render → app roda scraping síncrono ou em background task → responde. | Gratuito, robusto, ticks garantidos. Reaproveita stack web já existente. | Depende de serviço externo (mas há vários redundantes e gratuitos). Endpoint precisa de token simples para não ser público. |
| **C. Render Cron Job pago** | Job dedicado roda comando. | Isolado da web app. | **Pago**. Fora do escopo. |
| **D. Background worker pago** | Worker separado consumindo fila. | Escala bem. | **Pago** + complexidade. |
| **E. Híbrido**: APScheduler interno + cron externo de backup | Scheduler tenta rodar; cron externo garante o disparo. | Resiliente. | Mais código para pouco ganho real no free tier. |
| **F. GitHub Actions executando o scraper diretamente** (sem passar pela app) e gravando no Atlas | Action roda Python, escreve no Mongo, app só lê. | Independe do Render acordar. Logs no GH. | Duplica config (precisa de `MONGO_URI` no GH secrets); a app não é mais a “fonte de verdade” da execução. |

### Recomendação

**Opção B — cron externo HTTP batendo em endpoint protegido por token**, com GitHub Actions `schedule` como cron preferido (já vem com o repo, sem cadastro extra) e cron-job.org como fallback opcional.

Justificativa: aproveita 100% a stack web já existente, é gratuito, ticks garantidos, complexidade mínima, e mantém a app FastAPI como única fonte de verdade. Se no futuro migrar para plano pago, basta trocar para Render Cron sem mexer no código do scraper.

---

## 4. Estratégia de cache/estado entre execuções

Objetivo: evitar re-baixar PDFs e re-escrever no Mongo quando nada mudou.

**Princípio**: `Edital.id` já é determinístico (sha1 de `pdf_url`). Use-o como `_id` no Mongo para idempotência natural via `update_one(..., upsert=True)`.

**Camadas de cache**:

1. **Cache de listagem (curto-circuito do scraping inteiro)**:
   - Após parsear o HTML em `Edital`s, computar `listing_hash = sha1(sorted(edital.id for edital in editais))`.
   - Guardar `last_listing_hash` em uma coleção `scrape_runs` (ver §5).
   - Se igual ao hash anterior **e** todos os ids já existem no Mongo → marcar run como `unchanged`, não baixar PDFs, não escrever editais. Apenas atualiza `scrape_runs`.

2. **Cache por edital (evita re-download de PDF)**:
   - Antes de baixar o PDF de um `Edital`, fazer `db.funcap.find_one({"_id": edital.id}, {"registration_deadline": 1})`.
   - Se já existe e tem `registration_deadline` preenchido → pular download, reaproveitar dados, marcar como `seen`.
   - Só novos `id`s (ou sem deadline) baixam PDF.

3. **Persistência idempotente**:
   - `update_one({"_id": id}, {"$set": doc, "$setOnInsert": {"first_seen_at": now}}, upsert=True)`.
   - Contar `upserted_count` para reportar “novos inseridos”.

Não é necessário cache em disco local — o próprio Mongo é o estado, e o disco do Render free é efêmero (some no restart).

---

## 5. Mudanças em modelo, banco e serviços

### Coleções

- `funcap` (e futuras `capes`, `cnpq`): documentos de `Edital` com `_id = Edital.id`. Campo extra `first_seen_at`, `last_seen_at`.
- `scrape_runs`: histórico mínimo das execuções. Documento por run:
  ```
  {
    _id: ObjectId,
    institution: "funcap",
    started_at, finished_at,
    status: "ok" | "unchanged" | "error",
    listing_hash,
    total_found, new_inserted, updated, skipped_cached,
    duration_ms,
    error: null | {type, message}
  }
  ```
  Index: `{institution: 1, started_at: -1}`. Opcional TTL para limpar runs antigas.

### Models

- Adicionar em `shared/models.py` um pequeno dataclass `ScrapeRun` (ou só usar dict — preferir dataclass para consistência com `Edital`).

### Camada de serviço

Criar `shared/db.py` (ou `shared/repository.py`):
- `get_db()` — singleton do `MongoClient` (mover de `main.py` para reuso pelos scrapers e jobs).
- `EditaisRepository(institution)` com `get_existing_ids(ids)`, `upsert_many(editais) -> (inserted, updated)`.
- `ScrapeRunsRepository` com `start(institution) -> run_id`, `finish(run_id, **stats)`, `get_last(institution)`, `get_recent(institution, limit)`.

### Refator do scraper FUNCAP

`scrapers/funcap/scraper.py`:
- Extrair `run()` para uma versão `run_and_persist(db) -> ScrapeRunResult` que:
  1. cria run em `scrape_runs`,
  2. busca HTML, parseia editais,
  3. computa `listing_hash`, compara com último,
  4. consulta ids existentes, baixa PDFs apenas dos novos/incompletos (paralelizando com `ThreadPoolExecutor` — fecha o TODO existente),
  5. faz upserts,
  6. finaliza run com estatísticas.
- Manter o `run(output_path)` atual como wrapper opcional (CLI legado) ou removê-lo se não for usado — perguntar antes.

### Endpoints FastAPI

Adicionar em `main.py` (ou `routers/scrape.py` se ficar grande):

- `POST /scrape/funcap/run` — protegido por header `X-Scrape-Token` comparado a `os.environ["SCRAPE_TOKEN"]`. Executa `run_and_persist`. Retorna JSON com stats da run. **Síncrono** por padrão (cron externo aguarda); se exceder tempo do Render (~30s para responder ao keep-alive), mover para `BackgroundTasks` e responder 202.
- `GET /scrape/funcap/status` — retorna a última run de `scrape_runs` (timestamp, status, contagens, erro).
- `GET /scrape/funcap` — página HTML simples (Jinja2 ou HTML inline) listando os últimos N editais (`db.funcap.find().sort("last_seen_at", -1).limit(50)`) + cabeçalho com info da última run.
- Manter `/health` como está.

Para a página HTML, usar `fastapi.responses.HTMLResponse` com template inline (string f-string ou `jinja2` se quiser organizar). **Sem framework de frontend, sem CSS elaborado** — uma tabela e um cabeçalho.

### Variáveis de ambiente novas

- `SCRAPE_TOKEN` — token do endpoint de disparo.
- (já existe) `MONGO_URI`.

Atualizar `.env.example`.

---

## 6. Observabilidade mínima

- **Logs**: `logging.getLogger("unibolsas.scraper")`, nível INFO. Logar início, fim, contagens, erros com stacktrace. Render captura stdout — suficiente.
- **Status persistido**: coleção `scrape_runs` é a fonte de verdade do “o que aconteceu por último”, consultável via `/scrape/funcap/status` e visível na página.
- **Erros**: capturados no `run_and_persist`, gravados na própria run (`status: "error"`, `error: {...}`), não derrubam o endpoint.
- **Métricas simples** na página: última execução, duração, novos, total, status.

Sem Sentry/Prometheus nesta fase — over-engineering para o escopo.

---

## 7. Etapas de implementação (incremental, cada etapa entregável)

1. **Refator de DB**: criar `shared/db.py` com singleton de `MongoClient`. Migrar `main.py` para usá-lo. Sem mudança funcional.
2. **Repositórios**: `EditaisRepository` e `ScrapeRunsRepository` em `shared/`. Adicionar dataclass `ScrapeRun`. Criar índices no startup do FastAPI.
3. **Refator scraper FUNCAP**: nova função `run_and_persist(db)` com cache de listing hash + skip de PDFs já vistos + upsert. Paralelizar downloads (`ThreadPoolExecutor`, ~8 workers). Manter testes existentes funcionando; adicionar testes para a lógica de cache/upsert (mockando o repo).
4. **Endpoint de disparo**: `POST /scrape/funcap/run` com auth por token. Executar síncrono primeiro; medir duração; se >25s, mover para `BackgroundTasks`.
5. **Endpoint de status**: `GET /scrape/funcap/status` (JSON).
6. **Página HTML**: `GET /scrape/funcap` com tabela simples + header de status. Jinja2 ou HTML inline.
7. **Cron externo**: workflow GitHub Actions `.github/workflows/scrape-funcap.yml` com `schedule: cron: "0 */6 * * *"` fazendo `curl -X POST` no endpoint com token vindo de `secrets.SCRAPE_TOKEN`. Documentar no README.
8. **Atualizar `.env.example`** e `CLAUDE.md` com as novas convenções e variáveis.
9. (Opcional) TTL index em `scrape_runs` para 90 dias.

Cada etapa pode virar um commit independente, e cada commit deixa o projeto em estado funcional.

---

## 8. Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| Render dorme e cron externo dispara → cold start + scraping pode estourar timeout HTTP do cron (cron-job.org ~30s; GH Actions tolera muito mais) | Run perdida | Usar GitHub Actions (timeout generoso); ou responder rápido com `BackgroundTasks` e deixar o scraping rodar pós-resposta. |
| Endpoint público de scraping abusado | DoS / custo | Token obrigatório via header; retornar 401 sem ele. |
| Scraping demora >free tier worker time | Timeout / processo morto | Paralelizar PDFs; cache de PDFs já baixados reduz drasticamente runs subsequentes; primeira run pode ser manual. |
| Disco efêmero do Render | Cache em disco some | Estado mora no Mongo, não no FS. JSON em disco do `run()` legado deixa de ser fonte de verdade. |
| Heurística de data falha em PDFs novos | `registration_deadline` nulo | Já existe; manter `registration_deadline_context` para auditoria; logs ajudam a iterar. |
| Duplicação de ids se URL do PDF mudar | Edital “novo” idêntico ao antigo | Aceitável nesta fase; futura melhoria: hash do título normalizado. |
| GitHub Actions schedule pode atrasar até ~15min e ocasionalmente pular | Run atrasada | Aceitável para 6h de janela. Se virar problema, adicionar segundo cron externo redundante. |

---

## 9. Decisão recomendada (resumo)

- **Agendamento**: GitHub Actions `schedule` (cron a cada 6h) chamando `POST /scrape/funcap/run` com token. Sem scheduler interno.
- **Estado/cache**: Mongo é a fonte. `scrape_runs` guarda hash da listagem e estatísticas; `funcap` guarda editais idempotentes via upsert por `_id`. PDFs só são baixados para ids novos/incompletos.
- **Web**: três rotas — `POST /scrape/funcap/run` (disparo), `GET /scrape/funcap/status` (JSON), `GET /scrape/funcap` (HTML simples).
- **Observabilidade**: logs em stdout + coleção `scrape_runs`.
- **Sem infra paga, sem worker, sem fila, sem scheduler interno.**

---

## 10. Pendências para confirmar com o usuário antes de implementar

1. Manter o `run(output_path)` legado (escrita em JSON) ou remover?
2. Tudo bem usar GitHub Actions como cron, ou prefere cron-job.org?
3. Página HTML pode usar Jinja2 (adiciona dependência leve) ou prefere HTML inline em string?
4. Frequência confirmada: 6h?
5. Nome da coleção: `funcap` (lowercase) — confirma?
