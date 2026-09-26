# Plan gobernado — Recuperación de revisiones y paquetes íntegros

- Fecha: 2026-09-26
- Alcance: Persistence 0.3.2 y ML 4.9.2; Core permanece en 0.2.2
- Decisión: [ADR-0035](../../architecture/decisions/0035-review-recovery-and-lossless-packages.md)
- Estado: implementado; aceptación operacional pendiente

## Fases

1. Reproducir asociación a otro clip, pérdida de texto CSV, finalización con
   resultado incierto y consultas de auditoría por corrida.
2. Vincular recuperación y callbacks al intento y sesión originales. Bloquear
   decisiones inciertas en el controlador y en la sesión gestionada.
3. Publicar un codec tipado y fingerprint HITL que distingan nulos de cadenas
   vacías; preservar e inspeccionar los ZIP históricos sin reescribirlos.
4. Validar el ZIP temporal antes de ocupar el destino y agrupar consultas de
   auditoría en lotes de hasta 500.
5. Ejecutar suites y calidad estática, integrar PostgreSQL 17 con cuatro roles
   y verificar en Colab la recuperación y publicación coordinada en Drive.

## Criterio de cierre

Cada hallazgo debe tener una regresión y evidencia. Las comprobaciones
ambientales no ejecutadas permanecen pendientes; los mocks no acreditan el
recorrido operacional. No se alteran migraciones, artefactos privados,
históricos, remotos DVC ni servidores del usuario.

## Evidencia local

- Core: 271 pruebas aprobadas.
- Persistencia: 117 aprobadas; 9 integraciones omitidas sin PostgreSQL 17 local.
- ML: 561 aprobadas; 10 integraciones omitidas por entorno.
- Ruff, Pyright sin errores, compilación, auditoría de los cuatro notebooks,
  enlaces Markdown, `pip check` y `git diff --check`: aprobados.
- Quedan pendientes la integración con PostgreSQL 17 y cuatro roles, la
  recuperación en Colab con un clip real y la publicación coordinada en Drive.
  Estas omisiones impiden declarar aceptación operacional o producción.
