# code-flow

CodeFlow scans a Python project, splits files into semantic chunks, processes each
chunk, and stores results in `db.json`.

## Run

```bash
python refactor.py /path/to/project
python refactor.py /path/to/project --force
```

## What is stored

For each target project, CodeFlow stores:

- `files`: file-level hashes and scan timestamps.
- `chunks`: semantic chunks for each file, including `source`, `hash`, and
	`result`.
- `graph`: dependency graph data with:
	- `by_file`: per-file node/edge contributions.
	- `nodes`: deduplicated project-level nodes.
	- `edges`: deduplicated project-level edges.

## Chunk graph output

`processor.process_chunk` stores graph results in `chunk["result"]["graph"]`.

Graph payload shape:

```json
{
	"project": "code-flow",
	"module": "db",
	"nodes": [
		{"id": "code-flow::module::db", "label": "db", "kind": "module"},
		{"id": "code-flow::db::load_db", "label": "load_db", "kind": "symbol"}
	],
	"edges": [
		{"source": "code-flow::project", "target": "code-flow::module::db", "type": "hierarchy"},
		{"source": "code-flow::module::db", "target": "code-flow::db::load_db", "type": "hierarchy"},
		{"source": "code-flow::db::json", "target": "code-flow::db::load_db", "type": "usage"}
	]
}
```

Supported edge types:

- `import`
- `hierarchy`
- `usage`
- `call`
