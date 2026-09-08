# Checklist de publicación: demo pública AGPL-3.0

Este checklist se completa para cada demostración web que ejecute
`vaaet-core[vision]`. Es un gate operativo de ADR-0022, no asesoramiento legal
ni autorización para publicar activos de terceros.

## 1. Identidad de la demo

- [ ] Nombre, responsable, fecha y ventana de demostración registrados.
- [ ] Commit inmutable y tag público registrados; el árbol está limpio.
- [ ] La web muestra un enlace visible al código fuente del tag y a
      `AGPL-3.0-only`, junto con la atribución a Ultralytics.
- [ ] El repositorio público contiene instrucciones reproducibles de instalación,
      ejecución, configuración sin secretos y pruebas.

## 2. Código y dependencias

- [ ] La API, worker, frontend, scripts de build y configuración de despliegue
      correspondientes están disponibles en el repositorio público.
- [ ] El worker instala sólo `vaaet-core` y ejecuta
      `vaaet.artifacts.validate_manifest()` antes de deserializar un bundle; la
      web consume exclusivamente HTTP versionado.
- [ ] `vaaet-ml`, DVC, Drive, PostgreSQL y paths de artefactos no se exponen a
      la web ni se incorporan al runtime de serving.
- [ ] La versión de `ultralytics-opencv-headless`, su licencia upstream y su
      atribución están registradas en el release.

## 3. Inventario de activos

Completá una fila por activo efectivo de la demo antes de habilitarla. Un estado
`pendiente`, una procedencia desconocida o la falta de permiso bloquean el
despliegue.

| Activo | Versión/checksum | Procedencia y licencia | Redistribuible | Estado |
| --- | --- | --- | --- | --- |
| Dependencia YOLO | Pendiente | Ultralytics, AGPL-3.0/Enterprise | Según upstream | Pendiente |
| Peso YOLO base | Pendiente | URL y términos upstream | Verificar antes de publicar | Pendiente |
| Peso YOLO ajustado | N/A si no existe | Dataset, entrenamiento y licencia | Requiere revisión explícita | N/A |
| Bundle v3 MLP | Pendiente | Manifiesto, checksum y lineage | Requiere revisión explícita | Pendiente |
| Video de muestra | Pendiente | Sintético, redaccionado o con permiso | Requiere revisión explícita | Pendiente |
| Dataset de entrenamiento | N/A salvo que sea necesario y redistribuible | Propietario y licencia | No publicar por defecto | N/A |

No adjuntes en Git videos SISE, datos HITL, secretos, credenciales, DSN,
remotos DVC ni evidencia comercial. Un activo aprobado se referencia mediante
su identificador público, checksum y ubicación autorizada; no mediante una ruta
privada.

## 4. Validación previa

- [ ] Ruff, pruebas, compileall, auditoría de notebooks, enlaces y
      `git diff --check` correctos para el tag.
- [ ] El código público reconstruye el runtime de demo sin secretos y el worker
      rechaza un bundle cuyo manifiesto no sea válido.
- [ ] La interfaz ofrece los avisos legales, enlace a fuente y enlace a licencia
      antes de que un usuario envíe un video.
- [ ] El [runbook AWS temporal](../operations/aws-temporary-demo-runbook.md)
      está completado y su limpieza tiene responsable y hora límite.

## 5. Cierre

- [ ] Recursos AWS, objetos temporales, credenciales efímeras y logs de demo
      eliminados o rotados según el runbook.
- [ ] Se registró sólo evidencia no sensible: tag, fecha, estado de limpieza y
      resultado de los gates.
