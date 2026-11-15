# Cómo contribuir — VAAET

Antes de cambiar algo, leé [AGENTS.md](AGENTS.md), el `AGENTS.md` del
componente que vas a tocar y el ADR aplicable del
[índice de ADRs](docs/architecture/decisions/README.md). Las reglas que ningún
cambio puede romper están en las [reglas de negocio](docs/product/business-rules.md).

## Entorno de desarrollo

Requisitos: Python 3.10–3.13 y Git. Desde la raíz del monorepo, instalá los
componentes en este orden (no hay paquete instalable en la raíz):

```bash
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# Bash/Zsh:   source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./vaaet-core[vision,inference,dev]"
python -m pip install -e "./vaaet-persistence[admin,dev]"
python -m pip install -e "./vaaet-ml[training,evaluation,visualization,database,dev]"
python -m pip check
```

Instalá sólo los extras que use tu cambio. Para PostgreSQL local, copiá
`vaaet-ml/.env.example` a un `.env` fuera de Git y completá las credenciales de
cada perfil; la [guía PostgreSQL](docs/operations/postgresql-guide.md) explica
la configuración. GPU, Drive y DVC remoto se prueban en Google Colab según la
[guía de Colab](docs/operations/colab-guide.md).

## Flujo de trabajo

1. Creá una rama `feature/<descripcion>` desde `main`.
2. Escribí commits con Conventional Commits en español rioplatense formal,
   por ejemplo `fix(data): preservá la integridad de sesiones HITL`. La
   plantilla [`.git-commit-template.txt`](.git-commit-template.txt) lista tipos
   y scopes; para usarla localmente:
   `git config commit.template .git-commit-template.txt`.
3. Abrí un PR hacia `main` y completá el template.
4. Se integra con CI en verde y la revisión del responsable técnico.

Los cambios de arquitectura, contratos, seguridad, datos persistidos,
dependencias, permisos o remotos necesitan antes un plan en
[`docs/governance/plans/`](docs/governance/plans/) y el ADR correspondiente.

## Dónde va cada cambio

| Área | Dónde | Reglas y comandos |
|---|---|---|
| Visión, telemetría, features, estados o bundle | `vaaet-core/` | [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md) |
| PostgreSQL, SQL, auditoría o Alembic | `vaaet-persistence/` | [`vaaet-persistence/AGENTS.md`](vaaet-persistence/AGENTS.md) |
| Notebooks, datasets, entrenamiento, evaluación o DVC | `vaaet-ml/` | [`vaaet-ml/AGENTS.md`](vaaet-ml/AGENTS.md) |
| Documentación, CI y configuración compartida | Raíz | Este archivo |

`vaaet-app/` está reservado: no agregues código hasta aprobar su alcance y un
contrato HTTP versionado. No crees repositorios Git ni remotos DVC anidados.

## Estándares de código

- Identificadores, nombres de archivo y código en inglés.
- Comentarios y docstrings propios en español rioplatense formal: forma
  declarativa en contratos y voseo formal en instrucciones operativas. Agregalos
  sólo cuando aclaren una API, un efecto lateral, una invariante, una decisión
  o un algoritmo no evidente.
- Lint con Ruff y tipado con Pyright, configurado en
  [`pyrightconfig.json`](pyrightconfig.json) sobre los directorios `src/`.
- Los notebooks sólo orquestan módulos probados y nunca modifican `sys.path`.

## Tests

Cada `AGENTS.md` de componente tiene sus comandos completos. Un cambio que toca
lógica nueva incluye sus pruebas. Una verificación completa, igual a la del
[CI](.github/workflows/ci.yml), instala los tres componentes y ejecuta
`pip check`, Ruff, Pyright, pytest, `compileall` y la auditoría de notebooks. Las
pruebas marcadas `postgres` requieren una instancia PostgreSQL 17 desechable.

Las pruebas no descargan pesos ni requieren GPU, Drive, DVC remoto, videos
privados o credenciales personales. Lo que sólo se puede validar en Colab se
informa en el PR como pendiente, nunca como aprobado.

## Documentación

En el mismo PR:

- agregá una entrada en la sección «Unreleased» del [CHANGELOG](CHANGELOG.md)
  si cambia un comportamiento observable;
- actualizá el documento de [`docs/`](docs/index.md) afectado si cambia una
  regla, un rol, un contrato o la arquitectura;
- escribí un ADR nuevo con la [plantilla](docs/architecture/decisions/0000-template.md)
  ante una decisión costosa de revertir, y agregalo al índice.

La documentación vigente de `vaaet-ml/` se valida con
`pytest tests/repository`, que comprueba enlaces y afirmaciones obsoletas.

## Seguridad y datos

Nunca incluyas secretos, `.env`, certificados, videos, datasets privados,
calibraciones reales ni binarios ML (`.pt`, `.keras`, `.joblib`). Las
vulnerabilidades se reportan en privado según [SECURITY.md](SECURITY.md).
