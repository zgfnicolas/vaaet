---
name: js-project-configuration
description: Configura y revisa proyectos JavaScript y TypeScript (Node.js, React, Vite, Next.js) reproducibles y con supply chain endurecida, adaptado al futuro frontend de VAAET en vaaet-app. El gestor por defecto, que un agente usa salvo que el repo o una decisión indiquen otra cosa, es npm 12 instalado explícitamente (Node 26 trae npm 11); pnpm 11 queda como alternativa documentada, con los casos en que corresponde. Cubre runtime Node LTS fijado, política de install scripts por allowlist, cooldown de versiones nuevas, fuentes Git y URL bloqueadas, lockfile como contrato con lockfile-lint, package.json, .npmrc y pnpm-workspace.yaml, variables de entorno validadas y la separación entre build y runtime (NEXT_PUBLIC_ y VITE_ son públicas), CI en GitHub Actions, Renovate o Dependabot con cooldown, artefactos Docker o estáticos mínimos, ciclo de vida del proceso y trusted publishing. Usala siempre que aparezca un package.json, un lockfile de npm o pnpm, .npmrc, .node-version, node_modules, un Dockerfile de Node, variables NEXT_PUBLIC_ o VITE_, Dependabot o Renovate para npm, o cuando se diseñe o revise el frontend o la web app de vaaet-app, aunque no se diga «configuración». No la uses para escribir código de vaaet-app sin plan gobernado y ADR aprobados.
---

# Configuración de proyectos JS/TS (VAAET)

Baseline verificado el 2026-11-16. Las versiones envejecen rápido: revalidalas
con las fuentes de §12 antes de usarlas en un proyecto nuevo. Skills
relacionadas: `python-project-configuration` (backend),
`hexagonal-architecture-fastapi` (API que consume el frontend) y
`governed-plan`.

**Principio rector:** un clon limpio más una instalación congelada producen el
mismo árbol, el mismo build y el mismo artefacto en la laptop, en CI y en
producción. Prioridades, en orden: reproducibilidad, seguridad de la supply
chain, correctitud, simplicidad y velocidad.

## 0. Modo de trabajo

### 0.1 VAAET primero

VAAET hoy no tiene JavaScript. El frontend va a vivir en `vaaet-app/`, que está
reservado (`AGENTS.md`). Antes de crear un `package.json` ahí:

1. Proponé el diseño y un plan gobernado (skill `governed-plan`) y esperá la
   aprobación.
2. El ADR del frontend decide:
   - el framework (§2.2);
   - el gestor de paquetes (npm 12 por defecto; pnpm 11 sólo en los casos de
     §0.2);
   - la ubicación (por ejemplo, `vaaet-app/web/`);
   - el despliegue;
   - la vía de licencia (ADR-0022).
3. El frontend habla **sólo** con la API HTTP versionada (ADR-0021). Nunca
   lee PostgreSQL, el registro DVC ni archivos de los componentes Python.

Límites, contrato con la API, licencias y cambios de la raíz:
[references/vaaet-frontend.md](references/vaaet-frontend.md). Para un
proyecto JS fuera de VAAET, aplicá la skill directamente.

### 0.2 Gestor: qué usa un agente

**Por defecto, un agente (incluido un LLM como Claude) usa npm 12.** npm es el
gestor que viene con Node, el que conoce cualquier persona o herramienta, y en
la versión 12 bloquea los install scripts sin aprobación y las dependencias Git
y URL. Node 26 trae npm 11, así que npm 12 se instala explícitamente
(`npm install -g npm@12.x.y`) en local, en CI y en Docker antes de `npm ci`.

Antes de elegir, aplicá esta regla en orden:

1. **Detectá lo que ya usa el repo** o el directorio del proyecto:
   `package-lock.json`, `pnpm-lock.yaml` o `pnpm-workspace.yaml`, `yarn.lock`,
   `bun.lock`. Si hay un gestor, seguí con ese. No migres por iniciativa
   propia: cambiar de gestor es un cambio de dependencias («Ask»).
