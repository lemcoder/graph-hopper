# Knowledge Graph Construction Spec

## Purpose
Extract and store entity relationships.

## Requirements
- Parse content for entities (class, function, module).
- Store relationships (e.g., function calls, imports).
- Minimal graph structure (networkx or custom).

## Success Criteria
- Graph built for each subagent.
- Relationships retrievable for context assembly.
- Graph construction does not block ingestion.
