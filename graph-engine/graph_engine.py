#!/usr/bin/env python3
"""Vault graph engine - single-file extraction from dgx-dashboard.

Everything the graph needs lives in this one file: the Markdown vault parser
(wikilinks + markdown links -> folder-collapsed node graph) and the vanilla-JS
force-directed renderer, served by the Python standard library. No third-party
dependencies, no build step, no CDN.

Ported from:
    dgx-dashboard/core/vault/graph.py          (builder)
    dgx-dashboard/core/ui/static/vault-graph.js (renderer)

Differences from the dashboard copy:
  * max_nodes defaults to 0 = full graph (dashboard silently sampled the first
    180 sorted files). When a cap IS set, notes are ranked by link degree
    instead of filesystem order, so the important notes survive truncation.
  * The renderer is a factory (window.createVaultGraph) driven by a config
    object, so it can be pointed at any endpoint or fed inline data.
  * Adds --json (dump graph) and --html (write a standalone offline page).

Usage:
    python graph_engine.py                        # serve on 127.0.0.1:8014
    python graph_engine.py --port 9000 --no-open
    python graph_engine.py --max-nodes 200        # degree-ranked subset
    python graph_engine.py --json graph.json      # dump only
    python graph_engine.py --json                 # dump to stdout
    python graph_engine.py --html vault.html      # self-contained page

    GRAPH_VAULT_PATH=/path/to/vault python graph_engine.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# Vault parser
# --------------------------------------------------------------------------

WIKILINK_RE = re.compile(r"!\[\[[^\]]+\]\]|\[\[([^\]#|]+)(?:[#|][^\]]*)?\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")


def build_vault_graph(vault_path, max_nodes=0):
    """Return {"nodes", "links", "message", "meta"} for a Markdown vault."""
    root = Path(vault_path).expanduser()
    if not root.exists():
        return {
            "nodes": [],
            "links": [],
            "message": "Vault folder not found: %s" % root,
            "meta": {"vault": str(root), "files_on_disk": 0, "notes_total": 0,
                     "notes_shown": 0, "truncated": False, "max_nodes": max_nodes},
        }

    files = sorted(root.rglob("*.md"))
    if not files:
        return {
            "nodes": [],
            "links": [],
            "message": "No markdown files found in %s" % root,
            "meta": {"vault": str(root), "files_on_disk": 0, "notes_total": 0,
                     "notes_shown": 0, "truncated": False, "max_nodes": max_nodes},
        }

    known_notes = {_note_id(path, root): path for path in files}
    note_ids = {note_id for note_id in known_notes if not _is_folder_index_note(note_id)}

    # Pass 1: resolve every link across the whole vault.
    raw_edges = set()
    for note_id in note_ids:
        content = _read_text(known_notes[note_id])
        if content is None:
            continue
        for target in _extract_targets(content):
            resolved = _resolve_target(target, known_notes[note_id].parent, root, known_notes)
            if not resolved:
                continue
            graph_target = _index_note_folder_id(resolved) or resolved
            if graph_target != note_id:
                raw_edges.add((note_id, graph_target))

    # Pass 2: pick the node set. Cap by link degree, not by sort order.
    degree = Counter()
    for source, target in raw_edges:
        degree[source] += 1
        degree[target] += 1

    truncated = False
    if max_nodes and len(note_ids) > max_nodes:
        ranked = sorted(note_ids, key=lambda note_id: (-degree[note_id], note_id))
        selected_ids = set(ranked[:max_nodes])
        truncated = True
    else:
        selected_ids = set(note_ids)

    folder_ids = _folder_ids(selected_ids)

    links = {
        (source, target)
        for source, target in raw_edges
        if source in selected_ids and (target in selected_ids or target in folder_ids)
    }
    for note_id in selected_ids:
        folder_id = _folder_id(Path(note_id).parent)
        if folder_id:
            links.add((folder_id, note_id))
    for folder_id in folder_ids:
        parent_id = _parent_folder_id(folder_id)
        if parent_id in folder_ids:
            links.add((parent_id, folder_id))

    label_counts = _label_counts(selected_ids)
    note_nodes = [
        {
            "id": note_id,
            "label": _node_label(note_id, label_counts),
            "group": _top_level_group(note_id),
            "level": _folder_depth(note_id),
            "kind": "note",
        }
        for note_id in sorted(selected_ids)
    ]
    folder_nodes = [
        {
            "id": folder_id,
            "label": _folder_label(folder_id),
            "group": _folder_group(folder_id),
            "level": _folder_level(folder_id),
            "kind": "folder",
        }
        for folder_id in sorted(folder_ids)
    ]

    return {
        "nodes": note_nodes + folder_nodes,
        "links": [{"source": source, "target": target} for source, target in sorted(links)],
        "message": None if links else "Vault loaded, but no graph links were found.",
        "meta": {
            "vault": str(root),
            "files_on_disk": len(files),
            "notes_total": len(note_ids),
            "notes_shown": len(selected_ids),
            "truncated": truncated,
            "max_nodes": max_nodes,
        },
    }


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    except OSError:
        return None


def _extract_targets(content):
    wikilinks = [match.group(1).strip() for match in WIKILINK_RE.finditer(content) if match.group(1)]
    markdown_links = [
        match.group(1).strip()
        for match in MARKDOWN_LINK_RE.finditer(content)
        if match.group(1).strip().endswith(".md")
    ]
    return wikilinks + markdown_links


def _resolve_target(target, source_dir, vault_path, known_notes):
    cleaned = target.replace("\\", "/").removesuffix(".md")
    direct = "%s.md" % cleaned
    if direct in known_notes:
        return direct

    relative_path = (source_dir / ("%s.md" % cleaned)).resolve()
    try:
        return _note_id(relative_path, vault_path)
    except ValueError:
        pass

    matches = [
        note_id
        for note_id in known_notes
        if Path(note_id).stem == cleaned or note_id.endswith("/%s.md" % cleaned)
    ]
    return matches[0] if len(matches) == 1 else None


def _note_id(path, vault_path):
    return path.resolve().relative_to(vault_path.resolve()).as_posix()


def _top_level_group(note_id):
    parts = note_id.split("/")
    return parts[0] if len(parts) > 1 else "root"


def _folder_depth(note_id):
    return max(0, len(note_id.split("/")) - 1)


def _folder_ids(note_ids):
    folder_ids = set()
    for note_id in note_ids:
        folder_id = _folder_id(Path(note_id).parent)
        while folder_id:
            folder_ids.add(folder_id)
            parent_id = _parent_folder_id(folder_id)
            if not parent_id:
                break
            folder_id = parent_id
    return folder_ids


def _folder_id(path):
    if path == Path("."):
        return None
    return "folder:%s" % path.as_posix()


def _parent_folder_id(folder_id):
    return _folder_id(_folder_path(folder_id).parent)


def _folder_path(folder_id):
    return Path(folder_id.removeprefix("folder:"))


def _folder_label(folder_id):
    return _folder_path(folder_id).name


def _folder_group(folder_id):
    return _folder_path(folder_id).parts[0]


def _folder_level(folder_id):
    return len(_folder_path(folder_id).parts) - 1


def _is_folder_index_note(note_id):
    return _index_note_folder_id(note_id) is not None


def _index_note_folder_id(note_id):
    path = Path(note_id)
    if path.parent == Path("."):
        return None
    if path.stem != path.parent.name:
        return None
    return _folder_id(path.parent)


def _label_counts(note_ids):
    counts = {}
    for note_id in note_ids:
        label = Path(note_id).stem
        counts[label] = counts.get(label, 0) + 1
    return counts


def _node_label(note_id, label_counts):
    stem = Path(note_id).stem
    if label_counts.get(stem, 0) == 1:
        return stem
    return note_id.removesuffix(".md")


# --------------------------------------------------------------------------
# Page (HTML + CSS + renderer, all inline)
# --------------------------------------------------------------------------

PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vault Graph - %%VAULT_PATH%%</title>
<style>
:root {
  color-scheme: dark;
  --bg: #0e1116;
  --panel: #171b22;
  --text: #f2f5f8;
  --muted: #9aa7b3;
  --line: #303844;
  --accent: #57c7b6;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.topbar {
  align-items: center;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  gap: 16px;
  min-height: 76px;
  padding: 14px 24px;
}
.topbar h1 { font-size: 20px; margin: 0; }
.vault-path {
  color: var(--muted);
  font-size: 13px;
  margin: 6px 0 0;
  overflow-wrap: anywhere;
}
.graph-stats { display: flex; gap: 10px; }
.graph-stats span {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  padding: 7px 10px;
  text-transform: uppercase;
  white-space: nowrap;
}
.graph-stage {
  background:
    linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px),
    var(--bg);
  background-size: 28px 28px;
  flex: 1;
  min-height: 0;
  position: relative;
}
#vault-graph {
  display: block;
  height: 100%;
  min-height: 460px;
  width: 100%;
}
.graph-links line {
  stroke: rgba(154, 167, 179, 0.28);
  stroke-width: 1.2;
}
.graph-nodes circle {
  fill: var(--accent);
  cursor: grab;
  stroke: rgba(242, 245, 248, 0.7);
  stroke-width: 1.5;
  touch-action: none;
}
.graph-nodes circle.is-dragging {
  cursor: grabbing;
  stroke: #ffffff;
  stroke-width: 2.5;
}
.graph-nodes circle[data-kind="note"][data-level="0"] { fill: #8fc5ff; }
.graph-nodes circle[data-kind="note"][data-level="1"] { fill: #f2bd5b; }
.graph-nodes circle[data-kind="note"][data-level="2"] { fill: #8fc5ff; }
.graph-nodes circle[data-kind="note"][data-level="3"] { fill: #c084fc; }
.graph-nodes circle[data-kind="note"][data-level="4"] { fill: #fb7185; }
.graph-nodes circle[data-kind="folder"] {
  fill: var(--accent);
  stroke: #ffffff;
  stroke-width: 2.2;
}
.graph-empty {
  color: var(--muted);
  left: 50%;
  max-width: 520px;
  position: absolute;
  text-align: center;
  top: 50%;
  transform: translate(-50%, -50%);
}
@media (max-width: 620px) {
  .topbar { align-items: start; flex-direction: column; }
  #vault-graph { min-height: 520px; }
}
</style>
</head>
<body>
<header class="topbar">
  <div>
    <h1>Vault Graph</h1>
    <p class="vault-path">%%VAULT_PATH%%</p>
  </div>
  <div class="graph-stats">
    <span id="stat-nodes">0 notes</span>
    <span id="stat-links">0 links</span>
  </div>
</header>
<main class="graph-stage">
  <svg id="vault-graph" role="img" aria-label="Vault note connection graph"></svg>
  <div class="graph-empty" id="graph-empty">Loading vault graph...</div>
</main>
<script>window.__GRAPH_CONFIG__ = %%GRAPH_CONFIG%%;</script>
<script>
(function () {
  "use strict";

  var FRAME_MS = 1000 / 60;
  var MAX_FRAME_DELTA_MS = 50;
  var MAX_SUBSTEPS = 3;
  var NODE_PADDING = 24;
  var SETTLED_ALPHA = 0.005;
  var SETTLED_SPEED = 0.02;
  var SETTLED_FRAMES = 18;
  var GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
  var DEFAULT_GRAPH_SETTINGS = Object.freeze({
    springStrength: 0.03,
    springLength: 100,
    maxSpringLength: 300,
    repulsionStrength: 640,
    repulsionLength: 250,
    maxSpeed: 100
  });

  function createVaultGraph(config) {
    config = config || {};
    var svg = document.getElementById(config.svgId || "vault-graph");
    var empty = document.getElementById(config.emptyId || "graph-empty");
    if (!svg) { return null; }

    var statNodes = document.querySelector(config.statNodes || "#stat-nodes");
    var statLinks = document.querySelector(config.statLinks || "#stat-links");
    var endpoint = config.endpoint || "/graph.json";
    var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    var simulation = null;
    var resizeObserver = null;

    async function loadGraph() {
      try {
        var graph = config.data ? config.data : await fetchGraph();
        setGraphStats(graph);
        if (!graph.nodes.length) {
          destroySimulation();
          showEmpty(graph.message || "No vault notes found.");
          return;
        }
        hideEmpty();
        createSimulation(graph);
      } catch (error) {
        destroySimulation();
        showEmpty("Could not load vault graph.");
      }
    }

    async function fetchGraph() {
      var response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Graph request failed with " + response.status);
      }
      return response.json();
    }

    function createSimulation(graph) {
      destroySimulation();
      var size = measureGraph();
      var width = size.width;
      var height = size.height;
      var nodeData = graph.nodes.map(function (node) { return Object.assign({}, node); });
      var clusterCenters = buildClusterCenters(nodeData, width, height);
      var groupIndexes = new Map();
      var nodes = nodeData.map(function (node) {
        var groupIndex = groupIndexes.get(node.group) || 0;
        groupIndexes.set(node.group, groupIndex + 1);
        var cluster = clusterCenters.get(node.group) || { x: width / 2, y: height / 2 };
        var angle = groupIndex * GOLDEN_ANGLE + stableAngle(node.id);
        var radius = 14 + Math.sqrt(groupIndex + 1) * 12;
        return Object.assign({}, node, {
          x: clamp(cluster.x + Math.cos(angle) * radius, NODE_PADDING, width - NODE_PADDING),
          y: clamp(cluster.y + Math.sin(angle) * radius, NODE_PADDING, height - NODE_PADDING),
          vx: 0,
          vy: 0,
          fx: null,
          fy: null,
          element: null
        });
      });
      var byId = new Map(nodes.map(function (node) { return [node.id, node]; }));
      var links = graph.links.map(function (link) {
        return { source: byId.get(link.source), target: byId.get(link.target), element: null };
      }).filter(function (link) { return link.source && link.target; });

      simulation = {
        nodes: nodes,
        links: links,
        byElement: new Map(),
        clusterCenters: clusterCenters,
        settings: DEFAULT_GRAPH_SETTINGS,
        width: width,
        height: height,
        alpha: 1,
        accumulator: 0,
        lastFrameTime: null,
        frameId: null,
        settledFrames: 0,
        dragging: null
      };

      buildGraphElements();
      renderGraph();

      if (reducedMotion.matches) {
        settleImmediately();
      } else {
        startSimulation(1);
      }
    }

    function destroySimulation() {
      if (simulation && simulation.frameId !== null) {
        window.cancelAnimationFrame(simulation.frameId);
      }
      simulation = null;
      svg.innerHTML = "";
    }

    function buildGraphElements() {
      svg.setAttribute("viewBox", "0 0 " + simulation.width + " " + simulation.height);
      svg.innerHTML = "";

      var linkGroup = createSvg("g", { "class": "graph-links" });
      var nodeGroup = createSvg("g", { "class": "graph-nodes" });
      svg.append(linkGroup, nodeGroup);

      simulation.links.forEach(function (link) {
        link.element = createSvg("line", {
          "data-source": link.source.id,
          "data-target": link.target.id
        });
        linkGroup.append(link.element);
      });

      simulation.nodes.forEach(function (node) {
        node.element = createSvg("circle", {
          cx: 0,
          cy: 0,
          r: 6,
          "data-group": node.group,
          "data-kind": node.kind || "note",
          "data-level": node.level
        });
        var title = createSvg("title", {});
        title.textContent = node.label;
        node.element.append(title);
        nodeGroup.append(node.element);
        simulation.byElement.set(node.element, node);
      });
    }

    function startSimulation(alpha, allowReducedMotion) {
      if (!simulation) { return; }
      simulation.alpha = Math.max(simulation.alpha, alpha === undefined ? 0.45 : alpha);
      simulation.settledFrames = 0;
      var motionSuppressed = reducedMotion.matches && !simulation.dragging && !allowReducedMotion;
      if (document.hidden || motionSuppressed || simulation.frameId !== null) { return; }
      simulation.lastFrameTime = null;
      simulation.frameId = window.requestAnimationFrame(animateGraph);
    }

    function animateGraph(timestamp) {
      if (!simulation) { return; }
      simulation.frameId = null;
      var previousTime = simulation.lastFrameTime === null ? timestamp - FRAME_MS : simulation.lastFrameTime;
      var elapsed = Math.min(Math.max(timestamp - previousTime, 0), MAX_FRAME_DELTA_MS);
      simulation.lastFrameTime = timestamp;
      simulation.accumulator += elapsed;

      var substeps = 0;
      var maxVelocity = 0;
      while (simulation.accumulator >= FRAME_MS && substeps < MAX_SUBSTEPS) {
        maxVelocity = stepSimulation();
        simulation.accumulator -= FRAME_MS;
        substeps += 1;
      }
      if (substeps === MAX_SUBSTEPS) { simulation.accumulator = 0; }

      renderGraph();

      var settled = !simulation.dragging && maxVelocity <= SETTLED_SPEED;
      simulation.settledFrames = settled ? simulation.settledFrames + 1 : 0;

      if (simulation.settledFrames < SETTLED_FRAMES || simulation.dragging) {
        simulation.frameId = window.requestAnimationFrame(animateGraph);
      } else {
        simulation.alpha = 0;
        simulation.accumulator = 0;
        simulation.lastFrameTime = null;
      }
    }

    function stepSimulation() {
      var nodes = simulation.nodes;
      var links = simulation.links;
      var settings = simulation.settings;
      var alpha = simulation.dragging ? Math.max(simulation.alpha, 0.22) : simulation.alpha;

      applyRepulsion(nodes, settings, alpha);
      applyLinkSprings(links, settings, alpha);
      applyAttraction(nodes, alpha);

      var maxVelocity = 0;
      nodes.forEach(function (node) {
        if (node.fx !== null && node.fy !== null) {
          node.x = node.fx;
          node.y = node.fy;
          node.vx = 0;
          node.vy = 0;
          return;
        }
        node.vx *= 0.82;
        node.vy *= 0.82;
        limitVelocity(node, settings.maxSpeed);
        node.x += node.vx;
        node.y += node.vy;
        containNode(node);
        maxVelocity = Math.max(maxVelocity, Math.hypot(node.vx, node.vy));
      });
      maxVelocity = Math.max(maxVelocity, enforceMaxSpringLengths(links, settings));

      if (!simulation.dragging) { simulation.alpha *= 0.965; }
      return maxVelocity;
    }

    function applyRepulsion(nodes, settings, alpha) {
      var cutoff = Math.max(settings.repulsionLength, 1);
      var cutoffSq = cutoff * cutoff;
      var grid = new Map();

      nodes.forEach(function (node, index) {
        var cellX = Math.floor(node.x / cutoff);
        var cellY = Math.floor(node.y / cutoff);
        var key = cellX + "," + cellY;
        var bucket = grid.get(key);
        if (bucket) { bucket.push(index); } else { grid.set(key, [index]); }
      });

      nodes.forEach(function (a, index) {
        var cellX = Math.floor(a.x / cutoff);
        var cellY = Math.floor(a.y / cutoff);
        for (var offsetX = -1; offsetX <= 1; offsetX += 1) {
          for (var offsetY = -1; offsetY <= 1; offsetY += 1) {
            var bucket = grid.get((cellX + offsetX) + "," + (cellY + offsetY));
            if (!bucket) { continue; }
            bucket.forEach(function (otherIndex) {
              if (otherIndex <= index) { return; }
              var b = nodes[otherIndex];
              var dx = a.x - b.x;
              var dy = a.y - b.y;
              var distanceSq = dx * dx + dy * dy;
              if (distanceSq >= cutoffSq) { return; }
              if (distanceSq < 0.01) {
                var angle = stableAngle(a.id + ":" + b.id);
                dx = Math.cos(angle) * 0.1;
                dy = Math.sin(angle) * 0.1;
                distanceSq = 0.01;
              }
              var distance = Math.sqrt(distanceSq);
              var falloff = 1 - distance / cutoff;
              var force = (settings.repulsionStrength / Math.max(distanceSq, 64)) * falloff * alpha * 0.08;
              var forceX = dx * force;
              var forceY = dy * force;
              if (a.fx === null) { a.vx += forceX; a.vy += forceY; }
              if (b.fx === null) { b.vx -= forceX; b.vy -= forceY; }
            });
          }
        }
      });
    }

    function applyLinkSprings(links, settings, alpha) {
      var maxSpringLength = Math.max(settings.springLength, settings.maxSpringLength);
      links.forEach(function (link) {
        var dx = link.target.x - link.source.x;
        var dy = link.target.y - link.source.y;
        var distance = Math.hypot(dx, dy) || 1;
        var excessLength = Math.max(0, distance - maxSpringLength);
        var springForce = (distance - settings.springLength) * settings.springStrength * alpha * 0.35;
        var tautForce = excessLength * settings.springStrength * alpha * 1.4;
        var force = springForce + tautForce;
        var forceX = (dx / distance) * force;
        var forceY = (dy / distance) * force;
        if (link.source.fx === null) { link.source.vx += forceX; link.source.vy += forceY; }
        if (link.target.fx === null) { link.target.vx -= forceX; link.target.vy -= forceY; }
      });
    }

    function enforceMaxSpringLengths(links, settings) {
      var maxSpringLength = Math.max(settings.springLength, settings.maxSpringLength);
      var maxCorrection = 0;
      links.forEach(function (link) {
        var dx = link.target.x - link.source.x;
        var dy = link.target.y - link.source.y;
        var distance = Math.hypot(dx, dy) || 1;
        var excessLength = distance - maxSpringLength;
        if (excessLength <= 0 || (link.source.fx !== null && link.target.fx !== null)) { return; }
        var unitX = dx / distance;
        var unitY = dy / distance;
        var sourceShare = link.source.fx === null ? (link.target.fx === null ? 0.5 : 1) : 0;
        var targetShare = link.target.fx === null ? (link.source.fx === null ? 0.5 : 1) : 0;
        link.source.x += unitX * excessLength * sourceShare;
        link.source.y += unitY * excessLength * sourceShare;
        link.target.x -= unitX * excessLength * targetShare;
        link.target.y -= unitY * excessLength * targetShare;
        maxCorrection = Math.max(maxCorrection, excessLength);
      });
      return maxCorrection;
    }

    function applyAttraction(nodes, alpha) {
      nodes.forEach(function (node) {
        if (node.fx !== null) { return; }
        var cluster = simulation.clusterCenters.get(node.group) || { x: simulation.width / 2, y: simulation.height / 2 };
        node.vx += (cluster.x - node.x) * 0.00045 * alpha;
        node.vy += (cluster.y - node.y) * 0.00045 * alpha;
        node.vx += (simulation.width / 2 - node.x) * 0.00012 * alpha;
        node.vy += (simulation.height / 2 - node.y) * 0.00012 * alpha;
      });
    }

    function containNode(node) {
      var maxX = Math.max(NODE_PADDING, simulation.width - NODE_PADDING);
      var maxY = Math.max(NODE_PADDING, simulation.height - NODE_PADDING);
      if (node.x < NODE_PADDING || node.x > maxX) {
        node.x = clamp(node.x, NODE_PADDING, maxX);
        node.vx *= -0.2;
      }
      if (node.y < NODE_PADDING || node.y > maxY) {
        node.y = clamp(node.y, NODE_PADDING, maxY);
        node.vy *= -0.2;
      }
    }

    function renderGraph() {
      if (!simulation) { return; }
      simulation.nodes.forEach(function (node) {
        node.element.setAttribute("transform", "translate(" + node.x.toFixed(2) + " " + node.y.toFixed(2) + ")");
      });
      simulation.links.forEach(function (link) {
        link.element.setAttribute("x1", link.source.x.toFixed(2));
        link.element.setAttribute("y1", link.source.y.toFixed(2));
        link.element.setAttribute("x2", link.target.x.toFixed(2));
        link.element.setAttribute("y2", link.target.y.toFixed(2));
      });
    }

    function settleImmediately() {
      if (!simulation) { return; }
      if (simulation.frameId !== null) {
        window.cancelAnimationFrame(simulation.frameId);
        simulation.frameId = null;
      }
      simulation.alpha = Math.max(simulation.alpha, 0.7);
      for (var tick = 0; tick < 140; tick += 1) { stepSimulation(); }
      simulation.alpha = 0;
      simulation.accumulator = 0;
      simulation.lastFrameTime = null;
      renderGraph();
    }

    function bindGraphInteraction() {
      svg.addEventListener("pointerdown", function (event) {
        if (!simulation) { return; }
        var node = simulation.byElement.get(event.target);
        if (!node) { return; }
        var point = svgPoint(svg, event);
        node.fx = clamp(point.x, NODE_PADDING, simulation.width - NODE_PADDING);
        node.fy = clamp(point.y, NODE_PADDING, simulation.height - NODE_PADDING);
        node.x = node.fx;
        node.y = node.fy;
        node.vx = 0;
        node.vy = 0;
        simulation.dragging = { node: node, pointerId: event.pointerId };
        node.element.setPointerCapture(event.pointerId);
        node.element.classList.add("is-dragging");
        startSimulation(0.55);
        event.preventDefault();
      });

      svg.addEventListener("pointermove", function (event) {
        if (!simulation || !simulation.dragging || simulation.dragging.pointerId !== event.pointerId) { return; }
        var node = simulation.dragging.node;
        var point = svgPoint(svg, event);
        node.fx = clamp(point.x, NODE_PADDING, simulation.width - NODE_PADDING);
        node.fy = clamp(point.y, NODE_PADDING, simulation.height - NODE_PADDING);
        node.x = node.fx;
        node.y = node.fy;
        startSimulation(0.35);
        event.preventDefault();
      });

      svg.addEventListener("pointerup", stopDragging);
      svg.addEventListener("pointercancel", stopDragging);
      svg.addEventListener("lostpointercapture", stopDragging);
    }

    function stopDragging(event) {
      if (!simulation || !simulation.dragging || simulation.dragging.pointerId !== event.pointerId) { return; }
      var node = simulation.dragging.node;
      var pointerId = simulation.dragging.pointerId;
      simulation.dragging = null;
      node.fx = null;
      node.fy = null;
      node.element.classList.remove("is-dragging");
      if (node.element.hasPointerCapture(pointerId)) {
        node.element.releasePointerCapture(pointerId);
      }
      startSimulation(0.65, true);
    }

    function bindGraphLifecycle() {
      resizeObserver = new ResizeObserver(function () { resizeGraph(); });
      resizeObserver.observe(svg);

      document.addEventListener("visibilitychange", function () {
        if (!simulation) { return; }
        if (document.hidden) {
          if (simulation.frameId !== null) {
            window.cancelAnimationFrame(simulation.frameId);
            simulation.frameId = null;
          }
          simulation.lastFrameTime = null;
          simulation.accumulator = 0;
        } else if (simulation.alpha > SETTLED_ALPHA || simulation.dragging) {
          startSimulation(simulation.alpha);
        }
      });

      reducedMotion.addEventListener("change", function () {
        if (!simulation) { return; }
        if (reducedMotion.matches) { settleImmediately(); } else { startSimulation(0.45); }
      });
    }

    function resizeGraph() {
      if (!simulation) { return; }
      var size = measureGraph();
      if (Math.abs(size.width - simulation.width) < 1 && Math.abs(size.height - simulation.height) < 1) { return; }
      var scaleX = size.width / simulation.width;
      var scaleY = size.height / simulation.height;
      simulation.nodes.forEach(function (node) {
        node.x = clamp(node.x * scaleX, NODE_PADDING, size.width - NODE_PADDING);
        node.y = clamp(node.y * scaleY, NODE_PADDING, size.height - NODE_PADDING);
        if (node.fx !== null) {
          node.fx = node.x;
          node.fy = node.y;
        }
      });
      simulation.width = size.width;
      simulation.height = size.height;
      simulation.clusterCenters = buildClusterCenters(simulation.nodes, size.width, size.height);
      svg.setAttribute("viewBox", "0 0 " + size.width + " " + size.height);
      renderGraph();
      if (reducedMotion.matches) { settleImmediately(); } else { startSimulation(0.55); }
    }

    function measureGraph() {
      var bounds = svg.getBoundingClientRect();
      return {
        width: Math.max(bounds.width, 640),
        height: Math.max(bounds.height, 460)
      };
    }

    function setGraphStats(graph) {
      var meta = graph.meta || {};
      var shown = meta.notes_shown || graph.nodes.length;
      var label = shown + " notes";
      if (meta.truncated) { label = shown + "/" + meta.notes_total + " notes"; }
      if (statNodes) {
        statNodes.textContent = label;
        if (meta.vault) { statNodes.title = meta.vault + " (" + (meta.files_on_disk || 0) + " md files)"; }
      }
      if (statLinks) { statLinks.textContent = graph.links.length + " links"; }
    }

    function showEmpty(message) {
      if (!empty) { return; }
      empty.textContent = message;
      empty.hidden = false;
    }

    function hideEmpty() {
      if (!empty) { return; }
      empty.hidden = true;
    }

    bindGraphInteraction();
    bindGraphLifecycle();
    loadGraph();

    return { reload: loadGraph };
  }

  function buildClusterCenters(nodes, width, height) {
    var groups = Array.from(new Set(nodes.map(function (node) { return node.group; }))).sort();
    var centers = new Map();
    var centerX = width / 2;
    var centerY = height / 2;
    if (groups.length <= 1) {
      if (groups.length === 1) { centers.set(groups[0], { x: centerX, y: centerY }); }
      return centers;
    }
    var radiusX = width * 0.28;
    var radiusY = height * 0.24;
    groups.forEach(function (group, index) {
      var angle = (Math.PI * 2 * index) / groups.length - Math.PI / 2;
      centers.set(group, {
        x: centerX + Math.cos(angle) * radiusX,
        y: centerY + Math.sin(angle) * radiusY
      });
    });
    return centers;
  }

  function svgPoint(element, event) {
    var point = element.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    var matrix = element.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : point;
  }

  function limitVelocity(node, maxSpeed) {
    var speed = Math.hypot(node.vx, node.vy);
    if (speed <= maxSpeed) { return; }
    if (maxSpeed <= 0) {
      node.vx = 0;
      node.vy = 0;
      return;
    }
    node.vx = (node.vx / speed) * maxSpeed;
    node.vy = (node.vy / speed) * maxSpeed;
  }

  function stableAngle(value) {
    var hash = 2166136261;
    for (var index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return ((hash >>> 0) / 4294967296) * Math.PI * 2;
  }

  function createSvg(tag, attrs) {
    var element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(function (key) { element.setAttribute(key, attrs[key]); });
    return element;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  window.createVaultGraph = createVaultGraph;
  var config = window.__GRAPH_CONFIG__ || {};
  if (document.getElementById(config.svgId || "vault-graph")) {
    createVaultGraph(config);
  }
})();
</script>
</body>
</html>
"""