2. **Si no hay ninguno**, usá npm 12 ([references/npm.md](references/npm.md)).
3. **Usá pnpm 11** ([references/pnpm.md](references/pnpm.md)) sólo si se
   cumple alguno de estos casos, y nombralo en la entrega:
   - el repo ya tiene `pnpm-lock.yaml` o `pnpm-workspace.yaml`;
   - el ADR del frontend eligió pnpm;
   - la persona lo pide explícitamente;
   - es un monorepo JS con varios paquetes propios que necesita `workspace:` y
     `catalog:` para unificar versiones;
   - hay dependencias fantasma (paquetes importados sin declararlos) que el
     `node_modules` plano de npm no detecta.
4. **Nunca mezcles** gestores ni lockfiles. Dejá escrito el gestor elegido y su
   motivo en la entrega.

### 0.3 Contexto a determinar

```text
TIPO=        SPA Vite · app Next.js · backend Node · librería publicada · monorepo
PM=          npm 12 (por defecto) · pnpm 11 (alternativa, §0.2) · yarn o bun sólo si el repo ya los usa
RUNTIME=     Node 26 LTS · 24 (mantenimiento) si una dependencia lo exige
DESPLIEGUE=  estático/CDN · contenedor · plataforma gestionada
REGISTRY=    npmjs público · privado o proxy con scopes
```

### 0.4 Qué entregar

Archivos completos y comentados:
- `.node-version`;
- `package.json` (scripts, `engines`, `devEngines`, `packageManager`,
  `allowScripts`);
- `.npmrc` y/o `pnpm-workspace.yaml`;
- `.gitignore` y `.env.example`;
- el esquema de entorno;
- el workflow de CI;
- `renovate.json` o `dependabot.yml`;
- `Dockerfile` o la configuración del host estático.

Cada desviación del baseline lleva su motivo. En una revisión: hallazgos con
severidad, evidencia y corrección.

## 1. Reglas duras

1. **Runtime en Active o Maintenance LTS**, fijado en el repo
   (`.node-version`) y validado (`engines` y `devEngines`).
2. **Gestor fijado** (`packageManager` con versión exacta o
   `devEngines.packageManager`). Un solo lockfile, versionado y nunca editado a
   mano.
3. **Instalación congelada en CI y builds**: `npm ci` (con pnpm,
   `pnpm install --frozen-lockfile`).
4. **Install scripts por allowlist** (`allowScripts` en npm 12; `allowBuilds`
   en pnpm 11), en modo estricto en CI. Los diffs de la allowlist se revisan
   como el lockfile.
5. **Cooldown de versiones nuevas** (`min-release-age` en días; con pnpm,
   `minimumReleaseAge` en minutos), alineado con el bot. Excepciones sólo para
   fixes de seguridad, documentadas.
6. **Sin dependencias Git, URL ni tarball**, salvo una excepción documentada.
7. **Lockfile e integridad verificados en CI**: `lockfile-lint` sobre
   `package-lock.json` y `npm audit signatures`. Con pnpm, `pnpm-lock.yaml` no
   guarda la URL del tarball y `lockfile-lint` no aplica: ese rol lo cumplen
   `blockExoticSubdeps`, la instalación congelada y la revisión del diff.
   `npm audit` (o `pnpm audit`) es una señal, nunca un `audit fix --force`
   automático.
8. **Entorno validado por esquema al arrancar o al compilar.** Secretos fuera
   de Git, imágenes, logs y bundles. **`NEXT_PUBLIC_*` y `VITE_*` son
   públicos.**
9. **Artefacto mínimo**: sin devDependencies ni toolchain, como usuario no
   root y con apagado ordenado, o `dist/` estático sin Node.

## 2. Decisiones

### 2.1 Runtime y gestor

| Línea | Estado (noviembre de 2026) | Uso |
|---|---|---|
| Node 26 | Active LTS (EOL en abril de 2029) | Default para proyectos nuevos |
| Node 24 | Maintenance (EOL en abril de 2028) | Existentes; planificar la migración |
| Node 25 | Current impar, nunca LTS (EOL en junio de 2026) | Nunca en producción ni como `.node-version` |
| Node 22 | Maintenance (EOL en abril de 2027) | Migrar ya |
| ≤ 20 | EOL | Prohibido en producción |
| 27 | En desarrollo; LTS en octubre de 2027 | Sólo CI de compatibilidad |

Desde Node 27, sale una major por año (en abril) y todas pasan a LTS en
octubre.

**Node 26 trae npm 11.x, no npm 12.** El gestor sigue la regla de §0.2:

