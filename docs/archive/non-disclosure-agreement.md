<!-- context: VAAET/docs/governance/non-disclosure-agreement.md — Acuerdo de Confidencialidad.
Preparado para uso futuro cuando el proyecto escale a contexto corporativo. -->

# Acuerdo de Confidencialidad (NDA) — VAAET

> **Archivado el 2026-11-15. No normativo.** Borrador para un uso futuro que
> todavía no ocurrió; no está vigente ni firmado.

## Identificación del Proyecto

| Campo | Detalles |
|---|---|
| **Nombre del Proyecto** | VAAET — Video Advanced Analysis of Traffic |
| **Versión** | 1.0.0 |
| **Estado** | Borrador (para uso futuro) |
| **Responsable Técnico** | Facundo Nicolás González |
| **Última Revisión** | 2026-07-23 |

---

## 1. Objeto del Acuerdo

El presente acuerdo establece las obligaciones de confidencialidad para las partes que accedan a información reservada del proyecto VAAET, incluyendo pero no limitado a:

- Videos de vigilancia SISE del Puente Gral. Manuel Belgrano
- Datos de telemetría almacenados en la base de datos de producción
- Credenciales de acceso a infraestructura (PostgreSQL administrado, APIs)
- Datos de calibración específicos del puente (landmarks, factores de corrección)
- Información comercial y estratégica del proyecto

---

## 2. Definición de Información Confidencial

### 2.1 Es Información Confidencial

| Tipo | Ejemplos |
|---|---|
| **Datos de video** | Archivos `.mp4` de cámaras SISE |
| **Datos de producción** | Registros de `vaaet_raw`, `vaaet_ml`, `vaaet_feedback` y `vaaet_ops` |
| **Credenciales** | Colab Secrets o variables `VAAET_*` específicas por perfil |
| **Modelos entrenados** | Artefactos `.keras` y `.joblib` con datos propietarios |
| **Parámetros de calibración** | `pixels_per_meter`, factores de perspectiva del puente |
| **Información estratégica** | Planes comerciales, contratos con entes viales |

### 2.2 NO Es Información Confidencial

| Tipo | Ejemplos |
|---|---|
| **Código fuente** | Todo el contenido del repositorio público (licencia AGPL-3.0-only) |
| **Documentación** | Todos los archivos `.md` del repositorio |
| **Arquitectura** | Diagramas, ADRs, plantillas |
| **Datos sintéticos** | Generados por `vaaet-ml/src/vaaet_ml/features/synthetic.py` |
| **Información pública** | Publicaciones académicas derivadas |

---

## 3. Obligaciones de las Partes

### 3.1 La Parte Receptora se compromete a:

1. **No divulgar** información confidencial a terceros sin autorización escrita
2. **No copiar ni almacenar** videos SISE fuera de los entornos autorizados
3. **No compartir** credenciales de acceso a bases de datos o APIs
4. **Notificar** inmediatamente al responsable del proyecto ante cualquier exposición accidental
5. **Devolver o destruir** toda información confidencial al finalizar la relación

### 3.2 El Propietario se compromete a:

1. **Identificar claramente** qué información es confidencial
2. **Proporcionar acceso** seguro a los datos necesarios para el trabajo
3. **Mantener actualizada** la [política de seguridad](../governance/security-policy.md)

---

## 4. Duración

Este acuerdo entra en vigencia al momento de la firma y permanece activo durante **2 (dos) años** después de la finalización de la relación profesional, excepto para información que por su naturaleza requiera protección indefinida (credenciales, datos de producción).

---

## 5. Excepciones

La obligación de confidencialidad no aplica cuando:
- La información ya era de dominio público antes de la divulgación
- La información fue desarrollada independientemente por la parte receptora
- La divulgación es requerida por ley o autoridad judicial

---

## Firmas

| Parte | Nombre | Fecha | Firma |
|---|---|---|---|
| **Propietario** | Facundo Nicolás González | _____________ | _____________ |
| **Parte Receptora** | __________________ | _____________ | _____________ |

---

Responsable del documento: Facundo Nicolás González
Fecha de revisión: 2026-07-23
Documentos de referencia: [SECURITY.md](../../SECURITY.md), [política de seguridad](../governance/security-policy.md)
