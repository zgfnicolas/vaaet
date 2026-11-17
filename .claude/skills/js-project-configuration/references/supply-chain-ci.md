# Supply chain, CI y actualizaciones

## Contenido

1. `lockfile-lint` y auditoría
2. Workflow de CI (pnpm)
3. Variante npm 12
4. Renovate y Dependabot
5. Trusted publishing

Agregar un job a `.github/workflows/ci.yml` es un cambio de CI de la raíz: va
en el plan del frontend.

## 1. `lockfile-lint` y auditoría

```json
"scripts": {
  "lint:lockfile": "lockfile-lint --path package-lock.json --type npm --allowed-hosts npm --validate-https --validate-integrity",
  "audit:signatures": "npm audit signatures",
  "audit:deps": "npm audit --omit=dev --audit-level=high"
}
```

- `--allowed-hosts npm` acepta sólo el registry de npm; sumá el host del
  registry privado si existe. `--validate-integrity` exige integrity sha512.
- `lockfile-lint` cubre `package-lock.json`, `npm-shrinkwrap.json` y
  `yarn.lock`. **No** aplica a `pnpm-lock.yaml`: según su propia FAQ, pnpm no
  guarda la URL del tarball en el lock, así que ese vector no existe ahí. Con
  pnpm, el control equivalente es `blockExoticSubdeps` (default en pnpm 11),
  la instalación congelada y la revisión del diff del lock en cada PR.
- `npm audit signatures` verifica las firmas del registry y las attestations
  de provenance de lo instalado con npm. Con pnpm no hay un equivalente
  confirmado: verificá la documentación de tu versión antes de afirmarlo en
  un diseño.
- `audit` detecta advisories conocidos, no malware nuevo. Nunca
  `audit fix --force` automático.

## 2. Workflow de CI (pnpm)

```yaml
# Fragmento para .github/workflows/ci.yml (ilustrativo; requiere plan y ADR)
  web:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults: { run: { working-directory: vaaet-app/web } }
    steps:
      - uses: actions/checkout@<sha>          # vX — acciones fijadas por SHA
        with: { persist-credentials: false }
      - uses: pnpm/action-setup@<sha>         # lee "packageManager"
        with: { package_json_file: vaaet-app/web/package.json }
      - uses: actions/setup-node@<sha>
        with:
          node-version-file: vaaet-app/web/.node-version
          cache: pnpm
          cache-dependency-path: vaaet-app/web/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm run typecheck
      - run: pnpm run lint
      - run: pnpm run format:check
      - run: pnpm run test
      - run: pnpm run check:api-types        # regenera los tipos del OpenAPI y hace git diff --exit-code
      - run: pnpm run build
      - run: pnpm audit --prod --audit-level high
```

- `permissions: { contents: read }` a nivel de workflow, y `concurrency` con
  `cancel-in-progress` en PRs.
- Se cachea la caché de descargas o el store de pnpm, nunca `node_modules`.
- El filtro de rutas del workflow suma `vaaet-app/web/**`, y también los
  archivos del backend que generan el OpenAPI.
- Matriz opcional con la próxima LTS como job no bloqueante.

## 3. Variante npm 12

```yaml
      - uses: actions/setup-node@<sha>
        with: { node-version-file: vaaet-app/web/.node-version, cache: npm, cache-dependency-path: vaaet-app/web/package-lock.json }
      - run: npm install -g npm@12.N.N        # Node 26 trae npm 11.x
      - run: npm ci --strict-allow-scripts    # el .npmrc aplica min-release-age y engine-strict
      - run: npm run lint:lockfile
      - run: npm audit signatures
```

Si `devEngines.packageManager` exige npm 12, el paso `npm install -g` va antes
de cualquier otro comando npm del proyecto.

## 4. Renovate y Dependabot

```json
{
  "extends": ["config:recommended", ":pinAllExceptPeerDependencies"],
  "minimumReleaseAge": "3 days",
  "internalChecksFilter": "strict",
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 6am on monday"] },
  "packageRules": [
    { "matchUpdateTypes": ["patch", "minor"], "matchCurrentVersion": "!/^0/", "groupName": "non-major" },
    { "matchUpdateTypes": ["major"], "automerge": false, "labels": ["major-upgrade"] }
  ],
  "vulnerabilityAlerts": { "minimumReleaseAge": null }
}
```

```yaml
# .github/dependabot.yml (alternativa)
version: 2
updates:
  - package-ecosystem: npm            # también cubre pnpm
    directory: /vaaet-app/web
    schedule: { interval: weekly }
    cooldown: { default-days: 3, semver-major-days: 14 }
    groups:
      non-major: { update-types: [minor, patch] }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 3 }
```

- El cooldown del bot es igual o mayor que el del gestor, para no abrir PRs que
  la instalación va a rechazar.
- Usá Renovate ≥ 44.61.3: las versiones anteriores podían saltear
  `minimumReleaseAge` al pedir un rebase.
- En Dependabot, un grupo con comodines puede saltear el cooldown de cada
  paquete: agrupá por tipo de update.
- Automerge sólo con CI verde completo y nunca en majors. Los diffs de
  `allowScripts` y `allowBuilds` se revisan a mano.

## 5. Trusted publishing

Sólo aplica a librerías publicadas, no al frontend de VAAET.

- `"private": false`, `files` como allowlist, `exports` explícito con
  `types`, y `npm pack --dry-run` en CI para revisar el tarball.
- Publicación desde CI con trusted publishing (OIDC) y provenance; hoy
  funciona en GitHub Actions y GitLab CI/CD, no en runners self-hosted.
- Los granular access tokens que saltean 2FA ya no administran paquetes desde
  julio de 2026, y la publicación directa con ellos se elimina en enero de 2027
  (fecha anunciada: verificala). 2FA obligatorio para los maintainers.
