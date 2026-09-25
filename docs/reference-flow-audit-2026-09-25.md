# Auditoría breve del flujo de referencia · 25 de septiembre de 2026

**Alcance.** Contraste entre `Texto pegado.txt`, secciones 10–31, el árbol actual, las pruebas locales y la comprobación de producción hasta `2d1f457`. Se distingue la ejecución real de IA y API del módulo de las pruebas visuales locales. No acredita acceso ni publicación en el formulario privado del portal principal de IMC.

## Implementado y conservado

| Requisito | Evidencia actual |
| --- | --- |
| Entrada única, flexible y previa a la ficha | `portal/templates/portal/start.html` y `guest.start` conservan tipo, serie, marca, modelo y descripción en la misma `Machine`; no crean tres expedientes. |
| Primer resultado antes de registro | `portal/guest.py` crea un principal técnico limitado, reutiliza `Machine`/`Asset`/`AnalysisJob`, permite fotos o descripción y reclama atómicamente la misma ficha después de autenticar. `portal/tests/test_guest_drafts.py` cubre límites, expiración, reclamo y reutilización de sesión. |
| Catálogo técnico ampliado | En producción se comprobaron 85 referencias aprobadas activas y 316 especificaciones; la ampliación incorpora excavadoras, compactadores, minicargadores, montacargas, motoniveladoras y plataformas. Los 19 campos técnicos adicionales y los alias documentados conservan la distinción entre referencia de modelo y datos de una unidad. |
| Privacidad de medios y exportación | Los activos de visitante requieren capability; `public_asset` verifica publicación, versión, autorización y exclusión de placa/documento. PDF y ZIP comprueban `publish_machine` y MFA en `portal/views.py`. |
| Acceso real al proveedor y privacidad del borrador | La prueba real en SeeNode terminó con modelo solicitado y respondido `gpt-6-luna`. Reabrir el borrador devolvió 200, otra sesión recibió 403 y la respuesta no ofreció PDF al visitante. No se publicaron esas máquinas de prueba. |
| Revisión local de duplicados | `record_local_duplicate_review` guarda una decisión humana, evidencia, actor, fecha, solicitud y versión en `AuditEvent`; `review_submission(..., "approved")` exige esa decisión exacta. `find_possible_duplicates` sólo se muestra y registra para personal con permiso de ver fichas. Una coincidencia es una señal para revisar, no un bloqueo automático. |
| Ficha y selección de destino | La ficha distingue datos declarados, procedencia, año exacto/rango, precio/valoración, notas privadas y archivos. `set_imc_media_selection` conserva una selección IMC distinta de la selección pública y `build_export_payload` limita a cuatro principales y seis adicionales. |
| Traspaso manual trazable | `IntegrationDelivery`, `prepare_delivery`, `record_manual_review` y `ack_delivery` fijan versión, huella de carga, selección de medios, evidencia y acuse. El código no contiene cliente HTTP hacia IMC. |

## Brechas importantes

| Prioridad | Brecha y evidencia | Acción necesaria |
| --- | --- | --- |
| Alta | El anunciante IMC se registra como texto (`ManualReviewForm.imc_advertiser` y `IntegrationDelivery.manual_metadata`), sin relación autorizada y estable entre `User` local, empresa/vendedor y cuenta IMC. | Definir el contrato de identidad autorizado por IMC y modelar una vinculación explícita y auditable antes de cualquier conector o automatización. No emparejar por correo, nombre o empresa libre. |
| Alta para salida real | Falta evidencia de un recorrido real contra el formulario privado de IMC: sus IDs, obligatorios, roles, estados y reglas de actualización siguen marcados como pendientes en `docs/assisted-field-mapping-2026-09-24.md`. | Ejecutar una prueba autorizada de captura manual con cuenta de prueba y documentar el mapeo comprobado. Hasta entonces, tratar la entrega ZIP y el acuse local como preparación, no como sincronización. |
| Limitación de precisión comprobada | La segunda prueba real con `gpt-6-luna` y tres franjas de placa recuperó ambas medidas de neumáticos, inclinación de mástil, medida «LOAD TIRE TREADWIDTH», fabricante, dirección y serie. Etiquetó `2EC2` como lectura clara donde la revisión de la foto permite considerar `2EC25`; la aplicación no detectó esa ambigüedad. La investigación externa no produjo resultados útiles. | El propietario debe corregir o confirmar el modelo mediante la edición disponible. No se logró identificación exacta ni año o precio con esa foto. La dirección del fabricante no acredita origen ni ubicación de la unidad. La disponibilidad del proveedor no equivale a precisión perfecta; no se añadió un decodificador supuesto ni un cambio de modelo. |
| Resuelto | La administración de usuarios muestra el número de fichas por cuenta y enlaza al listado filtrado por propietario. Las cuentas técnicas de visitante quedan excluidas. | Prueba de tres fichas propias, exclusión de ficha ajena y de cuenta técnica. |

## No clasificado en esta auditoría

La congruencia ya compara datos declarados con lecturas de la máquina: compatible, contradicción o evidencia insuficiente. Exige una comparación real, conserva el corte del análisis y no confunde la placa de un motor con la identidad del equipo. Las correcciones posteriores ocultan el resultado anterior. Pruebas de reglas y de interfaz ejecutadas; no implica una certificación del equipo.

## Estado de la verificación final

La suite completa de cierre pasó **1.049 pruebas y 1.423 subpruebas**, sin fallos. Se omitió una prueba de conversión real de video por falta de FFmpeg/FFprobe. La expectativa anterior de no generar recortes de placa se actualizó, y se comprobó tanto la alternativa de tres franjas como la exclusión de documentos privados y URLs externas. También se verificó que los nuevos campos técnicos leídos por IA sobreviven a la normalización, guardado y proyección de la ficha.

El servicio SeeNode `974953` se comprobó activo en `2d1f457`; el portal principal no se modificó. La prueba visual se realizó localmente porque Brave bloqueó el dominio público con `ERR_BLOCKED_BY_CLIENT`; la comprobación remota fue por la API del módulo y no se presenta como recorrido visual remoto ni publicación en IMC.
