# Política pnpm 11

Verificado el 2026-11-16. pnpm 11.0 salió el 28 de abril de 2026 y requiere
Node ≥ 22.

## Contenido

1. Dónde va la configuración
2. `pnpm-workspace.yaml`
3. Builds aprobados
4. Cooldown y excepciones
5. Catalogs y overrides
6. Instalación de pnpm

## 1. Dónde va la configuración

- **`pnpm-workspace.yaml`**: toda la configuración del proyecto. En pnpm 11,
  incluso en un proyecto de un solo paquete.
- **`.npmrc`**: sólo registry y autenticación. pnpm 11 ignora ahí cualquier
  otra setting.
- El campo `pnpm` de `package.json` ya no se lee. `packageConfigs` reemplaza
  los `.npmrc` por proyecto.

```ini
# .npmrc — en pnpm 11, SOLO registry y auth; el token llega por variable de CI
@acme:registry=https://npm.example.internal/
//npm.example.internal/:_authToken=${NPM_TOKEN}
```

## 2. `pnpm-workspace.yaml`

```yaml
# vaaet-app/web/pnpm-workspace.yaml
packages:
  - "."                        # un solo paquete; en un monorepo JS, apps/* y packages/*

savePrefix: ""                 # versiones exactas en apps
engineStrict: true
strictPeerDependencies: true

# Supply chain
minimumReleaseAge: 4320        # minutos (3 días); el default de pnpm 11 es 1440
minimumReleaseAgeExclude:
  - "@acme/*"                  # sólo paquetes publicados por nosotros
blockExoticSubdeps: true       # default de pnpm 11: transitivas sólo desde registries
allowBuilds:
  esbuild: true
  "@swc/core": true
  core-js: false
```

## 3. Builds aprobados

- `allowBuilds` reemplaza a `onlyBuiltDependencies`, `neverBuiltDependencies`,
  `ignoredBuiltDependencies` e `ignoreDepScripts`. Si migrás desde pnpm 10,
  pasá esas entradas al mapa nuevo.
- `pnpm approve-builds` (interactivo, en local) deja el resultado en
  `allowBuilds`. El diff se revisa en el PR como el lockfile.
- Verificá en la documentación de tu versión si un build no aprobado es error
  o advertencia (`strictDepBuilds`), y activá el modo estricto en CI.

## 4. Cooldown y excepciones

- `minimumReleaseAge` va en minutos. pnpm 11 trae 1440 (un día) por defecto;
  para alinear con un bot de 3 días, usá 4320.
- `pnpm audit --fix` agrega la versión parcheada a `minimumReleaseAgeExclude`
  para no esperar el cooldown en un fix de seguridad. Revisá ese diff y
  retirá la excepción cuando la versión cumpla el plazo.

## 5. Catalogs y overrides

```yaml
# Una versión por dependencia en todo el workspace
catalog:
  react: 19.N.N
  react-dom: 19.N.N
  zod: 4.N.N
  typescript: 6.N.N

overrides:
  # CVE-2026-XXXX en una transitiva de foo; quitar cuando foo >= 3.2 lo actualice (abierto el 2026-11-10, @owner)
  "vulnerable-lib": 2.4.7
```

```json
"dependencies": { "react": "catalog:", "zod": "catalog:", "@acme/contracts": "workspace:*" }
```

Los comentarios de YAML permiten documentar cada override en el mismo lugar.

## 6. Instalación de pnpm

```json
{ "packageManager": "pnpm@11.N.N", "devEngines": { "packageManager": { "name": "pnpm", "version": ">=11", "onFail": "error" } } }
```

- Corepack no viene con Node ≥ 25. En CI, `pnpm/action-setup` lee la versión
  de `packageManager`. En local, mise, Volta o el instalador oficial.
- `pnpm install --frozen-lockfile` en CI y Docker.
