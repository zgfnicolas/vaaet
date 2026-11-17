# El frontend de VAAET

Leé este archivo antes de diseñar o revisar el frontend de `vaaet-app`. Las
decisiones marcadas como ADR no las fija esta skill: el diseño las nombra como
pendientes.

## Contenido

1. Límites que impone el repo
2. Ubicación y archivos de la raíz
3. Contrato con la API
4. Licencias
5. Decisiones que necesitan ADR

## 1. Límites que impone el repo

| Fuente | Regla para el frontend |
|---|---|
| `AGENTS.md` | `vaaet-app/` está reservado: sin código, framework ni dependencias hasta tener alcance aprobado y un contrato HTTP versionado. Las dependencias nuevas son «Ask». |
| ADR-0021 | El navegador sólo ve la API HTTP. El frontend nunca accede a PostgreSQL, a DVC, a Drive ni a los paquetes Python. |
| ADR-0022 | Servir la app con visión exige la vía AGPL (demo pública con el checklist) o una licencia Enterprise verificada fuera de Git. |
| RN-24 | Videos, datasets privados, calibraciones y credenciales no entran a Git, logs, bundles ni ejemplos. |
| RN-02 | La UI nunca presenta `Accident` como resultado automático: sólo una persona lo registra, con nota y contexto revisado. |

## 2. Ubicación y archivos de la raíz

- Ubicación sugerida: `vaaet-app/web/`, con el backend Python en `vaaet-app/`
  (la skill hexagonal). Un solo lockfile JS, dentro de `vaaet-app/web/`.
- El plan del frontend tiene que incluir los cambios de la raíz, porque el
  repo hoy no tiene JavaScript:
  - en `.gitignore`: `node_modules/`, `.next/`, `out/`, `coverage/` y
    `*.tsbuildinfo` (`dist/` y `.env` ya están);
  - un job nuevo en `ci.yml` con filtro de rutas `vaaet-app/web/**`, y la
    actualización de los filtros existentes;
  - `.dockerignore` o la configuración del host estático;
  - el ecosistema npm en Dependabot o Renovate, si existe.
- Los tests de repositorio de `vaaet-ml/tests/repository/` revisan la
  estructura. Verificá con `pytest tests/repository` que un `package.json`
  nuevo no rompa ninguna de sus reglas.

## 3. Contrato con la API

- La fuente del contrato es el OpenAPI que publica el backend FastAPI
  (`/api/v1/`). El frontend genera sus tipos desde ese archivo (por ejemplo,
  con `openapi-typescript`). El archivo generado se versiona.
- El CI exporta el OpenAPI del backend, regenera los tipos y falla con
  `git diff --exit-code` si difieren. Así, un cambio de contrato rompe el PR
  que lo introduce, no la producción.
- La URL de la API llega en runtime (`/config.json` en una SPA), no horneada
  en `VITE_*`, para compilar una vez y desplegar en varios entornos.
- La autenticación y el almacenamiento de la sesión los decide el ADR. Nunca
  un token de servicio en el bundle.
- Los videos y resultados se sirven por la API o por URLs firmadas del
  almacenamiento. El frontend no conoce rutas internas ni buckets.

## 4. Licencias

- La vía AGPL obliga a ofrecer el código correspondiente del servicio a sus
  usuarios. Eso incluye el frontend: seguí el
  [checklist de publicación](../../../../docs/governance/agpl-demo-release-checklist.md).
- Revisá la licencia de cada dependencia nueva contra la
  [política de licencias](../../../../docs/governance/third-party-licenses.md).
  Una herramienta como `license-checker` en CI reporta las incompatibles.
- El bundle no incluye pesos, videos ni datos de ejemplo sin procedencia.

## 5. Decisiones que necesitan ADR

- Framework: SPA Vite o Next.js (criterio en §2.2 del `SKILL.md`).
- Gestor de paquetes: pnpm 11 o npm 12, y cómo se instala en CI y Docker.
- Ubicación exacta, despliegue (CDN, nginx o contenedor) y dominio.
- Autenticación de usuarios y revisores, y manejo de la sesión.
- Generación del cliente de la API y versionado del contrato.
- Vía de licencia (ADR-0022) y entorno de la demo.
