# Artefactos de producción y ciclo de vida

## Contenido

1. SPA: `dist/` estático
2. Next.js: `output: "standalone"`
3. Backend Node
4. Apagado ordenado

## 1. SPA: `dist/` estático

El artefacto es `dist/`, servido por un CDN o por nginx. No hay Node en
producción.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:26-bookworm-slim@sha256:<digest> AS build
WORKDIR /app
RUN npm install -g pnpm@11.N.N        # Corepack no viene con Node >= 25
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginxinc/nginx-unprivileged:<versión>@sha256:<digest> AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
```

- `nginx.conf`:
  - fallback a `index.html` para el router;
  - caché larga para los archivos con hash y `no-cache` para `index.html` y
    `config.json`;
  - cabeceras de seguridad (CSP, `X-Content-Type-Options`, `Referrer-Policy`).
- `config.json` lo escribe el despliegue (§2 de [env-and-build.md](env-and-build.md)),
  no la imagen.
- Si la ruta de la caché del store de pnpm difiere en tu versión, ajustala
  (`pnpm store path`).

## 2. Next.js: `output: "standalone"`

```dockerfile
# syntax=docker/dockerfile:1
# next.config.ts: { output: "standalone" }
FROM node:26-bookworm-slim@sha256:<digest> AS build
WORKDIR /app
RUN npm install -g npm@12.N.N
COPY package.json package-lock.json .npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --strict-allow-scripts
COPY . .
RUN npm run build

FROM node:26-bookworm-slim@sha256:<digest> AS runtime
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

- El build necesita las devDependencies: se instala todo, se compila y la
  etapa final copia sólo `standalone`.
- `.dockerignore` con `node_modules`, `.git`, `.env*`, `coverage` y `.next`.
- Imágenes `-slim` (glibc) antes que Alpine cuando hay binarios nativos;
  siempre fijadas por digest.
- Secretos de build con `--mount=type=secret`, nunca con `ARG` ni `ENV`.

## 3. Backend Node

```dockerfile
FROM node:26-bookworm-slim@sha256:<digest> AS build
WORKDIR /app
RUN npm install -g npm@12.N.N
COPY package.json package-lock.json .npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --strict-allow-scripts
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:26-bookworm-slim@sha256:<digest> AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
USER node
CMD ["node", "dist/server.js"]
```

No uses `npm ci --omit=dev` en la etapa runtime: se instala una vez, se poda y
se copia.

## 4. Apagado ordenado

```ts
// src/server.ts (extracto)
const SHUTDOWN_TIMEOUT_MS = 10_000;
let shuttingDown = false;

function closeServer(): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()));   // deja de aceptar y espera lo que está en curso
    server.closeIdleConnections();                            // las keep-alive ociosas no bloquean el cierre
  });
}

async function shutdown(reason: string, error?: unknown): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  const force = setTimeout(() => process.exit(1), SHUTDOWN_TIMEOUT_MS);
  force.unref();
  try {
    await closeServer();
    await telemetry.shutdown();
  } catch (err) {
    error ??= err;
  } finally {
    clearTimeout(force);
    process.exit(error ? 1 : 0);
  }
}

process.once("SIGTERM", () => void shutdown("SIGTERM"));
process.once("SIGINT", () => void shutdown("SIGINT"));
process.on("uncaughtException", (err) => void shutdown("uncaughtException", err));
process.on("unhandledRejection", (err) => void shutdown("unhandledRejection", err));
```

- Un error no controlado deja el proceso posiblemente corrupto: terminá y
  dejá que el orquestador reinicie.
- El timeout es menor que el `terminationGracePeriodSeconds` del orquestador.
- El Permission Model de Node (`--permission`, con `--allow-fs-read` y
  similares) es un cinturón de seguridad para el código propio, no un sandbox
  para código malicioso. Se combina con un contenedor no root, FS de sólo
  lectura y red mínima.