def render_page(vault_path, graph_config):
    """Build the HTML page, injecting the vault path and renderer config."""
    return (
        PAGE_TEMPLATE
        .replace("%%GRAPH_CONFIG%%", json.dumps(graph_config))
        .replace("%%VAULT_PATH%%", str(vault_path))
    )


# --------------------------------------------------------------------------
# Server (stdlib only)
# --------------------------------------------------------------------------


class _GraphHandler(BaseHTTPRequestHandler):
    server_version = "VaultGraph/1.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = render_page(
                self.server.vault_path,
                {"endpoint": "/graph.json", "vaultPath": str(self.server.vault_path)},
            ).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        elif path == "/graph.json":
            graph = build_vault_graph(self.server.vault_path, self.server.max_nodes)
            body = json.dumps(graph).encode("utf-8")
            content_type = "application/json"
        else:
            self.send_error(404, "Not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def serve(vault_path, host, port, max_nodes, open_browser):
    graph = build_vault_graph(vault_path, max_nodes)
    meta = graph["meta"]
    print("vault:  %s" % meta["vault"])
    print("notes:  %d/%d shown%s" % (
        meta["notes_shown"],
        meta["notes_total"],
        " (truncated)" if meta["truncated"] else "",
    ))
    print("links:  %d" % len(graph["links"]))

    server = ThreadingHTTPServer((host, port), _GraphHandler)
    server.daemon_threads = True
    server.vault_path = vault_path
    server.max_nodes = max_nodes

    url = "http://%s:%d/" % (host, port)
    print("serving %s  (Ctrl+C to stop)" % url)

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("stopped")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Single-file Markdown vault graph viewer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("GRAPH_VAULT_PATH") or str(Path.home() / "projects" / "brain"),
        help="Markdown vault root (default: $GRAPH_VAULT_PATH or ~/projects/brain)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8014)
    parser.add_argument(
        "--max-nodes", type=int, default=0,
        help="cap notes by link degree (0 = full graph)",
    )
    parser.add_argument(
        "--json", nargs="?", const="-", default=None, metavar="PATH",
        help="dump graph JSON to PATH (or '-' for stdout) and exit",
    )
    parser.add_argument(
        "--html", default=None, metavar="PATH",
        help="write a standalone offline HTML page and exit",
    )
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)

    vault = Path(args.vault).expanduser()

    if args.json is not None:
        graph = build_vault_graph(vault, args.max_nodes)
        payload = json.dumps(graph, indent=2)
        if args.json == "-":
            print(payload)
        else:
            Path(args.json).write_text(payload, encoding="utf-8")
            meta = graph["meta"]
            print("wrote %s (%d notes, %d links)" % (args.json, meta["notes_shown"], len(graph["links"])))
        return 0

    if args.html is not None:
        graph = build_vault_graph(vault, args.max_nodes)
        page = render_page(vault, {"data": graph, "vaultPath": str(vault)})
        Path(args.html).write_text(page, encoding="utf-8")
        meta = graph["meta"]
        print("wrote %s (%d notes, %d links, %d bytes)" % (
            args.html, meta["notes_shown"], len(graph["links"]), len(page)
        ))
        return 0

    serve(vault, args.host, args.port, args.max_nodes, not args.no_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
