# MCP — Servidores y herramientas

Implementación en `ms-dpia-agents`, sin despliegue ni cambios de producción. Se verificaron las cinco tablas con SHOW CREATE TABLE; no se ejecutó DDL ni migraciones en producción. Las bases SQLite de pruebas se crean únicamente para verificación local.

## Interfaz y REST

Integraciones incluye «Servidores MCP»: alta, edición, diagnóstico, descubrimiento, activación/pausa, revisión de herramientas, permisos por agente y eliminación con confirmación. El navegador solo se comunica con DPIA; las conexiones MCP las realiza el backend.

Prefijo real: `/api/agents/v1`.

| Método | Ruta | Scope |
|---|---|---|
| GET | `/mcp/servers` | `mcp:read` |
| POST | `/mcp/servers` | `mcp:write` |
| GET | `/mcp/servers/{server_id}` | `mcp:read` |
| PATCH | `/mcp/servers/{server_id}` | `mcp:write` |
| DELETE | `/mcp/servers/{server_id}` | `mcp:write` |
| POST | `/mcp/servers/{server_id}/test` | `mcp:write` |
| POST | `/mcp/servers/{server_id}/discover` | `mcp:write` |
| PATCH | `/mcp/servers/{server_id}/status` | `mcp:write` |
| GET | `/mcp/servers/{server_id}/tools` | `mcp:read` |
| PATCH | `/mcp/tools/{tool_id}` | `mcp:write` |
| PUT | `/mcp/tools/{tool_id}/grants/{agent_id}` | `mcp:write`, aprobación cuando corresponda |

El portal `/developers` añade «MCP — Servidores y herramientas» con solicitudes/respuestas JSON, errores, permisos y 13 ejemplos curl copiables. `/api/agents/v1/contracts` publica los contratos OpenAPI de MCP.

Registrar guarda el servidor pausado e intenta inicialización y descubrimiento. Si falla el diagnóstico, el registro permanece pausado y POST devuelve 201 con `diagnostic_status` y el código de error en el servidor. No se invocan herramientas al registrar, probar ni descubrir. PATCH de configuración exige el objeto completo y `enabled:false`, conserva la credencial si se omite y revoca los permisos anteriores. Para activar se requiere diagnóstico satisfactorio y descubrimiento previo.

Las operaciones de cambio usan `expected_revision`, correspondiente al servidor/catálogo, incluso para herramientas y permisos. DELETE también exige `confirm:true`. Los listados de servidores admiten `limit` de 1 a 100 y cursor UUID `after`.

## Permisos y secretos

Los roles reales `admin`/`administrador` y `advanced`/`avanzado` habilitan administración MCP. Las sesiones de administrador pueden gestionar todos los servidores; los avanzados gestionan los registrados por su propietario. Los servidores son globales en el esquema existente, sin columna owner_id: `created_by` conserva el propietario que los registró. Los clientes Bearer operan sobre los registros de su propietario; para cambios MCP necesitan all_agents=true y los scopes correspondientes. Tener un ID de usuario no autoriza ninguna operación.

`mcp:approve` requiere rol administrador y permite revisar el riesgo o aprobar permisos HIGH/CRITICAL. Las nuevas herramientas quedan deshabilitadas y con riesgo HIGH, ignorando recomendaciones de confianza del servidor remoto. Los permisos operativos se guardan en `ae_mcp_tool_grants` con propietario, agente y herramienta. Las sesiones administrativas pueden autorizar otro propietario únicamente mediante owner_id explícito y comprobado. Los demás clientes quedan limitados al propietario autenticado. El scope `mcp:execute` también se exige para ejecutar o programar pasos MCP a través de los contratos existentes.

Las sesiones mantienen protección de origen y `X-DPIA-Action: manage-mcp`. Los clientes externos usan Bearer sin depender de cookies. Se reutiliza `AGENTS_INTEGRATION_MASTER_KEY` para cifrar credenciales Fernet. Las respuestas exponen únicamente has_credential. Se admite auth_type none, bearer o header; header utiliza `credential={"name":"X-API-Key","value":"..."}`. Nunca se precarga la credencial en formularios.

## Transporte y catálogo

Se implementa Streamable HTTP con protocolo 2025-06-18: initialize, notifications/initialized, ping, tools/list paginado y tools/call. Acepta respuestas JSON y SSE, y conserva el identificador de sesión y la versión negociada. No implementa stdio, instalación de código remoto, sampling ni ejecución de comandos.

