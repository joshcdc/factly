# AGENT.md — Fact-Checking Knowledge Graph

## 1. Project Overview

Build an autonomous fact-checking and knowledge graph application.

Users can either:
- Enter a topic to investigate and automatically construct a knowledge graph.
- Enter a specific claim to investigate, finding supporting and contradicting evidence.

The application uses Linkup for web research, LLMs for information extraction, Jev for structured evaluation where appropriate, and an interactive graph visualisation for presenting results.

### Core functionality

1. Accept a topic or claim.
2. Search the web using Linkup.
3. Retrieve relevant source content.
4. Extract entities, claims, relationships, dates and evidence.
5. Evaluate sources and evidence.
6. Construct a structured graph.
7. Display the graph interactively.
8. Allow users to inspect nodes, relationships and their supporting sources.

### Technology stack

| Component | Technology |
|---|---|
| Frontend | React + TypeScript |
| Backend | Python + FastAPI |
| Research | Linkup Search API |
| Information extraction | Generative LLM |
| Evaluation | Jev + rule-based evaluation |
| Graph visualisation | Existing graph engine, integrated through an adapter |
| Data storage | In-memory / JSON initially |

Do not introduce a database unless necessary.

---

## 2. Team Structure

Each team member owns one workstream.

### Agent 1 — Research & Backend Infrastructure

**Responsibility:** Linkup integration and research pipeline.

Tasks:

- Set up the FastAPI application.
- Implement the Linkup Search API integration.
- Accept topic and claim investigation requests.
- Retrieve search results and source metadata.
- Retrieve full webpage content where appropriate.
- Normalise search results into a consistent source format.
- Implement the API endpoint that coordinates the investigation.
- Handle API errors, timeouts and loading states.
- Pass collected sources to Agent 2's extraction pipeline.

Expected deliverables:

- Working Linkup integration.
- Source retrieval module.
- FastAPI endpoints.
- Normalised source data.
- End-to-end backend orchestration.

Suggested structure:

    backend/
      main.py
      api/
        routes.py
      research/
        linkup.py
        retrieval.py
        normalise.py
      models/
        source.py

**Important:** Do not implement LLM extraction or graph visualisation. Your responsibility ends when research results are ready for processing.

### Agent 2 — Intelligence & Fact-Checking

**Responsibility:** Information extraction and evidence evaluation.

Tasks:

- Implement the LLM integration.
- Extract entities:
  - People
  - Organisations
  - Companies
  - Locations
  - Events
  - Concepts
- Extract claims and factual assertions.
- Identify relationships between entities.
- Identify supporting and contradicting evidence.
- Associate extracted information with its source.
- Implement rule-based source ranking.
- Implement Jev-based source and evidence evaluation.
- Determine claim statuses:
  - Supported
  - Partially supported
  - Contradicted
  - Insufficient evidence
- Generate confidence assessments.
- Return validated structured JSON.

Expected deliverables:

- Extraction module.
- Evaluation module.
- Structured graph data.
- Source-to-evidence attribution.
- Claim assessments.

Suggested structure:

    backend/
      extraction/
        extractor.py
        prompts.py
        schemas.py
      evaluation/
        evaluator.py
        jev.py
        source_ranking.py

**Important:** Do not implement Linkup retrieval or frontend rendering. Accept normalised sources from Agent 1 and return structured graph data.

### Agent 3 — Frontend & Graph Visualisation

**Responsibility:** Entire user interface and graph interaction.

Tasks:

- Set up the React + TypeScript application.
- Build the landing page and investigation input.
- Support topic and claim investigation modes.
- Integrate the existing graph engine.
- Render entities as nodes and relationships as edges.
- Distinguish node types visually.
- Distinguish supporting and contradicting relationships.
- Implement zooming, panning and node dragging.
- Implement node selection.
- Display a detail panel when a node or edge is selected.
- Display source references, excerpts and credibility assessments.
- Display claim status and confidence assessments.
- Integrate with Agent 1's FastAPI endpoints.

Expected deliverables:

- Functional frontend.
- Interactive graph.
- Node and edge detail panels.
- Investigation input.
- Loading and error states.

Suggested structure:

    frontend/
      src/
        components/
          Graph/
          Sidebar/
          InvestigationInput/
          EvidencePanel/
        services/
          api.ts
        types/
          graph.ts

**Important:** Do not build a custom graph physics engine if an existing engine is available. Focus on the presentation and interaction layer.

---

## 3. Shared Data Contract

This is the most important integration requirement.

All three agents MUST agree on the following data structures before implementing their respective components.

### Source

    {
      "id": "source_1",
      "url": "https://example.com/article",
      "title": "Example Article",
      "publisher": "Example Publisher",
      "published_at": "2026-01-01",
      "content": "Retrieved source content",
      "source_type": "news",
      "credibility_score": 4,
      "relevance_score": 5
    }

### Node

    {
      "id": "entity_1",
      "type": "person",
      "label": "Example Person",
      "description": "Description of entity",
      "properties": {},
      "source_ids": ["source_1"]
    }

