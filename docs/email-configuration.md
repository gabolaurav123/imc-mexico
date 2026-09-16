# Diagnóstico de correo

Ejecutar `python manage.py check_email_config` o añadir `--json` para un informe estructurado. El comando sólo inspecciona la configuración cargada: no consulta la base de datos, DNS ni SMTP, no se autentica y no envía mensajes. Devuelve código 1 si detecta errores; las advertencias conservan código 0.

Muestra backend, host, puerto, remitente y dirección de respuesta. De `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD` sólo muestra si están configurados. No imprime `PUBLIC_URL`, enlaces privados, credenciales ni contenido de notificaciones. Un resultado `ok` significa que no detectó inconsistencias locales; **no acredita dominio verificado, acceso SMTP ni recepción**.

## Configuración

- Usar el remitente autorizado en `DEFAULT_FROM_EMAIL`.
- `EMAIL_REPLY_TO` es opcional: un solo buzón atendido, por ejemplo `IMC México <soporte@dominio-propio>`. Puede incluir un nombre entrecomillado; no admite listas ni saltos de línea. Vacío omite el encabezado.
- Elegir la modalidad y puerto indicados por el proveedor. No activar `EMAIL_USE_TLS` y `EMAIL_USE_SSL` simultáneamente.
- Mantener `PUBLIC_URL` como origen del portal, con HTTPS en producción, sin rutas privadas ni parámetros.
- Los backends `console`, `filebased`, `locmem` y `dummy` son locales y no acreditan envío SMTP; algunos guardan los enlaces de acceso en consola o archivos.

El remitente `resend.dev` está limitado a pruebas hacia el correo asociado a la cuenta Resend. Para destinatarios generales se necesita un dominio propio verificado y un remitente de ese dominio. El diagnóstico detecta esa restricción por el remitente configurado, pero no consulta su estado DNS. [Documentación de Resend](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain).

## Verificación operativa

Revisar por separado los registros de autenticación del dominio con el proveedor y realizar sólo un envío autorizado al destinatario acordado. `Notification.status='sent'` y el contador del worker significan **aceptación por el backend**. No prueban entrega al servidor destinatario, bandeja de entrada ni lectura.

Las direcciones `.invalid` se suprimen antes del envío. Para enlaces de acceso vencidos, `python manage.py retention` informa y `--apply` redacta su contenido conforme a la política existente. El diagnóstico no ejecuta retención ni cambia la cola.