| Opción | Cómo se obtiene | Install scripts | Cuándo |
|---|---|---|---|
| **npm 12 (por defecto)** | `npm install -g npm@12.x.y` en local, en CI y en Docker, antes de instalar | Bloqueados por defecto; `strict-allow-scripts` los vuelve error en CI; Git y URL bloqueados | Siempre que el repo no use otro gestor |
| **pnpm 11 (alternativa)** | `pnpm/action-setup` en CI; mise, Volta o el instalador oficial en local | Bloqueados sin `allowBuilds`; cooldown de 1 día por defecto; subdependencias exóticas bloqueadas | Sólo en los casos de §0.2 |
| npm 11 (el incluido) | Viene con Node 26 | `allowScripts` sólo avisa | Sólo como transición; no cumple la regla 4 |

- Corepack ya no viene con Node desde la 25: no cuentes con él.
- `devEngines.packageManager` con una versión que el npm incluido no cumple
  falla con `EBADDEVENGINES` en `setup-node`. Instalá el gestor antes de
  `npm ci`.
- No acotes el gestor con un techo de major (`"npm": "<13"`): bloquea la
  instalación cuando sale la siguiente.
- No mezcles gestores ni lockfiles. Yarn Berry y Bun son válidos sólo si el
  repo ya los usa.

Políticas completas: [references/npm.md](references/npm.md) (por defecto) y
[references/pnpm.md](references/pnpm.md) (alternativa).

### 2.2 Framework del frontend de VAAET

Criterio para el ADR:

- **SPA Vite (sugerida).** La UI de VAAET es una aplicación autenticada que
  consume una API FastAPI, no un sitio que necesite SEO. Una SPA:
  - produce un `dist/` estático, servido por CDN o nginx, sin Node en
    producción;
  - no tiene secretos;
  - mantiene un único backend: el de la skill hexagonal.
- **Next.js 16**, sólo si el ADR justifica SSR o rutas de servidor. En ese
  caso, el servidor de Next es otro proceso que llama a la API; nunca habla
  con PostgreSQL ni con los componentes Python.

## 3. Dependencias

| Campo | Contiene | Error típico |
|---|---|---|
| `dependencies` | Lo que se importa en runtime (react, zod, el cliente de la API) | Poner zod en dev porque «sólo valida» |
| `devDependencies` | Build, tipos, lint y test | Meter el toolchain en la imagen de producción |
| `peerDependencies` | Lo que provee el consumidor (en librerías), con rango amplio | Fijar react exacto en una librería |
| `optionalDependencies` | Binarios por plataforma | Esconder instalaciones rotas |

En una app, `save-exact` (npm) o `savePrefix: ""` (pnpm): las versiones
directas son exactas y cada upgrade es explícito.

Antes de agregar una dependencia, respondé:

- ¿Ya lo resuelve la plataforma (`fetch`, `crypto.randomUUID`,
  `structuredClone`, `URL`, `Intl`)?
- ¿Cuántas transitivas suma? ¿Tiene install scripts?
- ¿Tiene mantenimiento y provenance?
- ¿Cuánto suma al bundle del cliente?
- ¿Es compatible con AGPL-3.0?
- ¿Qué pasa si se abandona?

Los overrides sólo sirven para parchear una transitiva vulnerable. Cada uno
lleva CVE, fecha, dueño y condición de salida (en pnpm, un comentario YAML; en
npm, un `docs/dependency-overrides.md` verificado en CI).

## 4. Supply chain por capas

| Capa | Control | Evita |
|---|---|---|
| Resolución | Cooldown en el gestor y en el bot | Versiones maliciosas recién publicadas |
| Fuentes | Git, URL y tarball bloqueados; scopes para paquetes internos | Código fuera del registry; dependency confusion |
| Instalación | Allowlist de scripts en modo estricto | Payloads en `preinstall` y `postinstall` |
| Lockfile | Instalación congelada, revisión de diffs y `lockfile-lint` (npm) | Árboles alterados, hosts inesperados |
| Integridad | `npm audit signatures` (npm); integrity del lockfile (pnpm) | Tarballs alterados |
| Vulnerabilidades | `npm audit --omit=dev` o `pnpm audit --prod` como señal | Advisories conocidos (no malware nuevo) |
| Superficie | Pocas dependencias; knip para detectar las que no se usan | Paquetes innecesarios |

