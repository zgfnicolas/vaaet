# Entorno: build y runtime

## Contenido

1. Archivos
2. SPA Vite: configuración en runtime
3. Next.js y backends Node: esquema de entorno
4. Scripts y tsconfig

## 1. Archivos

```text
# .gitignore del frontend (o en la raíz, en el plan de VAAET)
node_modules/
dist/
.next/
out/
coverage/
*.tsbuildinfo
.env
.env.*
!.env.example
```

`.env.example` versionado, con valores ficticios y un comentario por variable
que diga si es pública o privada, de build o de runtime, y si es obligatoria.

## 2. SPA Vite: configuración en runtime

En una SPA todo lo que llega al navegador es público. Para compilar una vez y
desplegar en varios entornos, la configuración que cambia por entorno se sirve
como un archivo del host, no como `VITE_*`.

```ts
// src/config/runtime.ts
import { z } from "zod";

const RuntimeConfig = z.object({
  apiBaseUrl: z.url({ protocol: /^https?$/ }),        // Zod 4: z.url(), no z.string().url()
  environment: z.enum(["development", "staging", "production"]),
});
export type RuntimeConfig = z.infer<typeof RuntimeConfig>;

export function parseRuntimeConfig(raw: unknown): RuntimeConfig {
  const result = RuntimeConfig.safeParse(raw);
  if (!result.success) {
    // nombres de campos y motivo, nunca valores
    const problems = result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new Error(`Invalid runtime config: ${problems}`);
  }
  return result.data;
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`config.json unavailable (${response.status})`);
  return parseRuntimeConfig(await response.json());
}
```

```ts
// src/config/runtime.test.ts
import { expect, it } from "vitest";
import { parseRuntimeConfig } from "./runtime";

it("rejects a non-http api url", () => {
  expect(() => parseRuntimeConfig({ apiBaseUrl: "ftp://x", environment: "production" })).toThrow(/apiBaseUrl/);
});
```

- `VITE_*` queda para valores que **no** cambian por entorno y no son
  secretos (por ejemplo, la versión de la app).
- `/config.json` lo genera el despliegue desde variables del entorno. Nunca
  lleva secretos, porque el navegador lo descarga.

## 3. Next.js y backends Node: esquema de entorno

```ts
// src/config/env.ts (código de servidor)
import { z } from "zod";

const EnvSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]),
  PORT: z.coerce.number().int().min(1).max(65_535).default(3000),
  API_BASE_URL: z.url({ protocol: /^https?$/ }),           // privada: sólo la lee el servidor
  LOG_LEVEL: z.enum(["trace", "debug", "info", "warn", "error", "fatal"]).default("info"),
});
export type Env = z.infer<typeof EnvSchema>;

export function parseEnv(source: Record<string, string | undefined>): Env {
  const result = EnvSchema.safeParse(source);
  if (!result.success) {
    const problems = result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new Error(`Invalid configuration: ${problems}`);
  }
  return result.data;
}

export const env = parseEnv(process.env);
```

- En Next.js, `NEXT_PUBLIC_*` se hornea en `next build`. Un valor que cambia
  por entorno se lee en el servidor, en una ruta dinámica, y se pasa como prop
  al componente cliente.
- En desarrollo, `node --env-file-if-exists=.env` (sin `dotenv`). En
  producción, las variables las inyecta la plataforma, y no hay `.env` dentro
  de la imagen.
- Logueá un resumen (entorno, puerto, nivel), nunca `process.env`.

## 4. Scripts y tsconfig

```jsonc
// SPA Vite
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview",
  "typecheck": "tsc -b --noEmit",
  "lint": "eslint . --max-warnings=0",
  "format:check": "prettier --check .",
  "test": "vitest run",
  "check:api-types": "openapi-typescript ../openapi.json -o src/api/schema.d.ts && git diff --exit-code src/api/schema.d.ts",
  "lint:lockfile": "lockfile-lint --path package-lock.json --type npm --allowed-hosts npm --validate-https --validate-integrity",
  "check": "npm run typecheck && npm run lint && npm run format:check && npm test"
}
```

```jsonc
// Next.js 16: next lint ya no existe; ESLint directo con flat config (eslint.config.mjs)
"scripts": { "dev": "next dev", "build": "next build", "start": "next start", "typecheck": "tsc --noEmit", "lint": "eslint . --max-warnings=0", "test": "vitest run" }
```

- Vite: `moduleResolution: "bundler"`. Backend Node: `module: "nodenext"`.
  Next: partí de `create-next-app` y endurecé los flags (`strict`,
  `noUncheckedIndexedAccess`).
- La ruta del OpenAPI (`../openapi.json`) es ilustrativa: la define el plan.
- Biome es una alternativa válida a ESLint + Prettier en un solo binario.
