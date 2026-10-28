---
name: skill-writing
description: Write a focused, reusable task skill with valid metadata and instructions grounded in the task's available tools.
---

# Skill writing

Use this when the requested deliverable is a reusable skill. A task-created skill goes in `/workspace/skills/<name>/SKILL.md`.

- Choose one narrow capability and a lowercase hyphenated directory name. Put the same `name` and a discriminating `description` in YAML frontmatter, then give the reader the workflow, inputs, outputs, and checks that the task alone would leave unclear.
- Describe the tools and services available in the intended environment. If a workflow needs a package, say how to install it in that task workspace. Leave out empty section templates, copied manuals, author credits, and unrequested invocation metadata.
- Re-read the file to check frontmatter, links, commands, and example paths. A new skill takes effect once a session loads it.
- For handoff, put the skill file or a Python-standard-library archive of its folder in `/workspace/out` and call `deliver_file(path, name, note)`. The operator adopts it into group or shared skills.
