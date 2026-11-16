---
type: llm
focus: trace
weight: 1
---

The video analysis runs outside the HTTP request: the upload endpoint enqueues a job and returns 202 (or equivalent), and a separate worker calls analyze_video
