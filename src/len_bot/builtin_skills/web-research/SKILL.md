---
name: web-research
description: Research public web sources reachable from a task, distinguishing retrieved evidence from unavailable or dynamic pages.
---

# Web research

Use this for claims that need current public sources. The image has `curl` and `jq`; public HTTP(S) access goes through this task's configured proxy and limits.

- Begin with the user's URLs or identifiable primary sources. Fetch the actual page or document with `curl`, check the final URL, status, and retrieval date, and follow relevant source links deliberately. Base each claim on page content you fetched.
- Compare publication date with event date for time-sensitive claims. Keep a compact source list: URL, publisher, date, and which claim the page supports. Prefer primary records for precise figures, rules, and technical details.
- If a page requires JavaScript, use the public-browser skill when this task has it; otherwise report the limitation or use another retrieved source that answers the same question.
- Write the requested answer or report under `/workspace/out` with links beside supported claims. To deliver a file, use `deliver_file(path, name, note)`.
