# AI-WebScraper

[![CI](https://github.com/ZachSchwartz/AI-WebScraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ZachSchwartz/AI-WebScraper/actions/workflows/ci.yml)

Give it a URL and a keyword. It fetches the page, pulls out every link with the
text around it, scores each link for how well it matches the keyword, and stores
the ranked result so you can query it later.

Three Flask services sit behind a queue. The producer scrapes, the scorer ranks
with a sentence transformer, and the db_processor persists. Redis carries work
between them, PostgreSQL holds the results, and the whole stack comes up with
one command.

**Stack:** Python 3.14, Flask, Redis, PostgreSQL, SQLAlchemy,
sentence-transformers (`all-MiniLM-L6-v2`), Docker Compose, gunicorn

I used a sentence transformer instead of an LLM because ranking a few hundred
links per page is an embedding-similarity problem. MiniLM answers it in
milliseconds on CPU, with no API key and no per-call cost.

The pipeline runs end to end. The relevance formula has a tuning bug I found
while documenting it, and [known limitations](#known-limitations) covers what
it costs and how to fix it.

## Quickstart

Needs Docker with Compose v2.

```bash
./build.sh --build      # macOS and Linux; chmod +x build.sh first
.\build.bat --build     # Windows
```

The script starts the stack, opens <http://localhost:8080>, and tears the
containers down when you press a key. `docker compose up --build` does the
same thing without the script. The first run downloads the model, so it is
slow.

See [DEVELOPMENT.md](DEVELOPMENT.md) for the API reference, configuration,
and tests.

## What it produces

```bash
curl -X POST http://localhost:8080/api/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/docs", "keyword": "authentication"}'
```

```json
{
  "source_url": "https://example.org/docs",
  "keyword": "authentication",
  "job_id": "6f1b2c40-9a2e-4f3d-8f1a-7c5d3e9b0a11",
  "count": 42,
  "results": [
    { "url": "https://example.org/docs/authentication", "score": 0.981 },
    { "url": "https://example.org/docs/api/auth-tokens", "score": 0.974 },
    { "url": "https://example.org/blog/oauth-in-practice", "score": 0.046 },
    { "url": "https://example.org/about", "score": 0.011 }
  ]
}
```

The gap between the second and third result comes from the scoring formula, not
from the data. [How relevance scoring works](#how-relevance-scoring-works)
explains why.

Two more endpoints search what has been stored: `GET /db/query` by keyword or
source page, and `GET /db/query/href` by where a link points. The page at
<http://localhost:8080> runs all three.

## Architecture

```mermaid
flowchart LR
    Browser([Browser])
    Site([Target site])
    PgAdmin([pgAdmin :5050])

    subgraph Services
        Web["web :8080"]
        Producer["producer"]
        Scorer["scorer"]
        DBSvc["db_processor"]
    end

    Redis[("Redis")]
    Postgres[("PostgreSQL")]

    Browser -->|"POST /api/scrape"| Web
    Web -->|"step 1: /scrape"| Producer
    Producer -->|"fetch page, extract links"| Site
    Producer -->|"publish to scraped_items:job_id"| Redis
    Web -->|"step 2: /process with job_id"| Scorer
    Scorer -->|"drain, score, republish"| Redis
    Web -->|"step 3: /process with job_id"| DBSvc
    DBSvc -->|"drain scraped_items_processed:job_id"| Redis
    DBSvc -->|"store rows"| Postgres

    Browser -->|"GET /db/query"| Web
    Web -->|"proxy query"| DBSvc
    PgAdmin -->|"ad hoc SQL"| Postgres
```

The web service holds the browser's request open while it drives all three steps
in order. The numbered calls above happen one after another inside a single
`POST /api/scrape`. See [known limitations](#known-limitations) for what that
costs.

Every scrape gets a `job_id`, and each stage reads and writes queue keys scoped
to it: `scraped_items:<job_id>` and `scraped_items_processed:<job_id>`. Two
scrapes running at once therefore cannot consume each other's links. The keys
carry an expiry that is refreshed on every push, so a job that fails partway
does not leave its items in Redis for good.

### Project layout

```
producer/     fetches a page and extracts each link with the text around it
scorer/       embeds that text and scores the link against the keyword
database/     upserts scored links into PostgreSQL and answers the queries
web_service/  the public API, the one HTML page, and the pipeline orchestration
util/         shared by the services: queue draining, URL safety, health checks
tests/        the pytest suite, which runs outside Docker
```

Each service directory holds its own `Dockerfile`, `requirements.txt`, and
`src/`. Every image is built from the repository root, so a service carries
`util/` alongside its own source rather than mounting it at run time.

## How relevance scoring works

The producer does not hand the scorer a bare URL. It joins the anchor text, the
link's attributes, the page title and description, the readable words of the URL,
the text on either side of the link, and the headings above it into one
`processed_text` that the link is scored on.

Scoring combines three signals, in `scorer/src/scorer_processor.py`:

| Signal | Weight | What it measures |
| --- | --- | --- |
| Exact match | 0.5 | The keyword appears in `processed_text` as a substring |
| Semantic similarity | 0.3 | Cosine similarity between the embedding of the whole text and of the keyword |
| Context | 0.2 | The best of the keyword's context windows, three words either side of each standalone occurrence |

Context takes the strongest window rather than the mean, so a link that uses the
keyword meaningfully once is not diluted by the other places the page mentions
it in passing. A keyword with no standalone occurrence has no windows, and the
link scores on similarity alone. Embeddings are cached in memory and on a Docker
volume, keyed by a hash of the text, so a restart neither re-downloads the model
nor re-encodes text it has already seen.

Two sigmoids shape the result. Each cosine similarity is squashed with
`steepness=8` about zero, which spreads the narrow band that real cosine values
occupy across most of 0 to 1. The weighted sum is then squashed again with
`steepness=10, midpoint=0.6`:

```python
score = 0.5 * exact_match + 0.3 * semantic + 0.2 * context
return sigmoid(score, steepness=10, midpoint=0.6)
```

That midpoint is a mistake. Without an exact match the context term is
structurally zero, so the weighted sum cannot exceed 0.3, well below the 0.6
midpoint. The output is close to bimodal:

| cosine(text, keyword) | no substring match | substring match |
| --- | --- | --- |
| 0.0 | 0.011 | 0.818 |
| 0.3 | 0.037 | 0.973 |
| 0.5 | 0.045 | 0.980 |
| 0.7 | 0.047 | 0.982 |

Semantic similarity separates 0.011 from 0.047 in one tier and 0.973 from 0.982
in the other. It orders links within a tier, but which tier a link lands in is
decided entirely by whether the keyword appears literally. The numbers above
come from evaluating the formula, not from a labeled test set. See
[known limitations](#known-limitations).

## Design notes

### Fetching safety

The scraper fetches whatever URL it is handed, which would otherwise make it a
way to reach the private network the services run on.
`util/url_util.assert_fetchable` resolves each host and refuses anything that is
not a public address, so the Redis and Postgres containers, localhost, and the
cloud metadata endpoint are all out of reach. Redirects are followed one hop at
a time and checked the same way, since a public URL is free to redirect
somewhere private. `robots.txt` is honored before any page is fetched.

### Storage

A link is identified by the keyword, the page it was found on, and where it
points. A unique constraint on those three keeps a rescrape to one row. Storing
a link is an upsert against that constraint rather than a read followed by a
write, so two scrapes of the same page running at once cannot both find no
existing row and both insert.

### Serving

Each service is served by gunicorn rather than the Flask development server, and
each image's `CMD` sets a worker count and timeout for what that service does.
The scorer runs a single worker, because a second would hold its own copy of the
transformer and contend for the same cores. Every timeout is well above
gunicorn's 30 second default, because these requests drain a queue rather than
answer from memory.

### Front end

The one page the stack serves has no build step. Its Bootstrap stylesheet is
vendored rather than pulled from a CDN, so the page cannot change under a
deployment that did not rebuild. Every result on it came from a scraped
third-party document, so it is written into the DOM as text rather than
interpolated into markup, and a link is only clickable if it is `http` or
`https`.

## Known limitations

These are worth knowing before reading the code. Each one notes the shortest
path to a fix.

**The score is close to binary.** The 0.6 midpoint sits above anything the
formula can reach without an exact keyword match, so a relevant page that
phrases the topic differently loses to an irrelevant one that merely contains
the word. The midpoint belongs inside the achievable range. A second bug is
tangled with it: the exact-match test is a substring, so `cat` matches
`concatenate`, while the context windows require a whole word, and the two terms
disagree about what a match is. Retuning without a labeled set would only be
guessing.

**The pipeline is orchestrated synchronously.** `web_service` calls the three
services in sequence and holds the HTTP request open for the whole run
(`PIPELINE_TIMEOUT`, 180s), so the Redis queues decouple the services but not
the request. The fix is a job-status endpoint that returns the `job_id`
immediately and lets the page poll while workers drain the queues on their own
schedule.

**One page per scrape.** `scrape()` reads `targets[0]` and ignores the rest, and
it does not follow the links it finds. There is no crawl depth and no per-domain
rate limiting beyond `robots.txt`.

**There are no migrations.** `ensure_schema` creates the schema from the models
at startup, but `create_all` skips a table that already exists, so changing a
column still means recreating the volume. Alembic would make a schema change
deployable without that.

**`assert_fetchable` cannot survive DNS rebinding.** The guard resolves a
hostname, then hands the URL to `requests`, which resolves it again, so a name
that changes its answer between those two lookups slips past. Closing it means
pinning the validated address into the connection.

**Scoring batches within a link, not across them.** `_get_embeddings` sends the
texts one score needs to the model in a single call, but each link is still
scored on its own. Batching a whole page would mean a queue contract that hands
the processor a batch rather than an item, which all three services share.

**No authentication or rate limiting.** Every endpoint is open to anyone who can
reach the port. That is fine for a local stack and not fine for a deployed one.

## License

Released under the [MIT License](LICENSE).
