# Borradores temporales de visitantes

Un visitante puede preparar una sola ficha privada, subir hasta cuatro fotografías y obtener un primer análisis antes de registrarse. El sistema usa la misma `Machine`, sus `Asset` privados y su `AnalysisJob` normal; no crea un expediente paralelo ni una cuenta humana ficticia.

## Autorización y rutas

Al iniciar `POST /api/invitados/`, el servidor crea un principal técnico `User(is_guest=True, is_test=True)` sin contraseña utilizable ni datos personales. La sesión recibe una capacidad aleatoria `{id, secret}`; sólo se conserva su hash en la base. El UUID de la URL no autoriza por sí mismo y el secreto nunca aparece en una URL.

## Intento gratuito y prevención de abuso

Una persona sin cuenta dispone de una sola ficha temporal por dirección de red o navegador. Antes de crear el borrador, el servidor registra un `GuestTrial` duradero con el digest HMAC de la IP y un segundo digest de un marcador aleatorio del navegador. El marcador es una cookie opaca con vigencia de 400 días, `HttpOnly`, `Secure` fuera de desarrollo y `SameSite=Lax`; no contiene datos personales y sobrevive al inicio y cierre de sesión. Ambos digest son únicos: cambiar de red en el mismo navegador tampoco permite otro intento. No almacena IP, identificador de navegador ni cabeceras de red en claro. El registro no se elimina al caducar la ficha, por lo que borrar cookies, abrir otra sesión o esperar la limpieza no crea nuevos intentos.

La restricción es una unicidad de base de datos, no un contador en memoria: se aplica entre procesos y ante solicitudes simultáneas. Se consume sólo dentro de la misma transacción que crea correctamente el borrador; una solicitud inválida o un fallo de creación se revierte y no gasta el intento. Si la misma sesión todavía conserva su capacidad, `POST /api/invitados/` reabre la ficha ya iniciada.

La respuesta agotada usa HTTP `429` con `code: "guest_trial_used"` y `signup_url: "/registro/"`, para que la interfaz explique que debe crear una cuenta. Al registrarse o iniciar sesión, la ficha existente se transfiere a esa cuenta y desde entonces usa los límites normales de cuentas autenticadas. Compartir, publicar y exportar siguen requiriendo esa cuenta; el borrador de visitante no expone esas rutas.

La IP procede de `REMOTE_ADDR` por defecto. `X-Forwarded-For` se lee sólo si el par inmediato pertenece a `TRUSTED_PROXY_CIDRS`; la resolución recorre la cadena desde el proxy hacia el cliente para ignorar valores inyectados. Configure únicamente los CIDR documentados por el alojamiento. El prefijo internacional del teléfono pertenece al perfil de la cuenta cuando la persona se registra; no se intenta inferir un país desde la red.

Con esa misma sesión están disponibles:

- `GET /invitados/<uuid>/` para el wizard compartido y `GET /api/invitados/<uuid>/` para su estado.
- `POST /guardar/`, `POST /archivos/`, `POST /archivos/<asset>/accion/` y `GET /archivos/<asset>/` para editar, ordenar y previsualizar sólo sus archivos privados.
- `POST /analizar/` y `GET /analisis/<job>/` para el análisis normal. Acepta fotos o datos declarados (`brand`, `model`, `serial`, `description`) sin fotos; el segundo caso usa `mode: "description"`.

Las cargas están limitadas a cuatro archivos y el borrador a un análisis. Si el proveedor informa de falta de crédito, credenciales o modelo, ese fallo no consume el análisis: se permiten hasta tres intentos técnicos fallidos en el mismo borrador, sin reintentos automáticos. Un trabajo en cola, ejecutándose, completado o con otro fallo sí consume el análisis. El estado incluye `analysis_used` para que otra generación ofrezca crear cuenta.

La IP no identifica de forma inequívoca a una persona: redes de oficina comparten dirección, y cambiar a la vez red y navegador puede eludir este control. La página de límite explica el caso de red compartida y permite registrarse. La marca de agua disuade capturas de la vista previa; ninguna web puede impedir una captura del sistema operativo. La protección efectiva es impedir enlaces públicos/PDF y nuevos análisis anónimos desde el servidor, no desactivar el clic derecho.

En SeeNode se configuró el 6 de octubre una lista de proxies `/32` contrastada con las conexiones que recibe esta aplicación. No se confía globalmente en redes privadas ni en una cabecera enviada directamente por el visitante. Si el proveedor cambia sus proxies, debe actualizarse esta lista antes de mantener el cupo por IP.

Las rutas normales de maquinaria requieren propietario autenticado; el middleware bloquea cualquier sesión accidental del principal técnico fuera de la lista de rutas de visitantes. Un visitante no puede enviar, compartir, exportar PDF ni publicar. Los activos públicos requieren una `Publication` aprobada y medios autorizados, condiciones que un borrador temporal no puede alcanzar. El catálogo se carga bajo demanda desde su API; el wizard de visitante no serializa todos los modelos.

## Conservar después de autenticarse

Tras un registro o inicio de sesión real, `claim_after_authentication` bloquea el borrador y la maquinaria en una transacción y sustituye `Machine.owner` por la cuenta autenticada. Conserva los mismos UUID, archivos y trabajos; la capacidad se borra de la sesión. Un segundo intento o una sesión distinta no puede apropiarse del borrador.

Si un trabajo está ejecutándose al reclamar, conserva su solicitante técnico para la trazabilidad. El completado automático comprueba el propietario actual y no escribe sobre la cuenta recién reclamada; el resultado queda disponible para la propietaria real.

## Caducidad y operación

La capacidad vence a las 24 horas. `runworker` ejecuta una limpieza cada hora; operaciones puede ejecutarla manualmente con:

```powershell
python manage.py purge_guest_drafts --limit 100
```

La limpieza selecciona únicamente borradores vencidos sin reclamar. Marca primero la misma `Machine` como eliminada y cancela trabajos en cola. Si un trabajo ya está ejecutándose, deja el marcador `draft_deleted` y difiere la eliminación hasta que llegue a un estado terminal; así no borra archivos mientras el worker todavía puede consultarlos. Después elimina trabajos, consentimientos técnicos, archivos de base y ficheros privados, y desactiva el principal técnico. Los borradores reclamados, o cualquier ficha que inesperadamente tenga versiones, solicitudes o publicaciones, se preservan.
