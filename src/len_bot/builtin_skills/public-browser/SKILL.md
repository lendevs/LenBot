---
name: public-browser
description: 在任务的匿名浏览器里操作动态公开网页，使用已配置的 Playwright CLI。
---

# Public browser

Use `lenbot-browser` for public pages that need interaction. It uses this task's anonymous browser session and configured public network proxy.

- Run `lenbot-browser open https://example.com`, then `lenbot-browser snapshot`. Read the JSON snapshot before choosing an element reference such as `e4`; take a fresh snapshot after navigation or a substantial page change. Examples: `lenbot-browser fill e4 "search text"`, `lenbot-browser click e5`.
- Attach task files to an observed file input with `lenbot-browser attach-files e4 /inputs/brief.pdf /workspace/out/table.csv`. If clicking a button opens a file chooser, use `lenbot-browser upload /inputs/brief.pdf` instead. `attached` means file selection completed; submit the page as the task requires.
- To download from an observed link or button, run `lenbot-browser download e5` **instead of clicking it first**. It sets up the download wait, clicks once, waits for the bytes, and keeps the browser's filename in a unique `out/browser/download-*` directory. It captures a download from the current tab, so select the relevant tab first. For a site-specific multi-step interaction, keep using the page controls and inspect the files they produce.
- `lenbot-browser screenshot` and `lenbot-browser pdf` save into their own `out/browser/` directories. Explicit names also go there, one new name per save: `lenbot-browser screenshot --filename=out/browser/proof.png`. Screenshot supports an observed element ref, `--full-page`, `--hires`, and `--type`.
- File commands return `status`, `files`, actual names, sizes and MIME types, page source, and a task resource `reference` for saved outputs. They appear in the task resource browser for preview or further work. Call `deliver_file` with the returned `/workspace/...` path to create a delivery. Downloads started by ordinary clicks have no file-command receipt; find their files before using them.
- Read the returned JSON, including `isError`; `isError: true` is a failure even when the exit code is 0. When an operation's result is uncertain, observe the page again before deciding the next step.
- Run `lenbot-browser close` when finished. Its cookies and profile belong to this task. When a page requires login or a verification step, ask for help through the task's interaction tools.
