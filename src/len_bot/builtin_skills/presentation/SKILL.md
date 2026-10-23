---
name: presentation
description: Produce or revise PPTX slide decks with source-backed content and checks of slide structure and assets.
---

# Presentations

Use this for a slide deck deliverable. Write the final `.pptx` to `/workspace/out`.

- Start from the requested audience, purpose, source material, and visual constraints. Keep factual claims traceable to the supplied material or a source you read; use concise slide text and keep important charts or quotations.
- Pandoc is installed and can create a simple PPTX from Markdown. For controlled layouts, install a presentation library such as `pptxgenjs` in the task workspace when needed.
- Open or inspect the generated deck with a parser to check slide count, titles, media, and speaker notes. Checking the actual appearance needs a renderer; without one, state that the layout was not rendered.
- Deliver the final file using `deliver_file(path, name, note)`.
