---
paths:
  - "vaaet-core/src/vaaet/vision/**"
  - "vaaet-core/src/vaaet/inference/**"
---

# Visión e inferencia del core

- La visión es Pipe-and-Filter síncrono y ordenado; no agregues colas, threads
  ni procesos sin mediciones comparables en Colab y aprobación.
- `cv2` y Ultralytics sólo se importan dentro de `vaaet/vision/`.
  `vaaet.inference` y los contratos compartidos (`vaaet/contracts.py`) deben
  importarse con el extra `inference` solo; `test_core_isolation.py` lo
  verifica.
