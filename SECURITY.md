# Política de seguridad — VAAET

## Reporte privado de vulnerabilidades

No publiques vulnerabilidades ni secretos en Issues. El canal previsto es
[GitHub Private Vulnerability Reporting](https://github.com/zgfnicolas/vaaet/security/advisories).

El responsable debe habilitar esa opción en la configuración del repositorio y
comprobar el formulario antes de anunciar este canal como operativo. Mientras no
esté habilitado, no existe un canal público alternativo para divulgar detalles
sensibles. GitHub documenta la activación para administradores en su
[guía de configuración](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

Al reportar, incluí una descripción redactada, el impacto y pasos mínimos de
reproducción. No adjuntes DSN, contraseñas, certificados, videos privados ni
datos HITL.

## Alcance

- Exposición de secretos en código, notebooks, CI u outputs.
- Vulnerabilidades en dependencias declaradas por `vaaet-core` o `vaaet-ml`.
- Inyección SQL o acceso no autorizado en la persistencia de laboratorio.
- Validación insuficiente del bundle antes de deserializarlo.

Quedan fuera del alcance los servicios administrados de terceros y el contenido
restringido de videos; el responsable de cada proveedor conserva sus controles
de infraestructura, cifrado en reposo, parches y logs.

## Controles vigentes

- Colab Secrets o variables locales por perfil; nunca secretos en celdas.
- SQLAlchemy parametrizado, TLS `verify-full` recomendado y `disable` sólo en
  localhost.
- Roles de mínimo privilegio; Alembic y cuentas administrativas fuera de Colab.
- `pipeline_runs` redacta categorías, sin DSN ni mensajes sensibles.
- Git no almacena modelos, bundles, videos, datos privados ni archivos `.env`.
- Serving de visión sólo por la vía AGPL pública o Enterprise privada/comercial
  descrita en [ADR-0022](docs/architecture/decisions/0022-agpl-public-demo-path.md).

## Versiones soportadas

Se soporta la línea activa del laboratorio, 4.x, sobre `main`. La versión
exacta de cada componente está en su `pyproject.toml`; los cambios de seguridad
se validan contra esas versiones y el CI vigente.
