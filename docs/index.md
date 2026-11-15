# Documentación de VAAET

Índice de toda la documentación vigente, agrupada por la pregunta que responde.
Cada tema tiene un único documento responsable; los demás lo enlazan.

## Precedencia

1. **Normativo**: ADRs, contratos, reglas de negocio y seguridad. Prevalecen
   sobre cualquier resumen, README o guía.
2. **Operativo**: guías que describen cómo usar lo implementado.
3. **Histórico**: changelog, planes fechados y el [archivo](archive/README.md).
   Registran su momento y no describen el estado vigente.

## Información del repositorio — ¿qué es y cómo lo uso?

- [README](../README.md) · [licencia](../LICENSE) · [cómo contribuir](../CONTRIBUTING.md)
- [Seguridad](../SECURITY.md) · [soporte](../SUPPORT.md)

## Negocio — ¿qué problema resuelve y para quién?

- [Requisitos del producto (PRD)](product/product-requirements.md)
- [Roles y permisos](product/roles.md)
- [Reglas de negocio](product/business-rules.md)

## Técnico — ¿cómo está construido y por qué?

- [Arquitectura de software](architecture/software-architecture.md)
- [Modelo de datos PostgreSQL](architecture/data-model.md)
- [Linaje de datos](architecture/data-lineage.md)
- [Diagramas de arquitectura](architecture/diagrams/index.md)
- [Registro de ADRs](architecture/decisions/README.md)
- [Contrato del bundle](ml/model-artifact-contract.md)
- [Model card y gates de promoción](ml/model-card.md)
- [Sesgos y limitaciones](ml/bias-and-limitations.md)
- [Observabilidad de entrenamiento y ciclo HITL](ml/training-observability.md)
- [Protocolo de anotación humana](ml/human-annotation-protocol.md)

## Operación — ¿cómo lo ejecuto?

- [Guía de usuario](operations/user-guide.md)
- [Guía de Google Colab](operations/colab-guide.md)
- [Configuración de workflows en notebooks](operations/notebook-configuration.md)
- [Guía de calibración multi-vista](operations/multi-view-calibration-guide.md)
- [Operación PostgreSQL](operations/postgresql-guide.md)
- [Guía del registro DVC](ml/dvc-guide.md)
- [Runbook de demo temporal AWS](operations/aws-temporary-demo-runbook.md)

## Calidad — ¿cómo sé que funciona?

- [Plan de pruebas](quality/test-plan.md)
- [KPIs y guía de validación](quality/kpis.md)

## Gestión y gobernanza — ¿cómo se trabaja y hacia dónde va?

- [Roadmap](roadmap.md)
- [CHANGELOG](../CHANGELOG.md)
- [Planes de ejecución gobernados](governance/plans/)
- [Política de seguridad y privacidad](governance/security-policy.md)
- [Registro de licencias de terceros](governance/third-party-licenses.md)
- [Checklist de demo pública AGPL](governance/agpl-demo-release-checklist.md)

## Agentes de IA — ¿qué necesita saber un agente?

- [AGENTS.md](../AGENTS.md): única fuente de instrucciones. `CLAUDE.md` y
  `.github/copilot-instructions.md` sólo apuntan a ella.
- `AGENTS.md` de cada componente: [core](../vaaet-core/AGENTS.md),
  [persistencia](../vaaet-persistence/AGENTS.md) y [ML](../vaaet-ml/AGENTS.md).
- `.codex/skills/`: guías especializadas para Codex.
