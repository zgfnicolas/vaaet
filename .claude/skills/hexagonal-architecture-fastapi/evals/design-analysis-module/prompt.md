---
tags: [skill-creator]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Vamos a empezar el backend de la web de VAAET en vaaet-app con FastAPI. Diseñame el módulo de análisis de video: desde la web el usuario sube un video y elige la revisión del modelo, un worker lo procesa con vaaet-core (analyze_video + el bundle) y la telemetría clasificada se guarda en PostgreSQL con vaaet-persistence. También quiero un CLI para reprocesar un análisis. Dame el diseño y el esqueleto de código (puertos, adaptadores, configuración de FastAPI y tests). Escribí todo en archivos dentro de la carpeta de salida, no en el repo.
