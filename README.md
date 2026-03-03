# unibolsas-micros

Microsserviço de web scraping construído com **FastAPI** e **Python 3.13**.

A ideia é que esse serviço seja responsável por coletar dados da web de forma agendada e/ou sob demanda via HTTP. Por enquanto o projeto está no início — a estrutura base já está pronta para o time continuar desenvolvendo.

---

## Tecnologias

- **Python 3.13** — versão da linguagem usada no projeto
- **FastAPI** — framework web para criar as rotas HTTP
- **uv** — gerenciador de pacotes e dependências. Escolhemos o `uv` porque ele baixa as dependências **em paralelo**, o que torna a instalação muito mais rápida do que o `pip` tradicional
- **Docker** — para rodar o serviço em container, garantindo que funciona igual em qualquer máquina

---

## Pré-requisitos

Antes de começar, você precisa ter instalado na sua máquina:

- [mise](https://mise.jdx.dev/) — gerencia as versões do Python e do `uv` automaticamente
- [Docker](https://docs.docker.com/get-docker/) — necessário para rodar via container

---

## Rodando localmente (sem Docker)

### 1. Instale as ferramentas certas com o mise

Na raiz do projeto, rode:

```bash
mise trust
mise install
```

Isso instala automaticamente o Python 3.13 e o `uv` nas versões certas para esse projeto.

### 2. Instale as dependências

```bash
uv sync
```

O `uv` vai criar um ambiente virtual (`.venv`) e instalar tudo que está no `uv.lock`.

### 3. Suba o servidor

```bash
uv run uvicorn main:app --reload
```

O `--reload` faz o servidor reiniciar automaticamente sempre que você salvar um arquivo — muito útil durante o desenvolvimento.

O servidor vai estar disponível em: **http://localhost:8000**

Para verificar se está rodando, acesse: **http://localhost:8000/health**

---

## Rodando com Docker

### 1. Build da imagem

```bash
docker build -t unibolsas-micros .
```

### 2. Sobe o container

```bash
docker run -p 8000:8000 unibolsas-micros
```

O serviço vai estar disponível em: **http://localhost:8000**

---

## Estrutura do projeto

```
unibolsas-micros/
├── main.py          # Ponto de entrada da aplicação — as rotas ficam aqui
├── pyproject.toml   # Dependências e configurações do projeto
├── uv.lock          # Versões exatas das dependências (não edite manualmente)
├── Dockerfile       # Receita para criar a imagem Docker
├── mise.toml        # Versões do Python e uv usadas no projeto
└── .dockerignore    # Arquivos ignorados no build do Docker
```

---

## Endpoints disponíveis

| Método | Rota      | Descrição                        |
|--------|-----------|----------------------------------|
| GET    | `/health` | Verifica se o serviço está vivo  |
