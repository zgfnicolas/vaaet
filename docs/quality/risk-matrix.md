<!-- context: VAAET/docs/quality/risk-matrix.md — Matriz de riesgos y mitigación.
Complementa BIAS_AND_LIMITATIONS.md y FEASIBILITY.md. -->

# Matriz de Riesgos y Mitigación — VAAET

## Identificación del Proyecto

| Campo | Detalles |
|---|---|
| **Nombre del Proyecto** | VAAET — Video Advanced Analysis of Traffic |
| **Versión** | 4.6.1 |
| **Responsable Técnico** | Facundo Nicolás González |
| **Última Revisión** | 2026-08-30 |

---

## Matriz de Riesgos

| ID | Riesgo | Categoría | Probabilidad | Impacto | Severidad | Estrategia de Mitigación | Plan de Contingencia |
|---|---|---|---|---|---|---|---|
| R-001 | **Desconexión de Google Colab** durante procesamiento de video largo | Infraestructura | Alta | Serio | 🔴 Crítico | Procesar clips acotados, descargar outputs y conservar snapshots/paquetes en Drive cuando corresponda | Reanudar desde el último output materializado; no asumir checkpoint frame a frame |
| R-002 | **GPU no disponible** en Colab Free/Pro | Infraestructura | Media | Moderado | 🟡 Alto | Preflight tipado antes de tareas costosas; elegir otro runtime GPU gestionado | Detener el workflow de visión sin fallback CPU y reintentar cuando haya GPU |
| R-003 | **Fallo de conexión PostgreSQL** | Infraestructura | Media | Bajo | 🟢 Medio | Error redactado y outputs locales preservados | Reintentar operaciones idempotentes; exportar paquete local |
| R-004 | **Cambio de zoom/ángulo de cámara SISE** durante un clip | Dominio | Alta | Moderado | 🟡 Alto | `VideoViewPlan` explícito, perfiles locales por vista y descarte de minutos mixtos | Corregir el plan y reprocesar; no publicar MAE sin ground truth |
| R-005 | **Accidente/Congested con soporte real insuficiente** | ML/Datos | Alta | Serio | 🔴 Crítico | Accident fuera del MLP; sintéticos sólo en train/estrés | Holdout humano, shadow mode y gates mínimos de episodios/exposición |
| R-006 | **Drift del modelo** por cambios en patrones de tráfico | ML/Datos | Baja | Moderado | 🟢 Medio | Monitoreo de distribución de features en producción (futuro) | Re-entrenar con datos recientes cuando F1-macro caiga < 0.80 |
| R-007 | **Auto-etiquetado circular** introduce sesgo sistémico | ML/Datos | Alta | Moderado | 🟡 Alto | Umbrales calibrados a percentiles del puente; HITL para validación | Migrar progresivamente a ground truth humano |
| R-008 | **Incompatibilidad de versiones** de dependencias (TF, YOLO) | Técnico | Media | Moderado | 🟡 Alto | Extras declarados en ambos `pyproject.toml`, CI en Python 3.10–3.13 y `pip check` | Reinstalar los paquetes locales y extras del workflow desde el checkout; no introducir lockfiles sin una decisión aprobada |
| R-009 | **Exposición accidental de credenciales** de BD | Seguridad | Baja | Crítico | 🔴 Crítico | Variables de entorno exclusivamente; `.env` en `.gitignore`; nunca imprimir en outputs | Rotar credenciales inmediatamente; auditar historial de git |
| R-010 | **Pérdida de artefactos de modelo** entre sesiones de Colab | Operativo | Media | Serio | 🟡 Alto | Exportación del bundle completo a Google Drive | Re-ejecutar entrenamiento para regenerar artefactos |
| R-011 | **Contaminación o deriva del holdout humano** | ML/Datos | Baja | Serio | 🟡 Alto | Snapshots inmutables, grupos excluidos de train, checksums y fingerprint | Detener promoción y crear una generación nueva con motivo auditable |

---

## Mapa de Calor

```
              Bajo        Moderado      Serio        Crítico
Alta     │  ────────  │  R-004,R-007 │  R-001,R-005 │  ─────────  │
Media    │  ────────  │  R-002,R-008 │  R-010       │  ─────────  │
Baja     │  R-003     │  R-006       │  R-011       │  R-009      │
```

---

## Plan de Revisión

- **Frecuencia**: Revisión trimestral o ante cambios mayores de arquitectura
- **Responsable**: Facundo Nicolás González
- **Próxima revisión**: 2026-11-27

---

Responsable del documento: Facundo Nicolás González
Fecha de revisión: 2026-08-30
