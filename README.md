# RepoLens

RepoLens is a static analysis and code intelligence engine for GitHub repositories. It clones codebases, parses Abstract Syntax Trees across Java, Python, and JavaScript, maps how functions and files depend on each other, computes PageRank scores to identify core architectural modules, and provides fast local semantic search.

It also serves as the structural foundation for an automated interview question generation pipeline, exporting method-level call graphs to downstream services.

---

## What It Does

- Multi-Language AST Parsing: Uses Tree-sitter to parse Java, Python, and JavaScript source code into syntax trees. It extracts classes, fields, method signatures, parameter types, and function calls reliably without regex.
- Dependency and Call Graphs: Models file imports and method calls as directed graphs using NetworkX. It runs the Google PageRank algorithm to surface the most critical architectural files and shared utilities in a repository.
- Offline Semantic Search: Embeds symbols and code snippets locally using the all-MiniLM-L6-v2 Sentence-Transformer model and computes vector relevance with NumPy cosine similarity. It runs 100% locally with zero external API calls or fees.
- Incremental SHA-256 Caching: Computes SHA-256 hashes for every file. On subsequent analysis runs, unchanged files are skipped, making re-runs fast.
- Background Job Queue: Analysis runs asynchronously in FastAPI background tasks. The API returns an immediate acknowledgment so the client can poll live progress: PENDING -> CLONING -> PARSING -> INDEXING -> READY.
- Interactive Web Dashboard: Includes a browser interface at http://localhost:8000 with an interactive Vis.js network graph, semantic search bar, and one-click JSON export.

---

## Architecture Flow

1. Client Request: A client submits a repository URL via POST /analyze.
2. Cloning and Hashing: The repository is cloned into a workspace directory. Every source file is hashed with SHA-256 to check if it has changed since the last run.
3. AST Parsing: Tree-sitter parses modified files into syntax trees, extracting class names, method signatures, line ranges, and call invocations.
4. Graph Construction: NetworkX builds the dependency graph between files and methods, calculating PageRank centrality scores.
5. Vector Embedding: Sentence-Transformers converts symbols and code snippets into dense vector embeddings.
6. Storage: All extracted data, graph edges, and vector arrays are stored in SQLite.
7. Query and Export: Clients query the database through REST endpoints for structure, search, or call graph exports.

---

## Getting Started

### Prerequisites

- Python 3.11 or newer
- Git installed and available on your system path

### Local Setup

1. Clone this repository:
    git clone https://github.com/sahadheep/RepoLen.git
    cd RepoLen

2. Create and activate a virtual environment:

On Windows:
    python -m venv venv
    .\venv\Scripts\activate

On Linux or macOS:
    python -m venv venv
    source venv/bin/activate

3. Install dependencies:
    pip install -r requirements.txt

4. Run the server:
    uvicorn app.main:app --reload

Once running, access:
- Web Dashboard: http://localhost:8000
- API Documentation: http://localhost:8000/docs

---

### Running with Docker

    docker compose up --build

---

## API Endpoints

### 1. Trigger Analysis
Starts asynchronous background analysis on a repository.

Endpoint: POST /analyze

Request Body:
{
  "url": "https://github.com/pallets/flask"
}

Response (HTTP 202 Accepted):
{
  "repo_id": 1,
  "url": "https://github.com/pallets/flask",
  "status": "PENDING",
  "files_processed": 0,
  "message": "Analysis started in background. Monitor GET /repos/1/status for live progress."
}

---

### 2. Check Analysis Status
Polls the current processing progress of a repository.

Endpoint: GET /repos/1/status

Response (HTTP 200 OK):
{
  "repo_id": 1,
  "url": "https://github.com/pallets/flask",
  "status": "PARSING",
  "progress": 65,
  "files_processed": 42,
  "error_message": null,
  "message": "Current status: PARSING (65%)"
}

---

### 3. Get Important Files (PageRank)
Returns the top architectural files in the repository ordered by PageRank centrality.

Endpoint: GET /repos/1/important

Response (HTTP 200 OK):
{
  "repo_id": 1,
  "files": [
    { "path": "src/flask/app.py", "score": 0.042189, "rank": 1 },
    { "path": "src/flask/helpers.py", "score": 0.038412, "rank": 2 }
  ]
}

---

### 4. Semantic Code Search
Searches the repository using natural language questions.

Endpoint: POST /repos/1/search

Request Body:
{
  "query": "where are route endpoints and URL rules registered?",
  "top_k": 3
}

Response (HTTP 200 OK):
{
  "repo_id": 1,
  "query": "where are route endpoints and URL rules registered?",
  "results": [
    {
      "file_path": "src/flask/app.py",
      "symbol_name": "add_url_rule",
      "kind": "function",
      "start_line": 402,
      "end_line": 460,
      "score": 0.8124,
      "snippet": "def add_url_rule(self, rule, endpoint=None, view_func=None..."
    }
  ]
}

---

### 5. Export Call Graph (Context Dump)
Exports the full structural model and method-to-method call graph.

Endpoint: GET /repos/1/dump

Response (HTTP 200 OK):
{
  "repo_id": 1,
  "repo_root": "repos/my-org__order-service",
  "files": [
    {
      "path": "src/main/java/com/example/OrderService.java",
      "language": "java",
      "symbols": [
        {
          "id": "com.example.OrderService#processOrder(Long)",
          "kind": "method",
          "name": "processOrder",
          "enclosing_class": "com.example.OrderService",
          "signature": "public Order processOrder(Long orderId)",
          "start_line": 40,
          "end_line": 62,
          "fields": ["private final OrderRepository orderRepo;"],
          "calls": ["com.example.OrderRepository#findById"]
        }
      ],
      "imports": ["com.example.OrderRepository"]
    }
  ],
  "call_graph": [
    {
      "caller": "com.example.OrderController#checkout",
      "callee": "com.example.OrderService#processOrder"
    }
  ]
}

---

## Project Structure

RepoLen/
- app/
  - main.py: FastAPI application and API routes
  - analyzer.py: Analysis pipeline and background task runner
  - parser.py: Tree-sitter AST parser (Java, Python, JS)
  - graph.py: Dependency graph and PageRank calculation
  - embedder.py: Local sentence-transformers vector search
  - database.py: SQLite schema, migrations, and queries
  - models.py: Pydantic models for request and response validation
  - utils.py: Git cloning, file walking, and SHA-256 hashing
- static/
  - index.html: Interactive web dashboard (Vis.js network graph)
- tests/
  - test_parser.py: AST parsing tests across Java, Python, and JS
  - test_graph.py: Dependency graph and PageRank tests
  - test_embedder.py: Vector embedding and similarity tests
  - test_rerun.py: File hash caching and re-run tests
  - test_errors.py: Error handling and edge case tests
- Dockerfile: Docker container setup
- docker-compose.yml: Docker Compose configuration
- requirements.txt: Project dependencies
- README.md

---

## Running Tests

Run the full test suite with pytest:

    pytest tests/ -v

All 54 tests verify AST parsing, graph algorithms, vector embeddings, re-analysis caching, and error handling.

---

## License

This project is licensed under the MIT License.
