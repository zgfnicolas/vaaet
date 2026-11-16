<!-- context: VAAET/docs/architecture/decisions/0006-conservative-stationary-detection.md — Detección conservadora.
Referenciado por AGENTS.md, SAD.md §2.3. -->

# ADR-006: Detección de Estacionarios Ultra-Conservadora (AND-Conjunction)

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> This ADR applies to the archived bootstrap module (`archive/bootstrap-v1/`) only.
> Stationary detection logic is preserved in `src/perception/speed.py`. See ADR-009.  
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

Un problema histórico en sistemas de análisis de tráfico del Puente Belgrano es la contaminación de la velocidad promedio por vehículos estacionados (detenidos por congestión, accidentes, etc.). Si un vehículo parado se incluye con velocidad ~0 km/h, el promedio del flujo baja artificialmente.

Sin embargo, existe un riesgo opuesto: clasificar erróneamente tráfico lento (20-30 km/h en hora pico) como "estacionado" y excluirlo del cómputo, inflando artificialmente la velocidad promedio.

Se evaluaron:
- **Umbral simple de velocidad**: Si velocidad < X km/h → estacionado
- **Clasificador ML**: Entrenar un modelo con features de trayectoria
- **Análisis estadístico multi-criterio con AND**: Múltiples condiciones simultáneas

## Decisión

Se adopta un **clasificador estadístico ultra-conservador** que requiere que **TODAS** las siguientes condiciones se cumplan simultáneamente (AND-conjunction) para declarar un vehículo como estacionado:

1. Historial de trayectoria ≥ 200 frames (~6.5 segundos a 30fps)
2. Desplazamiento total < 5 píxeles
3. Movimiento por segmento < 3 píxeles
4. Desviación estándar de posición < 2.5 píxeles
5. Distancia promedio inter-frame < 0.3 píxeles
6. Distancia máxima inter-frame < 1.5 píxeles

## Razonamiento

1. **Precisión sobre recall**: Es preferible no detectar algunos vehículos estacionados (FN) que clasificar tráfico lento como parado (FP). Los FP contaminarían la velocidad promedio más gravemente
2. **AND-conjunction**: Cada criterio por separado podría activarse por ruido (tracking jitter, movimiento de cámara compensado imperfectamente). La conjunción de todos elimina falsos positivos
3. **Ventana temporal larga (200 frames)**: Evita decisiones prematuras. Un vehículo que frena brevemente en un semáforo no acumula 200 frames de inmovilidad
4. **Umbrales en píxeles, no en metros**: Evita dependencia del factor de conversión `pixels_per_meter`, que puede ser impreciso

## Consecuencias

### Positivas
- Falsos positivos prácticamente eliminados — tráfico lento nunca se excluye erróneamente
- Robusto ante ruido de tracking y compensación imperfecta de cámara
- No requiere entrenamiento ni datos etiquetados

### Negativas
- **Recall limitado**: Vehículos estacionados con micro-movimientos (ej: vibración del motor, viento) pueden no detectarse
- **Latencia de 6.5s**: Se necesitan ~200 frames antes de poder clasificar — no hay detección inmediata
- **Umbrales fijos**: Los valores (5px, 3px, 2.5px, etc.) no se adaptan a la resolución del video ni al zoom de la cámara

### Deuda técnica aceptada
- Los umbrales no son configurables desde `BRIDGE_CONFIG` — están hardcodeados en `is_stationary()`
- No hay evaluación cuantitativa del recall (porcentaje de estacionados reales detectados)
