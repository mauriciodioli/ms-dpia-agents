# Configuración de tareas en DPIA Agents

Se separa el editor de datos generales del agente del editor de las tareas configuradas que ya existen en `agente_tareas`. No se confunden con `ae_tasks`, que contiene pasos del worker.

## Interfaz

- «Mis agentes» conserva sus controles y añade «Tareas configuradas» desplegable, con enlaces individuales.
- Al configurar un agente que tiene tareas, se muestra la tabla de tareas y el formulario de identidad, descripción, instrucciones generales y zona horaria. Herramientas y límites se editan en cada tarea.
- Cada tarea abre el editor existente con su nombre, instrucciones, descripción, zona horaria, herramientas, parámetros y límites propios.
- Administración añade una tabla con una única columna «Tarea». En la misma celda se identifica el agente y propietario. Cada enlace abre el editor administrativo de esa tarea y vuelve a Administración después de guardar. La tabla tiene paginación independiente.
- Para agentes nativos sin tareas configuradas existentes, se conserva el editor previo de valores base; este cambio no crea tareas ni agentes originales automáticamente.

## MVC

- Repositorio: `src/agent_engine/configured_task_repository.py`, reflexión sin DDL de `agente_tareas`, vínculos con `ae_agents` y exclusión de agentes eliminados.
- Servicio: `src/agent_engine/configured_tasks.py`, autorización de propietario/administrador, validación con los contratos y herramientas existentes, revisiones independientes y auditoría de cambios.
- Controlador: `src/agent_engine/configured_task_api.py`, registrado antes del Blueprint, utiliza autenticación, CSRF, contratos, respuestas JSON y transacciones existentes.
- `AgentManager.save_identity` conserva las herramientas y límites base y reutiliza el guardado/auditoría existente.
- Vista: `src/static/agents-workspace.js`, rutas HTML en `src/routes/main_routes.py`, versión de recurso en `src/templates/agents_workspace.html`.

## Persistencia y compatibilidad

Sin tablas nuevas, migraciones ni SQL adicional. `agente_tareas.parametros` conserva sus claves anteriores y añade dos claves reservadas:

- `_agent_configuration`: configuración validada del editor de esa tarea.
- `_configuration_revision`: revisión independiente, inicialmente 1; guardar exige `expected_revision` y devuelve 409 ante conflicto.

El nombre se guarda en `agente_tareas.nombre`. Se conserva `habilitada`, el historial y las programaciones. Se excluyen tareas con `_deleted_at`. Los vínculos `ae_agent_id` nulos se resuelven por `ae_agents.legacy_agent_id → agente_tareas.agente_id`; un vínculo contradictorio se rechaza. Se bloquea el propietario antes de las filas para coordinar cambios con B2B.

El repositorio B2B también adapta `src/services/agent_configuration.py` para aceptar estas claves reservadas sin invalidar sus controles existentes y conservarlas al editar los valores generales del agente. El guardado original de Agents también las conserva. Deben desplegarse ambos cambios para compartir los nuevos metadatos.

Antes del primer guardado, el editor de tarea presenta los valores base del agente. Después mantiene una copia independiente, por lo que editar una tarea no cambia otra ni los valores generales.

Este cambio administra configuración. No modifica dispatcher, workers, consumo ni programaciones; las ejecuciones existentes siguen usando sus contratos y snapshots actuales. La incorporación de estos valores independientes al flujo de ejecución debe tratarse por separado antes de asumir que se aplican a una ejecución automática.

## Endpoints nuevos

Prefijo `/api/agents/v1`:

- `GET /agents/{agent_id}/configured-tasks`
- `GET/PATCH /agents/{agent_id}/configured-tasks/{task_id}`
- `GET /admin/configured-tasks?limit=25&after={task_id}`
- `GET/PATCH /admin/agents/{agent_id}/configured-tasks/{task_id}`
- `PATCH /agents/{agent_id}/identity`

El acceso administrativo requiere sesión de administrador; una cookie de otro propietario o un cliente API no obtiene privilegios administrativos. PATCH conserva el encabezado `X-DPIA-Action: manage-agents` y las comprobaciones de origen existentes.

## Validación

- `test_configured_tasks`: cuatro pruebas correctas con base SQLite aislada: independencia, revisiones, autorización, CSRF, paginación, borrado lógico y ausencia de trabajos/programaciones nuevos.
- Dos recorridos nuevos con Chromium y API Flask real: editor de tarea separado del general y selección/edición de una tarea ajena desde la tabla administrativa.
- Regresión B2B: 33 pruebas correctas de tareas, configuración, activación y pausa.
- Suite backend antigua `test_agents_workspace`: 7 correctas y una expectativa desactualizada en `test_session_requires_active_cookie_and_does_not_leak_identity`, que espera dos herramientas; el registro en HEAD ya contiene tres. No se cambió ese registro.
- No se accedió a producción ni se ejecutó DDL fuera de las bases temporales de pruebas.

La suite antigua de navegador `test_agents_workspace_ui.WorkspaceBrowserTests` deja cuatro pruebas correctas y tres incompatibilidades previas: espera un selector «Agente» en Programaciones que la vista actual no contiene, el texto anterior del estado vacío y una frase anterior del mensaje de conflicto. Las secciones y mensajes correspondientes ya difieren en HEAD; no se alteraron para acomodar esas expectativas.

Además pasó una prueba B2B específica de lectura y conservación de los metadatos independientes al volver a guardar la configuración general.
