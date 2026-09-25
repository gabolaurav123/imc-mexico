# Borradores temporales de visitantes

Un visitante puede preparar una sola ficha privada, subir hasta tres fotografías y obtener un primer análisis antes de registrarse. El sistema usa la misma `Machine`, sus `Asset` privados y su `AnalysisJob` normal; no crea un expediente paralelo ni una cuenta humana ficticia.

## Autorización y rutas

Al iniciar `POST /api/invitados/`, el servidor crea un principal técnico `User(is_guest=True, is_test=True)` sin contraseña utilizable ni datos personales. La sesión recibe una capacidad aleatoria `{id, secret}`; sólo se conserva su hash en la base. El UUID de la URL no autoriza por sí mismo y el secreto nunca aparece en una URL.

Con esa misma sesión están disponibles:

- `GET /invitados/<uuid>/` para el wizard compartido y `GET /api/invitados/<uuid>/` para su estado.
- `POST /guardar/`, `POST /archivos/`, `POST /archivos/<asset>/accion/` y `GET /archivos/<asset>/` para editar, ordenar y previsualizar sólo sus archivos privados.
- `POST /analizar/` y `GET /analisis/<job>/` para el análisis normal. Acepta fotos o datos declarados (`brand`, `model`, `serial`, `description`) sin fotos; el segundo caso usa `mode: "description"`.

Las cargas están limitadas a tres archivos y el borrador a un análisis. La creación se limita por IP y las cargas por borrador. Las rutas normales de maquinaria requieren propietario autenticado; el middleware bloquea cualquier sesión accidental del principal técnico fuera de la lista de rutas de visitantes. Un visitante no puede enviar, compartir, exportar PDF ni publicar. Los activos públicos requieren una `Publication` aprobada y medios autorizados, condiciones que un borrador temporal no puede alcanzar.

## Conservar después de autenticarse

Tras un registro o inicio de sesión real, `claim_after_authentication` bloquea el borrador y la maquinaria en una transacción y sustituye `Machine.owner` por la cuenta autenticada. Conserva los mismos UUID, archivos y trabajos; la capacidad se borra de la sesión. Un segundo intento o una sesión distinta no puede apropiarse del borrador.

Si un trabajo está ejecutándose al reclamar, conserva su solicitante técnico para la trazabilidad. El completado automático comprueba el propietario actual y no escribe sobre la cuenta recién reclamada; el resultado queda disponible para la propietaria real.

## Caducidad y operación

La capacidad vence a las 24 horas. `runworker` ejecuta una limpieza cada hora; operaciones puede ejecutarla manualmente con:

```powershell
python manage.py purge_guest_drafts --limit 100
```

La limpieza selecciona únicamente borradores vencidos sin reclamar. Marca primero la misma `Machine` como eliminada y cancela trabajos en cola. Si un trabajo ya está ejecutándose, deja el marcador `draft_deleted` y difiere la eliminación hasta que llegue a un estado terminal; así no borra archivos mientras el worker todavía puede consultarlos. Después elimina trabajos, consentimientos técnicos, archivos de base y ficheros privados, y desactiva el principal técnico. Los borradores reclamados, o cualquier ficha que inesperadamente tenga versiones, solicitudes o publicaciones, se preservan.
