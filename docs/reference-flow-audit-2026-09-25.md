# Auditoría breve del flujo de referencia · 25 de septiembre de 2026

**Alcance.** Contraste estático entre `Texto pegado.txt`, secciones 10–31, y el árbol actual. No acredita acceso al formulario privado de IMC, ejecución real de IA ni estado de un entorno remoto.

## Implementado y conservado

| Requisito | Evidencia actual |
| --- | --- |
| Entrada única, flexible y previa a la ficha | `portal/templates/portal/start.html` y `guest.start` conservan tipo, serie, marca, modelo y descripción en la misma `Machine`; no crean tres expedientes. |
| Primer resultado antes de registro | `portal/guest.py` crea un principal técnico limitado, reutiliza `Machine`/`Asset`/`AnalysisJob`, permite fotos o descripción y reclama atómicamente la misma ficha después de autenticar. `portal/tests/test_guest_drafts.py` cubre límites, expiración, reclamo y reutilización de sesión. |
| Privacidad de medios y exportación | Los activos de visitante requieren capability; `public_asset` verifica publicación, versión, autorización y exclusión de placa/documento. PDF y ZIP comprueban `publish_machine` y MFA en `portal/views.py`. |
| Revisión local de duplicados | `record_local_duplicate_review` guarda una decisión humana, evidencia, actor, fecha, solicitud y versión en `AuditEvent`; `review_submission(..., "approved")` exige esa decisión exacta. `find_possible_duplicates` sólo se muestra y registra para personal con permiso de ver fichas. Una coincidencia es una señal para revisar, no un bloqueo automático. |
| Ficha y selección de destino | La ficha distingue datos declarados, procedencia, año exacto/rango, precio/valoración, notas privadas y archivos. `set_imc_media_selection` conserva una selección IMC distinta de la selección pública y `build_export_payload` limita a cuatro principales y seis adicionales. |
| Traspaso manual trazable | `IntegrationDelivery`, `prepare_delivery`, `record_manual_review` y `ack_delivery` fijan versión, huella de carga, selección de medios, evidencia y acuse. El código no contiene cliente HTTP hacia IMC. |

## Brechas importantes

| Prioridad | Brecha y evidencia | Acción necesaria |
| --- | --- | --- |
| Alta | El anunciante IMC se registra como texto (`ManualReviewForm.imc_advertiser` y `IntegrationDelivery.manual_metadata`), sin relación autorizada y estable entre `User` local, empresa/vendedor y cuenta IMC. | Definir el contrato de identidad autorizado por IMC y modelar una vinculación explícita y auditable antes de cualquier conector o automatización. No emparejar por correo, nombre o empresa libre. |
| Alta para salida real | Falta evidencia de un recorrido real contra el formulario privado de IMC: sus IDs, obligatorios, roles, estados y reglas de actualización siguen marcados como pendientes en `docs/assisted-field-mapping-2026-09-24.md`. | Ejecutar una prueba autorizada de captura manual con cuenta de prueba y documentar el mapeo comprobado. Hasta entonces, tratar la entrega ZIP y el acuse local como preparación, no como sincronización. |
| Alta para habilitar IA | La política y pruebas locales fijan `gpt-6-luna` (`portal/ai_model.py`, `portal/tests/test_ai_model_policy.py`), pero no hay evidencia aquí de credenciales reales, disponibilidad del modelo, presupuesto ni una llamada de extremo a extremo. | Antes de habilitar IA para visitantes, confirmar en el entorno destino la configuración, worker y límites con una máquina autorizada; conservar el camino manual si falla. |
| Resuelto | La administración de usuarios muestra el número de fichas por cuenta y enlaza al listado filtrado por propietario. Las cuentas técnicas de visitante quedan excluidas. | Prueba de tres fichas propias, exclusión de ficha ajena y de cuenta técnica. |

## No clasificado en esta auditoría

La congruencia ya compara datos declarados con lecturas de la máquina: compatible, contradicción o evidencia insuficiente. Exige una comparación real, conserva el corte del análisis y no confunde la placa de un motor con la identidad del equipo. Las correcciones posteriores ocultan el resultado anterior. Pruebas de reglas y de interfaz ejecutadas; no implica una certificación del equipo.
