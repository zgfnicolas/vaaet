<!-- context: VAAET/docs/architecture/decisions/0004-mlp-speed-smoother.md — MLP como suavizador.
Referenciado por AGENTS.md, SAD.md §2.2, BIAS_AND_LIMITATIONS.md. -->

# ADR-004: MLP como Suavizador (No Estimador Primario)

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> This ADR applies to the archived bootstrap module (`archive/bootstrap-v1/`) only.
> The speed-smoothing MLP is part of the perception pipeline. See ADR-009.  
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

La estimación de velocidad basada puramente en desplazamiento de píxeles + conversión a metros es ruidosa debido a: errores de tracking, variaciones en la perspectiva, movimiento de cámara y cambios de zoom. Se necesita un mecanismo de suavizado que reduzca outliers sin requerir datos de ground truth (que no están disponibles).

Se evaluaron:
- **Filtro de Kalman**: Predicción basada en modelo de movimiento
- **Media móvil ponderada**: Suavizado temporal simple
- **MLPRegressor (scikit-learn)**: Red neuronal simple como regresor de velocidad
- **CNN real entrenada**: Red convolucional con datos de entrenamiento reales

## Decisión

Se adopta un **MLPRegressor de scikit-learn** (`hidden_layer_sizes=(64, 32)`) como componente de suavizado en una fusión ponderada: **70% estimación física + 30% predicción MLP**. El MLP se inicializa con datos aleatorios como scaffold.

```python
# Inicialización (Cell 3)
self.cnn_validator = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=200)
X_dummy = np.random.rand(100, 10)       # 10 features aleatorias
y_dummy = np.random.rand(100) * 80 + 20 # velocidades 20-100 km/h
self.cnn_validator.fit(X_dummy, y_dummy)

# Uso en calculate_enhanced_speed()
velocidad_final = 0.7 * velocidad_fisica + 0.3 * prediccion_mlp
```

## Razonamiento

1. **No hay ground truth**: No existen datos etiquetados de velocidad real para el Puente Belgrano. Una CNN entrenada sería igualmente inválida sin datos reales
2. **El 70/30 limita el impacto**: Incluso si el MLP produce valores incorrectos, su contribución está acotada al 30% del resultado final. El rango aceptable del MLP se filtra a [5, 100] km/h
3. **Efecto regularizador**: El MLP entrenado con datos random actúa como un regresor hacia la media (~60 km/h), lo que suaviza outliers extremos del cálculo físico
4. **Placeholder para mejora futura**: La arquitectura permite reentrenar el MLP con datos reales cuando estén disponibles, sin cambiar la interfaz

## Consecuencias

### Positivas
- No requiere datos de entrenamiento reales
- Efecto de suavizado measurable en velocidades ruidosas
- Arquitectura extensible: swap por modelo real cuando haya datos
- Zero dependencias adicionales (scikit-learn ya se usa)

### Negativas
- **Nombre misleading**: En el código se llama `cnn_validator` pero es un MLP, no una CNN. Los docs que dicen "CNN" son incorrectos
- **No mejora precisión real**: El entrenamiento con datos random no aporta aprendizaje real
- **Reproducibilidad**: `np.random.rand()` sin seed fijo produce diferentes modelos en cada ejecución
- **El 30% puede empeorar estimaciones correctas**: Si el cálculo físico es preciso, el MLP introduce ruido innecesario

### Deuda técnica aceptada
- Renombrar `cnn_validator` → `mlp_speed_smoother` (pendiente)
- Agregar seed fijo para reproducibilidad (pendiente)
- El MLP no tiene validación cruzada ni evaluación de rendimiento
