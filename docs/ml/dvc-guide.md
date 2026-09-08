# Registro DVC de bundles VAAET

DVC versiona el bundle promocionable completo sin guardar binarios pesados en
Git. El registro es portable: Google Drive, AWS S3 y Cloudflare R2 son sólo
proveedores de cache; Git y el manifiesto v3 mantienen la identidad y el
contrato del modelo.

## Reglas

- DVC gobierna únicamente `vaaet-ml/artifacts/traffic-state/` como unidad
  atómica: Keras, scaler, mapping y `model-manifest.json`.
- Un commit o tag Git identifica la versión recuperable. `model_version` se
  muestra como metadato y puede repetirse; `current.json` no participa en este
  registro.
- `.dvc/config` es neutral y se versiona. `.dvc/config.local` contiene el
  remoto lógico `vaaet-registry`, destinos, perfiles y rutas privadas; nunca se
  commitea ni se imprime.
- No hay fallback automático, `gc` automático ni sincronización desde notebooks.
  El core recibe un directorio local y valida su manifiesto antes de deserializar.

## Instalación y configuración

Desde la raíz, instalá core y sólo el plugin del proveedor elegido:

```powershell
python -m pip install -e "./vaaet-core"
python -m pip install -e "./vaaet-ml[dvc,dvc-gdrive]"

vaaet-registry configure gdrive --url "gdrive://<folder-id>"
vaaet-registry doctor
```

Usá un ID de carpeta compartida de Drive, no `gdrive://root`. El primer acceso
real abre OAuth; una cuenta de servicio opcional se declara con una ruta privada
fuera del workspace mediante `--service-account-file`.

Para AWS S3:

```powershell
python -m pip install -e "./vaaet-ml[dvc,dvc-s3]"
vaaet-registry configure s3 --url "s3://<bucket>/vaaet-registry" --profile vaaet --region us-east-1
vaaet-registry doctor
```

Las credenciales se resuelven desde el perfil o las variables estándar de AWS;
la CLI nunca acepta access keys. El principal requiere sólo listar, leer,
escribir y eliminar objetos del prefijo del registro.

Para Cloudflare R2:

```powershell
python -m pip install -e "./vaaet-ml[dvc,dvc-s3]"
vaaet-registry configure r2 --url "s3://<bucket>/vaaet-registry" --endpoint-url "https://<account-id>.r2.cloudflarestorage.com"
vaaet-registry doctor
```

R2 usa credenciales S3 de alcance mínimo y mantiene el bucket privado. No uses
URLs presignadas, tokens ni claves en comandos, Git o documentación.

## Guardar, ver y recuperar versiones

Después de exportar y validar los cuatro archivos del bundle:

```powershell
vaaet-registry stage
git add vaaet-ml/artifacts/traffic-state.dvc .gitignore
git commit -m "feat(models): registrá bundle mlp-vX.Y"
git tag model/mlp-vX.Y
vaaet-registry push
```

`stage` no hace commit y `push` rechaza un puntero no consolidado en `HEAD`.
Revisá `git status` antes de commitear y usá un tag inmutable para cualquier
versión que quieras recuperar o comparar.

```powershell
vaaet-registry list
vaaet-registry list --format json
vaaet-registry list --model-version mlp-vX.Y
vaaet-registry get --revision model/mlp-vX.Y --out ..\bundles\mlp-vX.Y
```

`list` materializa cada candidata en un temporal acotado y sólo lee manifiestos
válidos. Su JSON incluye revisión, versión, lifecycle, elegibilidad,
procedencia, input lock y bloqueos de promoción. `get` falla si el destino existe
o apunta al bundle activo, y sólo deja el directorio final después de validar
checksums y contrato v3. Las entradas con el algoritmo de identidad anterior
se muestran como `sólo-histórico` y no pueden materializarse con el propósito
operacional predeterminado. Para una comparación offline explícita:

```powershell
vaaet-registry get --revision <commit-o-tag> --out ..\bundles\historico --historical-evaluation
```

Ese flag no habilita inferencia operacional, persistencia, HITL ni promoción.
Si se decide adoptar el artefacto, se reexporta a otro destino con un motivo y
se vuelve a evaluar; nunca se reescribe la revisión DVC anterior.

## Migrar de proveedor

La migración es manual y requiere detener publicaciones. Configurá un remoto
local temporal, replicá todas las revisiones y comprobá al menos cada tag que
deba conservarse antes de reemplazar `vaaet-registry`:

```powershell
dvc remote add --local vaaet-migration-target "s3://<bucket-destino>/vaaet-registry"
dvc remote modify --local vaaet-migration-target endpointurl "https://<account-id>.r2.cloudflarestorage.com"
dvc push --all-commits -r vaaet-migration-target
dvc get . vaaet-ml/artifacts/traffic-state --rev model/mlp-vX.Y --remote vaaet-migration-target --out ..\bundles\verification
```

Validá el manifiesto del directorio recuperado y sus checksums. Sólo entonces
ejecutá `vaaet-registry configure ... --replace` para el nuevo proveedor y
eliminá el remoto temporal de `.dvc/config.local`. No ejecutes `dvc gc` hasta
cerrar la verificación y mantener un respaldo independiente.

Referencias: [contrato del bundle](model-artifact-contract.md),
[ADR-0023](../architecture/decisions/0023-provider-neutral-dvc-registry.md),
[ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md),
[ADR-0027](../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md),
[DVC Remote Storage](https://doc.dvc.org/user-guide/data-management/remote-storage)
y [DVC S3-compatible](https://doc.dvc.org/user-guide/data-management/remote-storage/amazon-s3).
