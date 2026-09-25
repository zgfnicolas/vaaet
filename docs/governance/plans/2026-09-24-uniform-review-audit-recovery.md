# Plan gobernado — Auditoría HITL y recuperación uniforme

- Fecha: 2026-09-24
- Alcance: Persistence 0.3.1 y ML 4.9.1; Core permanece en 0.2.2
- Decisión: [ADR-0034](../../architecture/decisions/0034-uniform-review-audit-evidence.md)
- Estado: implementado; aceptación operacional pendiente de PostgreSQL 17, Colab y Drive

## Fases

1. Reproducir exportación de decisiones pendientes, metadatos incompatibles,
   errores externos visibles y reintentos con UUID nuevo.
2. Validar auditoría en fuentes PostgreSQL, backup y ZIP antes de consolidar
   etiquetas humanas; conservar los históricos ambiguos para inspección.
3. Preparar metadata desde las filas reales antes de abrir corridas PostgreSQL.
4. Retener decisiones del widget antes de enviarlas y traducir fallos de
   reconciliación sin exponer parámetros del driver.
5. Ejecutar integración PostgreSQL 17 con roles separados, backup real y
   recuperación sin duplicaciones; repetir en Colab y Drive.

## Criterio de cierre

Cada regresión debe pasar y el job PostgreSQL debe recolectar todas las pruebas
obligatorias. Una validación ambiental no ejecutada se informa como pendiente;
no se declara aptitud operacional por las pruebas unitarias. No se reescriben
migraciones, paquetes históricos, holdouts ni datos privados.