Configuraciones de CI, `lockfile-lint` y bots:
[references/supply-chain-ci.md](references/supply-chain-ci.md).

## 5. Scripts como API del repo

Los scripts estándar son `dev`, `build`, `preview` o `start`, `typecheck`,
`lint`, `format:check`, `test`, `lint:lockfile` (con npm) y `check` (todo lo que corre el
CI).

- Sin `npx` para binarios locales: `node_modules/.bin` ya está en el `PATH`.
- Sin dependencias globales implícitas.
- Next.js 16 no tiene `next lint`, y `next build` ya no lintea: usá ESLint
  directo, con flat config.
- Hooks locales (lefthook, lint-staged) sólo para feedback rápido: el CI es la
  autoridad.

## 6. Entorno: build y runtime

| Stack | Público (llega al navegador) | Privado | Cambiar sin rebuild |
|---|---|---|---|
| Vite | `VITE_*`, horneado en `vite build` | No existe: una SPA no tiene secretos | `/config.json` servido por el host y leído al iniciar |
| Next.js | `NEXT_PUBLIC_*`, horneado en `next build` | Sin prefijo, leído en código de servidor | Leer `process.env` en el servidor y pasarlo como prop |
| Node | — | Todo | Variables en runtime |

- Para un artefacto que se compila una vez y se despliega en varios entornos,
  nada que cambie por entorno (la URL de la API, flags) va en `VITE_*` ni en
  `NEXT_PUBLIC_*`, salvo que se compile un artefacto por entorno a propósito.
- **Ningún secreto lleva esos prefijos, nunca.** Un token de la API en
  `VITE_API_TOKEN` se publica en el bundle.
- El esquema (Zod 4, con `z.url()` y no `z.string().url()`) valida al arrancar
  o al compilar, y reporta nombres de variables, nunca valores.

Código y tests: [references/env-and-build.md](references/env-and-build.md).

## 7. CI

Un workflow propio (`web.yml`, no un job dentro de `ci.yml`, cuyo filtro de
rutas es de todo el workflow), filtrado por el directorio del frontend:

1. checkout sin credenciales persistidas;
2. Node desde `.node-version`;
3. npm 12 instalado explícitamente (o el gestor alternativo fijado);
4. `npm ci --strict-allow-scripts`;
5. `lockfile-lint` y `npm audit signatures`;
6. typecheck, lint, formato y test;
7. build;
8. audit de producción.

Acciones fijadas por SHA, `permissions: { contents: read }`, caché de
descargas, nunca `node_modules`. Workflow completo en
[references/supply-chain-ci.md](references/supply-chain-ci.md).

## 8. Producción

- **SPA**: `dist/` servido por CDN o nginx, con cabeceras de seguridad y caché
  por hash de archivo. Sin Node en producción.
- **Next.js o backend Node**:
  - imagen `-slim` fijada por digest, multi-stage;
  - `output: "standalone"` en Next;
  - sin devDependencies, como usuario `node`;
  - `.dockerignore` con `node_modules`, `.git` y `.env*`;
  - apagado ordenado, con un timeout menor que el grace period del
    orquestador.
- Secretos de build con `--mount=type=secret`, nunca con `ARG` ni `ENV`.

Dockerfiles y ciclo de vida:
[references/docker-and-lifecycle.md](references/docker-and-lifecycle.md).

## 9. Monorepos

En VAAET, el frontend es un proyecto JS dentro de un monorepo Python: un solo
lockfile en su directorio, no en la raíz del repo. Si un día hubiera varios
paquetes JS:
- workspaces de npm con un solo `package-lock.json`, o, si hace falta
  unificar versiones con `catalog:`, pnpm (uno de los casos de §0.2);
- un solo lockfile;
- configuración compartida (tsconfig, ESLint) y contratos;
- nunca un `packages/shared` con lógica de negocio.

## 10. Antipatrones

- **Lockfile y gestor:**
  - lockfile sin versionar o editado a mano, o dos lockfiles;
  - `npm install` o `pnpm install` sin congelar en CI;
  - `packageManager` sin fijar;
  - esperar Corepack en Node ≥ 25;
  - creer que Node 26 trae npm 12;
  - introducir pnpm (u otro gestor) por iniciativa propia en un repo que ya usa
    npm, o al revés: la regla de §0.2 manda seguir con lo que hay;
  - un techo de major en `devEngines.packageManager`.
