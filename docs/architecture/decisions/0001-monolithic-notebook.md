<!-- context: VAAET/docs/architecture/decisions/0001-monolithic-notebook.md — Decisión histórica de notebook monolítico.
Referenciado por AGENTS.md y SAD.md. -->

# ADR-001: Notebook Monolítico sobre Módulos Python

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> Nota de vigencia (2026-08-01): este documento conserva la decisión histórica.
> La adquisición activa usa módulos compartidos según [ADR-0013](0013-on-demand-data-collection-workflow.md).
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

VAAET necesita ser ejecutable en Google Colab sin configuración adicional. Los usuarios objetivo (ingenieros de tráfico, investigadores) no necesariamente tienen experiencia en gestión de paquetes Python, virtualenvs o instalación de módulos locales.

Se evaluaron dos alternativas:
- **Opción A**: Paquete Python con estructura `src/`, `setup.py`, imports entre módulos
- **Opción B**: Notebook único (`vaaet.ipynb`) con todo el código en celdas secuenciales

## Decisión

Se adopta la **Opción B: notebook monolítico**. Todo el código, configuración y lógica de procesamiento reside en `vaaet.ipynb`.

## Razonamiento

1. **Portabilidad en Colab**: Un solo archivo `.ipynb` se abre directamente en Colab sin necesidad de clonar un repositorio o instalar paquetes locales
2. **Reproducibilidad**: Ejecutar las celdas en orden garantiza un estado consistente — no hay dependencias circulares ni módulos faltantes
3. **Inspección de resultados intermedios**: El formato notebook permite ver outputs de cada celda durante el procesamiento
4. **Audiencia**: El público objetivo puede no estar familiarizado con `pip install -e .` o imports relativos

## Consecuencias

### Positivas
- Zero-config para ejecutar en Colab
- Todo el contexto visible en un solo archivo
- Facilita demos y presentaciones de portfolio

### Negativas
- **Testing unitario difícil**: No se pueden importar funciones individuales para test
- **Celdas extensas**: La clase `VAAETHybrid` (~600 líneas) en una sola celda es difícil de navegar
- **Sin reutilización de código**: No se puede importar `VAAETHybrid` desde otro proyecto
- **Merge conflicts**: Los archivos `.ipynb` (JSON) generan conflictos difíciles de resolver en Git

### Deuda técnica aceptada
- El smoke test `test_sistema()` reemplaza a un test suite formal
- La validación end-to-end depende del generador de demos sintéticas
