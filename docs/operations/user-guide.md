# Guía de usuario

VAAET ML ofrece tres workflows operacionales independientes y un cuarto
notebook de evaluación read-only:

1. [Recolección](../../vaaet-ml/notebooks/data-collection/collect_traffic_telemetry.ipynb): opcional; convierte video en telemetría cruda, CSV acumulativo y video anotado.
2. [Entrenamiento](../../vaaet-ml/notebooks/training/train_traffic_state_classifier.ipynb): transforma telemetría en 19 features y genera el bundle del clasificador.
3. [Inferencia](../../vaaet-ml/notebooks/inference/analyze_traffic_video.ipynb): combina un clip con un bundle validado y devuelve video anotado, telemetría y estado del tráfico.
4. [Evaluación](../../vaaet-ml/notebooks/evaluation/evaluate_models_and_eda.ipynb): compara bundles y cohortes explícitas sin crear `pipeline_run`, persistir ni promover modelos.

Los videos anotados usan por defecto un HUD público en español: estado y velocidad
en la esquina superior izquierda, conteos acumulados en la derecha y la zona central
libre para la circulación. `HUD_DEBUG=True` agrega IDs, confianza, evidencia y calidad
sólo para diagnóstico técnico. Un candidato de incidente se muestra como `POSIBLE
INCIDENTE - REVISAR` y conserva el estado automático `Congested`.

Ejecutá cada notebook de arriba hacia abajo. La única celda de preparación
resuelve `vaaet-core`, `vaaet-persistence` y `vaaet-ml` en ese orden con los extras justos del
workflow; no agregues instalaciones ad hoc. Colección, entrenamiento e
inferencia fallan temprano sin GPU; evaluación continúa read-only. La
persistencia PostgreSQL está deshabilitada por defecto y requiere Secrets de
Colab o variables de entorno.

El nombre recomendado del video es `bridge_YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS.mp4`. Un nombre libre funciona, pero `record_time` se deriva de la hora de procesamiento y tiene menor trazabilidad.

Para runtime GPU, Secrets, Drive, outputs y recuperación ante reinicios consultá la [guía de Google Colab](colab-guide.md). Para restricciones del modelo consultá [sesgos y limitaciones](../ml/bias-and-limitations.md).
