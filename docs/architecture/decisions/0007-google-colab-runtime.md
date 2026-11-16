<!-- context: VAAET/docs/architecture/decisions/0007-google-colab-runtime.md — Google Colab como runtime.
Referenciado por AGENTS.md, PRD.md, ADR-001. -->

# ADR-007: Google Colab como Entorno de Ejecución Principal

**Estado:** Reemplazada por [ADR-0009](0009-modular-three-stage-architecture.md)
> Google Colab remains the primary runtime for all notebooks.
> See ADR-009 for the current three-module architecture.  
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

VAAET requiere GPU para inferencia con YOLO 11 en tiempo razonable. El proyecto es educativo/portfolio y no cuenta con presupuesto para infraestructura dedicada de GPU. Se necesita un entorno que permita:
- Acceso a GPU sin costo
- Ejecución sin instalación local
- Compartir resultados fácilmente

Se evaluaron:
- **Google Colab Free/Pro**: Jupyter en la nube con GPU gratuita
- **Servidor local con GPU**: Máquina propia o institucional
- **AWS EC2 con GPU (p3/g4)**: Instancias de GPU en la nube
- **Kaggle Notebooks**: Alternativa a Colab con GPU
- **Lightning.ai**: Plataforma ML con GPU gratuita

## Decisión

Se adopta **Google Colab** como entorno de ejecución principal, con soporte secundario para ejecución local con Python 3.8+.

## Razonamiento

1. **GPU gratuita**: Colab Free ofrece T4 (16GB VRAM) sin costo, suficiente para YOLO 11 incluso en variante X
2. **Zero config**: Abrir un `.ipynb` en Colab y ejecutar — no hay Docker, no hay setup de CUDA, no hay instalación local
3. **Portabilidad**: Cualquier persona con cuenta Google puede ejecutar VAAET sin instalar nada
4. **Ideal para demos**: El formato notebook permite presentaciones interactivas de portfolio
5. **Conectividad a RDS**: Colab tiene acceso a internet, permite conectar a AWS RDS directamente

## Consecuencias

### Positivas
- Acceso a GPU sin costo ni infraestructura propia
- Reproducibilidad perfecta — mismo entorno para todos los usuarios
- No requiere CI/CD — el "deploy" es compartir el link del notebook
- Auto-descarga de modelos YOLO en el runtime

### Negativas
- **Sin CI/CD clásico**: No hay pipeline de build/test automatizado
- **Sesiones efímeras**: Máximo ~12h (Free) o ~24h (Pro). Se pierde estado al desconectar
- **GPU no garantizada**: En horas pico, Colab Free puede no asignar GPU
- **Almacenamiento efímero**: Archivos locales se pierden — requiere AWS RDS para persistencia (ver ADR-005). Los artefactos del modelo (~100 KB: `.keras` + `.joblib`) se copian a Google Drive al final de M1 y se cargan automáticamente en M2 via un fallback de 3 niveles (local → Drive → upload manual)
- **Sin ejecución programática**: No se puede triggear procesamiento via API o cron
- **Dependencia de Google**: Si Colab cambia su política de Free Tier, el proyecto se ve afectado

### Deuda técnica aceptada
- No hay retry automático si la sesión de Colab se desconecta durante procesamiento
- No hay checkpointing — si el procesamiento se interrumpe, hay que re-procesar desde el inicio
- `optimize_for_colab()` hace heurísticas sobre la GPU disponible que pueden quedar obsoletas