- **Runtime:** Node EOL o Current en producción, o una versión implícita.
- **Install scripts:**
  - ejecutarlos todos sin allowlist;
  - `--ignore-scripts` global como política, que rompe binarios legítimos;
  - aprobar con `--all` sin revisar;
  - una allowlist sin revisión en los PRs.
- **pnpm 11:** settings en `.npmrc` o en el campo `pnpm` de `package.json`;
  `onlyBuiltDependencies`.
- **Cooldown:** no tenerlo, o un cooldown del bot menor que el del gestor.
- **Fuentes y auditoría:**
  - dependencias Git o URL habilitadas globalmente;
  - `npm audit fix --force` automático;
  - creer que `audit` detecta malware nuevo;
  - overrides sin motivo ni fecha.
- **Dependencias:** paquetes para funciones triviales de la plataforma; zod en
  devDependencies.
- **Imagen:**
  - toolchain en la imagen de producción;
  - imágenes sin digest;
  - `.env` dentro de la imagen;
  - contenedor como root.
- **Entorno:**
  - secretos en `VITE_*` o `NEXT_PUBLIC_*`;
  - valores por entorno horneados en un artefacto que se promueve;
  - `process.env` logueado;
  - `z.string().url()` en Zod 4.
- **Scripts:** `npx` en scripts; `next lint`.
- **Registry:** tokens npm en un `.npmrc` versionado.
- **VAAET:**
  - el frontend que llama a algo que no sea la API HTTP;
  - un `package.json` en `vaaet-app/` sin plan ni ADR;
  - `node_modules` sin ignorar en la raíz.

## 11. Definition of Done

- **Runtime y gestor:** `.node-version` en una LTS soportada; `engines` y
  `devEngines` coherentes; gestor elegido con la regla de §0.2, nombrado en la
  entrega, fijado e instalado explícitamente; un solo lockfile.
- **Supply chain:**
  - allowlist versionada y modo estricto;
  - cooldown alineado con el bot;
  - sin fuentes Git ni URL;
  - `lockfile-lint` y `npm audit signatures` en CI (con pnpm, revisión del
    diff del lock);
  - sin críticas abiertas;
  - ningún token versionado.
- **Calidad:** CI limpio desde un clon nuevo (instalación congelada,
  typecheck, lint, formato, test y build).
- **Entorno:** `.env.example` completo; esquema validado con test; público y
  privado clasificados; ningún secreto en bundles ni imágenes.
- **Producción:** `dist/` estático o imagen mínima, no root, fijada por digest,
  con apagado ordenado.
- **VAAET:** plan y ADR aprobados; sólo la API HTTP; cambios en la raíz
  (`.gitignore`, `ci.yml`) incluidos en el plan.

## 12. Referencias

| Archivo | Cuándo leerlo |
|---|---|
| [references/vaaet-frontend.md](references/vaaet-frontend.md) | Antes de diseñar o revisar el frontend de `vaaet-app` |
| [references/npm.md](references/npm.md) | **Gestor por defecto**: política de npm 12 |
| [references/pnpm.md](references/pnpm.md) | Gestor alternativo, sólo en los casos de §0.2 |
| [references/supply-chain-ci.md](references/supply-chain-ci.md) | CI, `lockfile-lint`, auditoría, Renovate y Dependabot |
| [references/env-and-build.md](references/env-and-build.md) | Esquema de entorno y build contra runtime |
| [references/docker-and-lifecycle.md](references/docker-and-lifecycle.md) | Imágenes, host estático y apagado ordenado |

Fuentes:
- Node.js: calendario de releases, TypeScript (type stripping) y Corepack.
- npm docs v12: `install-scripts`, `approve-scripts`, config, `devEngines`,
  `audit signatures` y trusted publishing; changelog de GitHub sobre npm v12.
- pnpm 11: notas de versión y Settings.
- lockfile-lint, Renovate (`minimumReleaseAge`) y Dependabot (`cooldown`).
- Next.js 16 (ESLint, `output: "standalone"`), Vite (Env Variables) y
  Zod 4 (changelog).
