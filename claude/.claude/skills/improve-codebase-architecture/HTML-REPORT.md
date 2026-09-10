# HTML Report Format

Self-contained HTML in OS temp dir. Use Tailwind (CDN) and Mermaid (CDN). Mix Mermaid (graphs/flows) with hand-built HTML/SVG (mass/editorial diagrams).

## Scaffold
```html
<!doctype html>
<html lang="en">
  <head>
    <script src="https://cdn.tailwindcss.com"></script>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: true, theme: "neutral" });
    </script>
    <style> .seam { stroke-dasharray: 4 4; } .leak { stroke: #dc2626; } .deep { background: linear-gradient(135deg, #0f172a, #1e293b); } </style>
  </head>
  <body class="bg-stone-50 text-slate-900 font-sans">
    <main class="max-w-5xl mx-auto px-6 py-12 space-y-12">
      <header><!-- Repo name, date, compact legend --></header>
      <section id="candidates" class="space-y-10"><!-- Cards --></section>
      <section id="top-recommendation"><!-- Top pick --></section>
    </main>
  </body>
</html>
```

## Candidate Card (`<article>`)
- **Title**: Short (e.g., "Collapse Order intake").
- **Badge row**: Strength (Strong=emerald, Worth exploring=amber, Speculative=slate) + dependency category.
- **Files**: Monospaced (`font-mono text-sm`).
- **Before/After Diagram**: Side-by-side columns (~320px tall).
- **Problem/Solution**: 1 sentence each.
- **Wins**: Bullets, ≤6 words each. Use glossary terms (locality, leverage).
- **ADR callout**: Amber-tinted box if applicable.

## Diagram Patterns
Mix patterns. Do not solely rely on Mermaid.
- **Mermaid Graph**: Good for dependencies/calls. Style `.leak` red, `.deep` dark.
- **Hand-built Boxes/Arrows**: HTML/SVG. Good for thick-bordered deep modules with grayed-out internals.
- **Cross-section**: Stacked horizontal bands (thin layers consolidating into one thick band).
- **Mass Diagram**: Interface size vs. Implementation size rectangles (shallow = equal; deep = tall implementation).
- **Call-graph Collapse**: Nested tree collapsed into single box.

## Style & Tone
- **Visuals**: Editorial, generous whitespace, sparing color (accent + red/amber). Label text: `text-xs uppercase tracking-wider`.
- **Tone**: Plain English. Strict Glossary: module, interface, implementation, depth, seam, adapter, leverage, locality. (Never: component, service, API, boundary).
- **Top recommendation**: 1 large card, candidate name, 1 sentence rationale, anchor link.