Solo se permiten endpoints HTTPS públicos en puerto 443, sin credenciales, consulta ni fragmento en la URL. Se verifican todas las direcciones DNS, se rechazan direcciones privadas/reservadas y se fija la dirección de conexión conservando SNI y validación TLS. No se siguen redirecciones ni se usan proxies ambientales. Hay límites de tiempo, respuesta de 1 MiB, 200 herramientas y 20 páginas por descubrimiento. Los esquemas tienen límites de tamaño/profundidad y rechazan referencias externas o recursivas.

El catálogo no utiliza caché de proceso: Manager, Dispatcher y TaskBox consultan los datos actuales. Los trabajos guardan server_revision, nombre y huella del esquema en configuration_snapshot.mcp_tools. Antes de invocar se vuelven a comprobar servidor, herramienta, permiso y versión. Un cambio de catálogo incompatible rechaza la versión anterior; no se reescribe el trabajo para ejecutar una herramienta distinta.

Pausar o eliminar revoca disponibilidad para llamadas nuevas. Eliminar usa deleted_at y conserva herramientas, auditoría y ejecuciones. Los cambios de esquema/descripción o riesgo invalidan los permisos correspondientes. Una llamada que ya salió hacia un proveedor no se puede cancelar retroactivamente; la autorización anterior al envío es el punto de control compartido con revocación.

## Workers, consumo y selección

El adaptador MCP es código local de confianza dentro del Worker existente. Para atender la cola MCP, el despliegue debe disponer de un worker con esa capacidad, por ejemplo desde src:

```bash
flask --app app agent-worker --providers --capability mcp --watch
```

No se inició ningún worker ni se ejecutó este comando durante la implementación. Después de disponer del adaptador y capacidad MCP, registrar servidores nuevos no requiere reiniciar el worker; las pruebas lo verifican con un worker iniciado antes del primer servidor.

Se mantienen los límites existentes por trabajo de llamadas, duración y tokens. Las ejecuciones registran estado y duración en ae_mcp_executions y llamadas en ae_usage. Los costos monetarios y moneda permanecen NULL cuando no existe evidencia verificable del proveedor: no se inventan tarifas ni se modifica el sistema de puntos. No hay garantía de un techo monetario para tarifas desconocidas; las herramientas sensibles requieren aprobación explícita.

`POST /api/agents/v1/agents/{agent_id}/source-selection` recomienda una fuente sin ejecutarla. Requiere jobs:create y la protección manage-agents para sesiones. Entrada: required_terms, fresh_seconds (1–86400), currency y candidates. Cada candidato contiene tool, sufficient, valid_until y estimated_cost. Se comprueba primero evidencia local entregada, vigente y que cumpla los términos; después se comparan fuentes elegibles de API/scraping/MCP y se reserva OpenAI para razonamiento cuando las otras fuentes resulten insuficientes. Las estimaciones remotas de costo y suficiencia son del solicitante, no cargos acreditados. Se conserva el orden de los pipelines explícitos del contrato existente; no se obliga a pasar por OpenAI ni por Apify. Apify conserva su integración existente a través del Scraper; no se añadió un proveedor paralelo.

## Archivos y arquitectura

- Modelos: agent_engine/mcp_models.py, basados en las cinco tablas verificadas; metadata independiente, sin DDL al importar.
- Repositorio: mcp_repository.py; consultas de evidencia local añadidas a repository.py.
- Servicios: mcp_service.py, mcp_catalog.py, source_selection.py y tool_selection.py.
- Transporte y adaptador: mcp_transport.py y mcp_runtime.py.
- Controladores: mcp_api.py; registro en agent_engine/__init__.py.
- Autenticación/contratos: auth.py, contracts.py y la respuesta mínima de sesión en api.py.
- Runtime: tools.py, management.py, configured_tasks.py, dispatcher.py, task_box.py, worker.py, provider_handlers.py y cli.py.
- Vista: agents-workspace.js y versión de recurso en agents_workspace.html.
- Documentación integrada: mcp_documentation.py, specification.py, developer_portal.py y agents_developers.html.

## Validación

- 15 pruebas MCP nuevas correctas: CRUD real, API Bearer, scopes y roles, cifrado, aprobación sensible, versiones dinámicas, revocación, ejecución con cola/worker, programación, integridad referencial, SSRF, JSON/SSE, esquemas y dos recorridos en Chromium.
- Se ejecutaron 87 comprobaciones combinadas de MCP y regresión de integraciones/runtime: 85 correctas. Dos comprobaciones de artefactos oficiales están bloqueadas porque faltan archivos de migración que sus fixtures esperan. No se generaron ni ejecutaron migraciones para acomodarlas.
- git diff --check correcto.
- Los tests se mantienen localmente en tests/ y están ignorados por Git, por indicación del usuario.

Referencias de protocolo: [transporte Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [ciclo de inicialización](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle) y [herramientas MCP](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
