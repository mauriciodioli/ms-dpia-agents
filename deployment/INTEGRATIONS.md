# DPIA Agents: integraciones operativas

Implementación preparada para revisión. No se ejecutó DDL, despliegue, push ni llamadas a proveedores reales.

## Archivos de la implementación

- `src/agent_engine/integration_models.py`: dos tablas propias de configuración y auditoría.
- `src/agent_engine/integrations.py`: configuración cifrada, revisiones, diagnósticos y switch.
- `src/agent_engine/integration_api.py`: administración, autorización explícita por agente y búsqueda de prueba.
- `src/agent_engine/provider_transport.py`: HTTPS sin redirecciones/reintentos y validación de diagnósticos.
- `src/agent_engine/provider_handlers.py`: Amazon mediante DPIA Scraper y análisis mediante OpenAI.
- `src/agent_engine/{__init__,api,cli,tools,task_box,worker,outbox}.py`: registro, permisos y ejecución sobre el motor existente.
- `src/config.py`: configuración del cifrado, hosts y modelos permitidos.
- `src/static/agents-workspace.{js,css}`: tarjetas equivalentes y modales.
- `deployment/agent-integrations.sql`: migración manual aditiva; no modifica tablas existentes.

Los tests quedan únicamente locales, ignorados por Git. Docker copia `src/`, no `tests/` ni `deployment/`.

## Semántica del switch

El switch administra el acceso de los Workers a la credencial. Apagado, no se descifra el token para ejecutar tareas ni se inician llamadas externas. No se elimina la credencial, no se revoca en el proveedor y no se borran trabajos/resultados.

Leer estado/configuración no descifra la credencial. Probar conexión y activar son acciones administrativas explícitas que sí pueden utilizarla. Probar conexión nunca cambia `enabled`.

El estado se comprueba en Outbox, al reclamar la tarea y nuevamente antes del POST externo. Los mensajes que ya están en Redis se retienen sin iniciar llamadas. La autorización de envío se registra como `SUBMITTING` bajo bloqueo de la misma fila de integración que usa desactivar. Una llamada ya autorizada puede finalizar y guardar su resultado. El siguiente paso queda retenido si el proveedor está apagado. Las tareas pendientes conservan sus deadlines originales; no se extienden automáticamente.

Si se pierde la respuesta de un POST, la tarea queda `BLOCKED_UNCERTAIN`, conserva el identificador externo cuando se recibió y no se reenvía automáticamente. Reconciliar antes de crear una nueva búsqueda. La clave de idempotencia de Scraper es estable por `task_id`.

Guardar configuración desactiva y limpia el diagnóstico anterior; exige activar nuevamente. La versión `expected_revision` impide que un diagnóstico lento sobreescriba una desactivación o cambio posterior.

## Preparación manual

1. Respaldar la base de datos propia de Agents. Revisar y aplicar **una sola vez** `deployment/agent-integrations.sql` en esa base, antes de arrancar esta versión. El archivo crea `ae_integrations` y `ae_integration_audit`; no altera las migraciones oficiales anteriores ni crea otra base de datos.
2. Configurar una clave Fernet independiente de MySQL: `AGENTS_INTEGRATION_MASTER_KEY`. Generarla una sola vez con `cryptography.fernet.Fernet.generate_key()`, guardarla en el gestor de secretos y entregar el mismo valor al servidor web y a ambos Workers. No imprimirla en logs, versionarla ni regenerarla al reiniciar. Conservar copia segura; perderla impide descifrar credenciales existentes.
3. Definir estas variables en el entorno protegido usado por el contenedor:

   - `AGENTS_INTEGRATION_MASTER_KEY`: obligatoria para guardar/usar credenciales.
   - `DPIA_SCRAPER_BASE_URL=https://api.dpia.site/api/scraper/v1`.
   - `DPIA_SCRAPER_ALLOWED_HOSTS=api.dpia.site`: ampliar solo a dominios HTTPS confiables administrados por el operador. El navegador no controla esta lista.
   - `DPIA_SCRAPER_TIMEOUT_SECONDS=120`: admitidos 90–180 segundos.
   - `AGENTS_OPENAI_MODELS`: lista separada por comas de modelos autorizados por el operador. La activación comprueba acceso al modelo elegido; la lista no afirma disponibilidad para la cuenta.
   - `OPENAI_MODEL`: modelo inicialmente seleccionado; debe estar en la lista anterior.
   - Mantener la configuración MySQL y Redis existente.

   Los tokens/API keys se introducen en el modal administrativo y quedan cifrados en MySQL. No se importa automáticamente una clave legacy ni se utiliza un token de clientes Agents como credencial externa. Las configuraciones guardadas en MySQL prevalecen sobre los valores iniciales de URL/timeout/modelo.

4. Construir/publicar manualmente la imagen aprobada y actualizar únicamente los procesos de Agents, conservando los montajes y variables actuales. No se modificó `.github/workflows/aws.yml`, Dockerfile, Nginx ni Redis.
5. Iniciar dos procesos adicionales con **la misma imagen aprobada**, red `red_app`, configuración y montajes de solo lectura del web. No necesitan puertos publicados:

```sh
# Comandos de proceso dentro de la imagen existente:
flask --app app agent-worker --providers --capability search --watch --interval 5
flask --app app agent-worker --providers --capability analysis --watch --interval 5
```

