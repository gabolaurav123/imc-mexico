# Preparación administrativa manual para IMC · 25 de septiembre de 2026

## Alcance actual

Seenode prepara una versión aprobada para que un operador la capture en IMC
México. No hay API, SSO, robot, escritura remota ni asignación inventada de
identificadores. Guardar una selección, copiar campos, descargar un ZIP y
aprobar localmente no publica una ficha en IMC.

## Campos y trazabilidad

| Necesidad operativa | Registro local | Regla |
| --- | --- | --- |
| Copiar datos al formulario principal | Bloques de `IntegrationDetail` desde `Machine.approved_version.data` | `price` sólo representa precio solicitado; un rango de año permanece pendiente y no se transforma en año exacto. |
| Observaciones del anunciante | `data.notes` | Se muestra de forma privada y queda fuera de la descripción pública y del ZIP de publicación. |
| Anunciante real de IMC y duplicados | `IntegrationDelivery.manual_metadata.events` | Cada revisión guarda actor local, fecha, evidencia, alcance, límite de búsqueda y resultado. «Parcial» y «no revisado» no significan ausencia de duplicados. |
| Captura comprobada | Acuse inmutable de `IntegrationDelivery` y `Publication` | Después de la captura se registran operador, fecha, usuario/anunciante IMC, `remote_id`, referencia y URL HTTPS reales. |
| Cambio posterior | Versión aprobada y entrega actual | Si versión o disponibilidad no coincide con el último acuse, la vista marca actualización pendiente; no modifica IMC automáticamente. |

## Selección de medios por destino

`Publication.imc_asset_ids` y `imc_selection_version` guardan una selección
editable únicamente para la versión aprobada actual. No reutilizan ni cambian
`public_asset_ids`, que corresponde a la ficha compartida de Seenode.

- Slots 1–4: fotografías principales.
- Slots 5–10: fotografías adicionales.
- Videos autorizados se guardan después de las fotografías y se exportan bajo
  `videos_autorizados/`.
- El servidor acepta sólo medios que pertenecen a la versión, están listos y
  autorizados, y son de finalidad `general` o `detail`.
- Placas detectadas, placas declaradas y documentos quedan excluidos incluso si
  alguien altera el formulario del navegador.
- Las fichas antiguas conservan todos sus archivos. Si no hay una selección
  IMC explícita, el paquete conserva el orden histórico y limita sus fotografías
  a diez para este destino.

## Paquete y control de acceso

La descarga contiene una sola versión bajo
`ficha_[folio]_[versión]/`: `datos_para_imc.txt`,
`ficha_administrativa.pdf`, carpetas de fotos principales/adicionales, videos y
`manifiesto.txt`. El manifiesto enumera contenido, orden, portada, versión,
anunciante local, campos pendientes y referencia IMC cuando ya existe.

Las rutas PDF y ZIP requieren personal con `portal.publish_machine` y MFA
cuando la plataforma la exige. Visitantes y propietarios normales no reciben la
exportación oficial. Los controles de interfaz son sólo una ayuda: la misma
validación se aplica en el servidor antes de preparar y antes de reconocer un
acuse.
