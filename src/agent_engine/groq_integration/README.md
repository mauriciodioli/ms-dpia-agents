# Groq — módulo independiente para guiones de video

Adaptador aislado en la capa de modelo, reutiliza ProviderHTTP y el contrato existente `video_script.build` / `validate_script`. No cambia rutas, controladores, tablas, workers, switches ni el proveedor predeterminado OpenAI. No ejecuta llamadas durante importación.

La clave se obtiene después en Groq Console y se guarda en un almacén de secretos, nunca en Git. Este módulo acepta la clave mediante inyección en tiempo de ejecución. Ejemplo de integración futura desde el controlador autorizado del worker:

```python
from agent_engine.groq_integration import GroqScript, GroqSettings
from agent_engine.video_script import build
# secret debe venir de la integración cifrada y habilitada, no de una petición del usuario.
generator = GroqScript(secret, GroqSettings(model='openai/gpt-oss-20b'))
script = build(source_context, generator)
```

Antes de activar en producción faltan: registrar el proveedor en el módulo administrativo de integraciones, cifrar y autorizar su credencial, aplicar el control de presupuesto/uso, fencing del worker y fallback explícito a OpenAI. No se debe conectar directamente al worker sin esos controles. El modelo y la modalidad JSON deben verificarse con una clave real; los límites gratuitos pueden cambiar.