Nombres sugeridos: `ms202612agents-worker-scraper` y `ms202612agents-worker-openai`. Para Docker, usar esos nombres con `docker run -d --network red_app --restart unless-stopped`, la imagen aprobada y los mismos montajes/configuración protegida del servicio web; agregar el comando correspondiente después de la imagen. No ejecutar `--providers` junto con `--local-test`. Mantener el Worker local existente.

La tabla `ae_workers` conserva identificadores únicos por proceso y heartbeat. La UI exige señal de menos de 60 segundos y capacidad `search` o `analysis`; un Worker ocupado sigue estando disponible operativamente.

## Prueba real controlada (pendiente, no ejecutada)

1. Iniciar sesión administrativa en `/integrations`. Guardar las credenciales correspondientes. La URL de Scraper debe permanecer en el host autorizado.
2. Pulsar **Probar conexión** en ambas tarjetas. Scraper consulta `/auth/check` para lectura y escritura, `/estado` y `/marketplaces`. OpenAI consulta `GET /v1/models/{model}`. Estas acciones no generan contenido ni ejecutan scraping.
3. Comprobar permisos, latencia medida, última conexión y heartbeat del Worker. `/estado` no prueba Apify, Sheets ni su base de datos. El diagnóstico OpenAI confirma acceso a metadatos del modelo, no garantiza cuota ni permisos de inferencia de una clave restringida; estos solo se confirman cuando se realiza la tarea autorizada.
4. Activar cada integración. Configurar un agente propio con `dpia.amazon.search`, habilitarlo y autorizarlo expresamente en **Configurar → Autorizar mis agentes**. La habilitación global no concede automáticamente acceso a todos los usuarios/agentes. Límites recomendados para la prueba: una llamada, 300 segundos, sin correcciones. Para ejecutar OpenAI, autorizar también `openai.analysis` y ajustar el presupuesto de tokens.
5. Configurar previamente el presupuesto del proveedor. **Ejecutar búsqueda de prueba** permite una consulta Amazon y una sola llamada. El contrato externo limita Amazon a un máximo de diez resultados; `max_products` limita los resultados conservados, no el costo externo. Scraper no documenta un tope monetario por solicitud: no se envía ni promete uno. El formulario exige confirmar el posible costo antes de crear el trabajo.
6. Seguir el identificador en **Ejecuciones**. El recorrido es Dispatcher → Outbox → Redis Streams → Worker → proveedor → MySQL. La respuesta válida queda `REVIEWING`, con evidencia `UNVERIFIED`. No se cambiaron `Reviewer`, `ReviewCoordinator`, verificador ni las reglas de entrega. Un resultado no aprobado/entregado continúa respondiendo 409 en el endpoint de resultados.
7. Desactivar la integración y verificar que no se inician nuevas llamadas. Las ya autorizadas pueden terminar. No reenviar una tarea `BLOCKED_UNCERTAIN` sin reconciliar el trabajo externo.

Amazon es el único adaptador de búsqueda habilitado. MercadoLibre, eBay y AliExpress muestran su presencia en catálogo, pero sus adaptadores siguen pendientes. No se publican productos automáticamente ni se realizan llamadas de imágenes/publicación.

## API administrativa

Todas las rutas requieren sesión de administrador; los clientes Bearer de Agents no pueden administrarlas. Las escrituras requieren JSON, `X-DPIA-Action: manage-integrations` y comprobación de mismo origen.

- `GET /api/agents/v1/integrations` y `GET /integrations/{id}`: configuración sin secretos.
- `GET /api/agents/v1/integrations/{id}/health`: último diagnóstico y disponibilidad actual del Worker, sin llamadas externas.
- `PUT /api/agents/v1/integrations/{id}`: `{expected_revision, config, credential?}`. Omitir `credential` conserva la existente.
- `POST /api/agents/v1/integrations/{id}/{test|enable|disable}`: `{expected_revision}`.
- `GET /api/agents/v1/integrations/{id}/agents`: agentes propios con la herramienta.
- `PUT /api/agents/v1/integrations/{id}/agents/{agent_id}`: autorización explícita, `{expected_revision, authorized}`.
- `POST /api/agents/v1/integrations/dpia-scraper/trial`: confirmación de costo, parámetros limitados y encabezado `Idempotency-Key`.

Identificadores: `dpia-scraper` y `openai`. `enabled`, `configured`, `authenticated`, `healthy`, `permissions_ok`, `adapter_implemented` y `worker_available` son campos independientes. Las credenciales, ciphertext y hashes no forman parte de las respuestas.

## Verificación realizada

67 pruebas aprobadas: controles y cifrado, persistencia al reabrir almacenamiento, autorización/CSRF, conflictos de revisión, acceso al token, errores de transporte, cola/Workers, navegador Chromium de escritorio/móvil, política de revisión y acceso a resultados. Sin consumo de créditos: proveedores simulados, SQLite temporal y doble de Redis Streams. No se probó contra MySQL/Redis de producción. Chromium ejecutó el JavaScript sin errores; `git diff --check` limpio.

Fuentes de contrato consultadas:
- DPIA Scraper: https://api.dpia.site/scrapeador/#api y su catálogo público `/static/docs/scraper-endpoints.json`.
- OpenAI: https://developers.openai.com/api/reference/resources/models/methods/retrieve
- Transporte Responses ya existente en `services/result_generation.py`; el nuevo handler usa el mismo endpoint oficial `/v1/responses`, con `store: false` y límite de salida.
