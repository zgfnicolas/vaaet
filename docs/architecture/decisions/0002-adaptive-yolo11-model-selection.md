<!-- context: VAAET/docs/architecture/decisions/0002-adaptive-yolo11-model-selection.md — Selección adaptativa de YOLO 11.
Referenciado por AGENTS.md, SAD.md §2.1, PRD.md. -->

# ADR-002: YOLO 11 con Selección Adaptativa por Duración

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> This ADR applies to the archived bootstrap module (`archive/bootstrap-v1/`) only.
> YOLO 11 is still used in the production module. See ADR-009 for current architecture.  
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

El sistema necesita un modelo de detección de objetos capaz de clasificar vehículos (car, truck, bus, motorcycle, bicycle) en video de cámaras de vigilancia. Los videos pueden variar desde minutos hasta más de 12 horas, y el entorno de ejecución (Colab Free) tiene recursos limitados (GPU T4 con 15GB VRAM, sesiones de máximo 12h).

Se evaluaron:
- **YOLO 11** (Ultralytics): 5 variantes de tamaño (n/s/m/l/x)
- **YOLOv9**: Última versión estable previa
- **RT-DETR**: Detector transformer de tiempo real
- **Detectron2**: Framework de Meta para detección

## Decisión

Se adopta **YOLO 11 con selección automática de variante según duración del video**:

| Duración | Modelo | Justificación |
|---|---|---|
| < 1h | yolo11x.pt | Máxima precisión, tiempo de procesamiento aceptable |
| 1-3h | yolo11l.pt | Buen balance precisión/velocidad |
| 3-6h | yolo11m.pt | Modelo medio para videos largos |
| 6-12h | yolo11s.pt | Prioriza velocidad para no exceder sesión Colab |
| > 12h | yolo11n.pt | Mínimo consumo para videos muy largos |

## Razonamiento

1. **Familia unificada**: Las 5 variantes comparten arquitectura, lo que permite selección automática sin cambiar código de pre/post-procesamiento
2. **Adaptación a recursos**: Colab Free tiene límite de sesión (~12h) y GPU compartida. Videos largos necesitan modelos más livianos para completar el procesamiento
3. **Pre-entrenamiento en COCO**: Todas las variantes incluyen las 5 clases vehiculares necesarias sin fine-tuning
4. **API de Ultralytics**: Abstrae complejidad de inferencia, NMS y pre-procesamiento en una sola llamada

## Consecuencias

### Positivas
- Selección automática sin intervención del usuario
- Maximiza precisión cuando los recursos lo permiten
- Compatible con GPU y CPU (más lento en CPU)

### Negativas
- **Dependencia de Ultralytics**: Si la API cambia, hay que actualizar código
- **Modelos pesados**: yolo11x.pt > 100MB — se descarga en runtime, no se versiona en Git
- **Sin fine-tuning**: Dependemos de los pesos pre-entrenados en COCO. Vehículos específicos de Argentina (ej: colectivos) no tienen clase nativa
- **Posible sesgo COCO**: Distribución de clases en COCO puede no representar tráfico argentino

### Deuda técnica aceptada
- La duración se extrae del nombre del archivo, no de los metadatos del video
- No hay fallback si la descarga del modelo falla (solo se reporta error)