Supported node types:

- person
- organisation
- company
- location
- event
- concept
- claim
- source

### Edge

    {
      "id": "edge_1",
      "source": "entity_1",
      "target": "entity_2",
      "relationship": "founded",
      "description": "Relationship description",
      "evidence_ids": ["evidence_1"],
      "source_ids": ["source_1"]
    }

### Evidence

    {
      "id": "evidence_1",
      "claim_id": "claim_1",
      "source_id": "source_1",
      "stance": "supports",
      "excerpt": "Relevant quotation from source",
      "reasoning": "Why this excerpt is relevant",
      "strength": 4
    }

Supported stances:

- supports
- contradicts
- neutral

### Claim assessment

    {
      "claim_id": "claim_1",
      "status": "partially_supported",
      "confidence": 0.82,
      "supporting_evidence": ["evidence_1"],
      "contradicting_evidence": ["evidence_2"],
      "explanation": "Assessment explanation"
    }

Supported statuses:

- supported
- partially_supported
- contradicted
- insufficient_evidence

Confidence is a model-assessed indicator, not a calibrated probability of truth.

---

## 4. API Contract

Agent 1 owns the API implementation. Agent 3 integrates with it.

### Investigation endpoint

    POST /api/investigate

Request:

    {
      "query": "Relationship between OpenAI and Microsoft",
      "mode": "topic"
    }

Alternatively:

    {
      "query": "Microsoft controls OpenAI",
      "mode": "claim"
    }

Response:

    {
      "investigation_id": "investigation_1",
      "query": "Relationship between OpenAI and Microsoft",
      "nodes": [],
      "edges": [],
      "sources": [],
      "evidence": [],
      "assessments": []
    }

### Investigation status

    GET /api/investigate/{investigation_id}

This endpoint can be used for polling if research is asynchronous.

The frontend should not assume research completes instantly.

---

## 5. Integration Rules

1. Agree on shared schemas before substantial implementation.
2. Keep module interfaces stable.
3. Do not modify another agent's module without communicating first.
4. Do not create duplicate implementations of shared functionality.
5. Use Git branches for independent work.
6. Commit frequently with descriptive messages.
7. Never commit API keys or secrets.
8. Keep API keys in environment variables.
9. Use mock data when another component is not ready.
10. Prioritise working integration over additional features.

### Git workflow

Use three branches:

- `feature/research`
- `feature/intelligence`
- `feature/frontend`

Integrate into `main` through pull requests or coordinated merges.

Create the shared schemas in `main` first. All three agents should use the same definitions rather than maintaining separate copies.

---

## 6. Two-Day Development Schedule

### Day 1 — Build independently

**First 30–45 minutes**
- Set up repository.
- Agree on data schemas.
- Create shared interfaces.
- Set up development environments.

**Next 3–4 hours**
- Agent 1: Linkup retrieval and FastAPI.
- Agent 2: Extraction and evaluation.
- Agent 3: Frontend and graph visualisation using mock data.

**End of Day 1**
- All three components should work independently.
- Backend should be able to retrieve sources.
- Intelligence pipeline should accept mock sources and produce graph JSON.
- Frontend should render mock graph JSON.

### Day 2 — Integration and polish

**First 2 hours**
- Connect Linkup to extraction.
- Connect extraction to graph construction.
- Connect FastAPI to frontend.
- Fix data contract mismatches.

**Next 2–3 hours**
- Test complete investigations.
- Improve graph layout and readability.
- Improve evidence detail panels.
- Fix errors and edge cases.

**Final 1–2 hours**
- Prepare demonstration.
- Test multiple topics and claims.
- Ensure the application works from a clean start.
- Freeze features and fix remaining bugs.

---

## 7. Priority Order

### P0 — Must work

- Topic and claim input.
- Linkup research.
- Entity and relationship extraction.
- Evidence extraction.
- Graph construction.
- Interactive graph rendering.
- Source attribution.

### P1 — Important

- Claim status classification.
- Supporting and contradicting evidence.
- Source credibility evaluation.
- Confidence assessments.
- Node detail panels.

### P2 — Only if time permits

- Advanced graph filtering.
- Entity expansion.
- Improved graph layouts.
- Timeline visualisation.
- Persistent investigations.
- Graph export.

---

## 8. General Instructions

This is a two-day hackathon project.

Optimise for a working demonstration, not production architecture.

- Avoid unnecessary abstractions.
- Avoid overengineering.
- Avoid excessive agent orchestration.
- Use structured LLM outputs.
- Validate all generated JSON.
- Handle missing and malformed data.
- Keep dependencies minimal.
- Prefer simple implementations that can be integrated quickly.

**The final product must demonstrate a complete journey:**

User submits a claim or topic → Linkup finds sources → AI extracts information → Evidence is evaluated → Graph is constructed → User explores the graph and inspects the evidence.

That end-to-end journey takes priority over every optional feature.