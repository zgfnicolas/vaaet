# Política npm 12

Verificado el 2026-11-16. Node 26 trae npm 11.x: para esta política hay que
instalar npm 12 explícitamente, en local, en CI y en Docker.

## Contenido

1. Runtime y gestor en `package.json`
2. `.npmrc`
3. Allowlist de install scripts
4. Cooldown
5. Fuentes Git y URL
6. Monorepos

## 1. Runtime y gestor en `package.json`

```text
# .node-version — única fuente (setup-node, mise, fnm y Volta la leen)
26.N.N          # versión exacta vigente de la línea 26
```

```json
{
  "private": true,
  "type": "module",
  "packageManager": "npm@12.N.N",
  "engines": { "node": ">=26 <27" },
  "devEngines": {
    "runtime":        { "name": "node", "version": ">=26 <27", "onFail": "error" },
    "packageManager": { "name": "npm",  "version": ">=12",     "onFail": "error" }
  }
}
```

- `devEngines` (npm ≥ 10.9) es el contrato del entorno de desarrollo, y
  `engines`, el de quien instala. Con `engine-strict=true` (§2), un `engines`
  incompatible es un error.
- `devEngines.packageManager` falla con `EBADDEVENGINES` si el npm del entorno
  no cumple. En CI, instalá npm 12 antes de `npm ci`.
- Sin techo de major en el gestor.
- Node 26 ejecuta `.ts` con type stripping estable, y se eliminó
  `--experimental-transform-types`. `enum`, `namespace` y parameter
  properties no funcionan sin compilar, y los decorators no se transforman.

## 2. `.npmrc`

```ini
# .npmrc del proyecto: versionado, sin tokens
save-exact=true              # apps: versiones directas exactas
engine-strict=true           # engines incompatible = error
strict-peer-deps=true        # greenfield; en legacy, migrar de forma progresiva
min-release-age=3            # días; disponible desde npm 11.10
fund=false
# allow-git=none y allow-remote=none ya son el default de npm 12: no los habilites globalmente
```

`strict-allow-scripts` va por línea de comandos en CI (§3), no en el
`.npmrc` del proyecto. En local, un paquete nuevo con scripts fallaría antes
de que alguien lo pueda revisar.

## 3. Allowlist de install scripts

En npm 12, los scripts `preinstall`, `install`, `postinstall` y el rebuild
implícito de node-gyp de las dependencias no corren sin aprobación. Un script
no aprobado se saltea con una advertencia y la instalación sigue.
`strict-allow-scripts` lo convierte en error.

```json
"allowScripts": {
  "esbuild@0.25.N": true,
  "sharp@0.34.N": true,
  "core-js": false
}
```

Este bloque lo genera npm; no lo escribas a mano:

```bash
npm install                                    # npm avisa qué scripts quedaron pendientes
npm approve-scripts --allow-scripts-pending    # sólo lista lo que se bloquearía
npm approve-scripts esbuild sharp              # aprueba después de revisar qué ejecuta cada uno
npm deny-scripts core-js                       # registra la denegación
npm ci --strict-allow-scripts                  # CI: un script no revisado = error
```

- `approve-scripts` y `deny-scripts` son alias de
  `npm install-scripts approve` y `npm install-scripts deny`.
- La aprobación se fija a la versión revisada por defecto. Usá
  `--no-allow-scripts-pin` (aprobación por nombre) sólo para paquetes de alta
  confianza que publican seguido.
- Una denegación sobrevive a un `approve --all` y bloquea la aprobación en
  bloque.
- Para `npx` e instalaciones globales:
  `npm config set allow-scripts=<paquete> --location=user`.
- `--ignore-scripts` global no es una política: rompe binarios nativos
  legítimos. La allowlist es más precisa.

## 4. Cooldown

- `min-release-age=3` hace que una versión publicada hace menos de 3 días no
  sea resoluble. Alinealo con el bot (Renovate o Dependabot con 3 días o más).
- Excepción puntual para un fix de seguridad urgente:
  `npm install <pkg>@<versión> --min-release-age=0`, documentada en el PR con
  el CVE.

## 5. Fuentes Git y URL

- `allow-git=none` y `allow-remote=none` son el default de npm 12. El motivo
  es que una dependencia Git puede traer su propio `.npmrc` y cambiar el
  ejecutable de Git, lo que saltea incluso `--ignore-scripts`.
- Si una excepción es imprescindible, habilitala por paquete y con commit
  fijo, documentada; nunca de forma global.

## 6. Monorepos

`approve-scripts` no entiende de workspaces: revisá la raíz y cada workspace.
Para monorepos con varias apps, pnpm (ver [pnpm.md](pnpm.md)) suele ser mejor
opción.
