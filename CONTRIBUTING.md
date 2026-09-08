# Guía de contribución — Monorepo VAAET

Leé [AGENTS.md](AGENTS.md), [llms.txt](llms.txt), el
[índice documental](docs/index.md) y el ADR aplicable antes de modificar el
repositorio. ADR-0021 y ADR-0028 definen los límites entre core, persistencia,
ML y app; ADR-0022 aplica a cualquier serving futuro con YOLO.

- Los cambios core se realizan desde `vaaet-core/`; sus reglas y comandos están
  en [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md).
- Los cambios ML se realizan desde `vaaet-ml/`; sus reglas y comandos están en
  [`vaaet-ml/CONTRIBUTING.md`](vaaet-ml/CONTRIBUTING.md).
- Los cambios PostgreSQL compartidos se realizan desde `vaaet-persistence/` y
  siguen [`vaaet-persistence/AGENTS.md`](vaaet-persistence/AGENTS.md).
- La documentación y configuración compartida se mantienen en la raíz.
- No crear repositorios Git o remotos DVC anidados.
- No agregar código a `vaaet-app/` hasta aprobar el contrato HTTP y el alcance
  del componente.

Los cambios arquitectónicos deben actualizar su ADR y el plan gobernado
correspondiente. No incluir secretos, binarios ML ni datos sensibles en Git.

## Idioma del código

Escribí identificadores, nombres de archivos y código en inglés. Usá español
rioplatense formal para comentarios y docstrings propios: forma declarativa en
contratos y voseo formal en instrucciones operativas. Agregá documentación sólo
cuando aclare una API, un efecto lateral, una invariante, una decisión o un
algoritmo no evidente; evitá comentarios que repitan el código.

## Calidad local

El tipado estático se configura desde [`pyrightconfig.json`](pyrightconfig.json)
con alcance sobre los directorios `src/`. Instalá los extras `dev`
del componente que modifiques y los extras operativos requeridos por su
workflow. Una verificación completa instala core, persistencia y ML en ese
orden, y ejecuta `pip check`, Ruff, Pyright, pruebas, compilación y auditoría de
notebooks.
