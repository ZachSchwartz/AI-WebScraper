# Development

How to run the stack, call it, and work on it. See the
[README](README.md) for what it does and how it is built.

## Setup

Clone the repository, then:

```bash
./build.sh --build      # macOS and Linux; chmod +x build.sh first
.\build.bat --build     # Windows
```

The scripts need Docker with Compose v2, which they check for before doing
anything. They start the stack, open <http://localhost:8080>, then wait for a
keypress and tear the containers down. `docker compose up --build` runs the same
stack without them.

The first run installs dependencies and downloads the model, so it is slow.
After that, drop `--build` unless you changed code, since each service image
carries its own source.

## Configuration

The stack runs out of the box on local development defaults. To change the
database or pgAdmin credentials, copy `.env.example` to `.env` and edit it.
Docker Compose picks it up automatically, and `.env` is gitignored, so your
values stay local.

## Resetting the database

```bash
./build.sh --delete_db      # macOS and Linux
.\build.bat --delete_db     # Windows
```

This drops the Postgres volume only. The model cache survives, so the next start
does not download the model again.

The schema is created from the models if the table is not already there, which
means an existing volume keeps whatever it was built with. A database created
before the unique constraint on `(keyword, source_url, href_url)` will not gain
it, so reset once to rebuild.

## Running the tests

The suite runs outside Docker and needs no model download. Every check below
also runs in CI on each push, alongside a build of the producer, database, and
web images. The scorer image is not built there: it pulls in `torch`, and the
tests already cover the scoring logic without it.

```bash
pip install -r requirements-dev.txt
pytest
black --check database scorer producer util web_service tests
pylint --disable=import-error database scorer producer util web_service tests
mypy --ignore-missing-imports database scorer producer util web_service
```

`pytest` reports coverage and fails below 80%, and the thresholds live in
`pytest.ini`. Redis is stubbed in process with `fakeredis` and the database
tests run against SQLite, so no service needs to be up. That also forces the
upsert that stores a link to be built for whichever dialect the engine speaks.
`mypy` runs over the same code, so the type annotations are checked rather than
decoration.

The scorer service imports `torch` and `sentence-transformers` at module level,
which together weigh over a gigabyte. Rather than install them to test scoring,
`tests/conftest.py` substitutes a deterministic stand-in that embeds text as a
hashed bag of words, so cosine similarity still rises with shared vocabulary and
the scoring logic is exercised in full.

## Querying the database directly

pgAdmin runs at <http://localhost:5050>. Sign in with the credentials from your
`.env`, which default to `admin@example.com` and `admin`. Then open scraper,
databases, scraper, schemas, public, tables, `scraped_items`, right click it, and
choose Query Tool.

## API reference

The web service on port 8080 serves everything below. The other services listen
only on the Compose network and are not meant to be called directly.

### POST /api/scrape

Scrape one page, score its links, store them, and return them ranked.

| Field | Required | Description |
| --- | --- | --- |
| `url` | yes | Page to scrape. Must resolve to a public address. |
| `keyword` | yes | Term to rank links against. |

```bash
curl -X POST http://localhost:8080/api/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/docs", "keyword": "authentication"}'
```

Responds `200` with `source_url`, `keyword`, `job_id`, `count`, and `results`, an
array of `{url, score}` sorted by score descending with one entry per distinct
link.

It responds `400 missing_parameter` if either field is absent,
`400 invalid_url` if the URL resolves to a private address or is otherwise
refused, and `500 scraping_failed` if a stage of the pipeline fails.

### GET /db/query

Search stored links. Both parameters are optional. With neither, every stored
row comes back.

| Parameter | Description |
| --- | --- |
| `keyword` | Exact keyword the links were scored against. |
| `source_url` | Page the links were found on. Canonicalized before matching, so it need not match character for character. |

```bash
curl 'http://localhost:8080/db/query?keyword=authentication'
```

Responds `200` with `count` and `items`, ordered by score descending. Each item
carries `id`, `keyword`, `source_url`, `href_url`, `relevance_score`, `job_id`,
`processed_date`, and `raw_data`, which is the full scraped context the score
was computed from.

It responds `500 query_failed` if the query itself fails and `503 query_failed`
if the database service cannot be reached.

### GET /db/query/href

Look up a single link by where it points, to find which scraped page it appeared
on.

| Parameter | Required | Description |
| --- | --- | --- |
| `href_url` | yes | A URL found on a previously scraped page. |

Responds `200` with `href_url`, `source_url`, `keyword`, and `relevance_score`.
It responds `400 query_failed` if the parameter is absent, `404 query_failed` if
no such link is stored, and `503 query_failed` if the database service cannot be
reached.

### GET /health

Each service exposes one. The web service's reports only itself. The scorer's
and the database processor's also check that Redis is reachable. Compose gates
startup on them.

### Errors

Every failure takes one shape:

```json
{ "error": "invalid_url", "message": "...", "status": "error" }
```

The message is written for the caller. Internal failures log their detail and
report a generic message rather than describing this stack to a client.

`/api/scrape` names the failure in `error`. Both query endpoints report
`query_failed` whatever went wrong, because the web service only proxies them,
so there the status code and the message carry the meaning.
