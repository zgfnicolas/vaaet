<!-- context: VAAET/docs/architecture/decisions/0003-sort-over-deepsort.md — Decisión de usar SORT.
Referenciado por AGENTS.md, SAD.md §2.1. -->

# ADR-003: SORT sobre DeepSORT/ByteTrack

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> This ADR applies to the archived bootstrap module (`archive/bootstrap-v1/`) only.
> SORT is still used in the production module. See ADR-009 for current architecture.  
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

El sistema requiere asignar IDs persistentes a vehículos detectados entre frames para calcular trayectorias y velocidades. Se necesita un algoritmo de tracking multi-objeto (MOT) que funcione en Colab Free sin GPU dedicada exclusivamente al tracking.

Se evaluaron:
- **SORT** (Simple Online and Realtime Tracking): Kalman filter + Hungarian algorithm
- **DeepSORT**: SORT + red de re-identificación visual (ReID)
- **ByteTrack**: Asociación en dos etapas (detecciones high/low confidence)
- **BoT-SORT**: Fusión de movimiento + apariencia con corrección de cámara

## Decisión

Se adopta **SORT ligero** implementado directamente en `VAAETHybrid._find_or_create_track()` usando matching por distancia euclidiana al centroide más cercano (umbral: 100px) por tipo de vehículo.

## Razonamiento

1. **Mínimo overhead de GPU**: SORT no requiere una red neuronal adicional. DeepSORT necesita un modelo ReID (~128MB) que competiría con YOLO por la GPU de Colab
2. **Simplicidad**: La implementación es ~50 líneas dentro de la clase. No agrega dependencias externas
3. **Suficiente para el caso de uso**: En un puente de 2 carriles, los vehículos se mueven en trayectorias mayormente lineales con pocas oclusiones prolongadas
4. **Velocidad**: El matching por distancia es O(n²) pero con los ~20-50 vehículos típicos en un frame de puente, es instantáneo

## Consecuencias

### Positivas
- Zero dependencias adicionales
- No consume GPU para tracking
- Latencia de matching despreciable
- Fácil de debuggear y ajustar

### Negativas
- **Más ID switches**: Sin ReID visual, si un vehículo es ocluido y reaparece, obtendrá un nuevo ID
- **No resistente a oclusiones >1s**: Si la detección se pierde por varios frames, el track se pierde
- **Matching naive por distancia**: En tráfico denso con vehículos cercanos del mismo tipo, puede haber asignaciones incorrectas
- **Sin predicción de movimiento**: A diferencia de SORT original (Kalman), esta implementación no predice la posición futura

### Deuda técnica aceptada
- El umbral de 100px es estático — debería adaptarse al tamaño del frame
- No hay modelo de velocidad para predecir posición entre detecciones
