# Servicio de publicación: integración con la web principal

La portada de este repositorio es una entrada al servicio. La web principal de
IMC México conserva su diseño; no necesita copiar las plantillas ni las hojas de
estilo para utilizar la lógica del portal.

## Punto de entrada y recorrido

`GET /publicar/` conduce al registro o al inicio de una nueva ficha si ya existe
sesión. Registro e inicio de sesión conservan el destino de publicación. Visitar
un enlace nunca crea una ficha ni inicia una llamada de IA.

1. Registro: nombre, apellidos, correo, celular con prefijo internacional,
   preferencia de contacto, contraseña/confirmación y aceptación de términos.
   Empresa es opcional. El teléfono se guarda completo en `User.phone`.
2. Creación explícita del borrador y carga privada de fotografías. Placa opcional.
3. Análisis solicitado por el usuario, aplicación de datos disponibles y edición.
4. Ficha virtual, descarga PDF y envío explícito a revisión.
5. Revisión administrativa, observaciones/notificaciones y publicación autorizada.

## Lógica reutilizable y presentación sustituible

| Área | Código que conserva las reglas |
| --- | --- |
| Cuenta y contacto | `portal/forms.py`, `auth_views.py`, `security.py`, modelos User/Consent |
| Borradores, versiones, permisos y aprobación | `portal/services.py`, `models.py` |
| Archivos privados | `portal/storage.py`, validación de cargas en `processing.py` |
| Lectura e investigación | `processing.py`, `research*.py`, `valuation.py`, `ai_model.py` |
| Notificaciones y correo | `notifications.py`, `emailing.py` y el worker |
| Adaptadores HTTP | `portal/views.py` y `config/urls.py` |

`portal/templates/` y `portal/static/` son la presentación actual. El frontal de
la web original puede llamar a los mismos adaptadores, o implementar adaptadores
propios alrededor de los servicios. Los módulos de dominio siguen usando Django:
no son funciones independientes que puedan pegarse en cualquier tecnología.

## Contrato HTTP existente

Las operaciones privadas requieren sesión y CSRF. Mantener las revisiones para
evitar sobrescribir cambios, y mostrar los errores 400/401/403/404/409 al usuario.

| Operación | Ruta |
| --- | --- |
| Crear borrador | `POST /api/maquinarias/` |
| Guardar correcciones | `POST /api/maquinarias/{id}/guardar/` |
| Cargar fotografía | `POST /api/maquinarias/{id}/archivos/` |
| Solicitar análisis | `POST /api/maquinarias/{id}/analizar/` |
| Consultar resultado y estado | `GET /api/analisis/{id}/` |
| Aplicar resultado | `POST /api/maquinarias/{id}/aplicar/` |
| Enviar a revisión | `POST /api/maquinarias/{id}/enviar/` |
| Ficha privada / PDF | `GET /panel/maquinarias/{id}/ficha/` y `/pdf/` |

No crear nuevas llamadas a IA al abrir páginas, consultar resultados o descargar
PDF. Luna es el modelo activo; Astra está bloqueado. La prueba de integración
automática debe simular el proveedor para evitar costes.

### Investigación y ficha unificada (v29)

- La ficha editable reúne identificación, año aproximado, conservación, datos
  comerciales y estimación en un único documento. Los cambios manuales conservan
  prioridad al repetir el análisis.
- Una foto general incluye hasta cuatro acercamientos de sus mismos píxeles en
  la misma llamada de Luna. No son fotos de unidades diferentes ni nuevas llamadas.
- Con marca legible y sin modelo, la búsqueda devuelve `research.hypotheses`:
  modelos documentados, evidencia, fuentes y periodo de producción cuando existe.
  Son referencias para identificar el equipo; no se copian a `data.model`, al año
  de la unidad ni a su precio. La firma incluye estas hipótesis.
- Cuando existe un perfil de fabricante verificado, la búsqueda de candidatos
  restringe y valida sus dominios. Esto evita confundir empresas homónimas, como
  DEVELON maquinaria (`develon-ce.com`) y una empresa ajena de nombre parecido.
- Un rango visual de edad puede abarcar desde dos años, siempre con indicios de
  generación y sin superar el año actual. Nunca se presenta como fecha exacta.
- Con modelo identificado, la valoración permite hasta dos acciones web y seis
  páginas de anuncios dentro del presupuesto y plazo existentes. Para calcular
  precio necesita comparables verificables e independientes del mismo modelo,
  condición, mercado, moneda y tipo de precio. Anuncios y ventas no se mezclan.

Reabrir una ficha anterior no repite llamadas de pago. Para usar v29 con fotos ya
analizadas, solicitar explícitamente un nuevo análisis en el flujo de fotos.

## Antes de migrar

- Confirmar tecnología, autenticación y esquema de la web original y de MySQL.
  Esa base maestra aún no está vinculada; no se declara una migración terminada.
- Adaptar el esquema aprobado y la exportación, con identificadores estables y
  procedencia de datos. Probar en una copia antes de escribir en la base maestra.
- Mantener secretos, worker, almacenamiento privado y comprobaciones de permisos
  en servidor. No trasladarlos al navegador junto con el formulario.
- Ejecutar `pytest -q` y `npm run test:ui`. Los casos `test_publish_entry.py`,
  `test_quick_intake.py`, `test_auto_completion.py`, `test_security.py` y los de
  teléfono, notificaciones y PDF cubren el recorrido con respuestas simuladas.
- Comprobar el frontal definitivo en celular y escritorio: prefijo separado,
  contraseñas visibles a demanda, errores, guardado, edición, envío y seguimiento.
  Las pruebas locales no acreditan calidad real de IA ni entrega de correo.
