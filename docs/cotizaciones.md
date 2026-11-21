# DPIA Cotizaciones — desarrollo incremental

Rama de trabajo independiente de main. El primer cambio incorpora el dominio puro
de observaciones históricas y comparación de ofertas; **no** constituye todavía
un servicio comercial completo ni habilita la tarea COTIZACIONES en producción.

## Arquitectura prevista

- Dispatcher: recibir un tipo de tarea configurado COTIZACIONES; mantener autorización,
  límites e idempotencia.
- Planner: seleccionar exclusivamente herramientas autorizadas de cotización.
- Worker: procesar lotes de productos y adaptadores por proveedor; registrar evidencia.
- Manager: evaluar cobertura, coincidencia técnica y faltantes sin inventar precios.
- Persistencia: catálogo, proveedores, cotizaciones, observaciones históricas inmutables,
  ejecuciones periódicas y auditoría de fuentes.
- Entrega: presupuesto exportable y series históricas por producto/proveedor.

## Contratos y precauciones

Cada observación registra identificadores de producto/proveedor, fecha con zona horaria,
precio unitario Decimal, moneda, disponibilidad, transporte y cantidad mínima.
El comparador no mezcla monedas ni presupone impuestos, descuentos, equivalencia
técnica o vigencia. Estas validaciones deben incorporarse antes de recomendar compras.
Una cotización sin evidencia se marca como no disponible, nunca se inventa.

## Pendiente para integrar

1. Confirmar contratos de task_schedules, capacidades y registry de workers.
2. Diseñar migraciones SQLAlchemy y retención de series temporales.
3. Incorporar adaptadores autorizados de proveedores, límites y reintentos.
4. Registrar tipo COTIZACIONES, programación y permisos.
5. Exportación Excel, pruebas de integración, medición de costos y validación con
   proveedores reales.

No se ha modificado main ni desplegado ningún servicio.
