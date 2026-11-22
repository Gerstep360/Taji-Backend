# Criterios de aceptación y pruebas por CU

| CU | Criterio | Prueba |
| --- | --- | --- |
| CU33 | Alta, consulta, modificación y eliminación con cobertura y vencimiento | CRUD, filtros y validación de Django |
| CU34 | Ofertas por solicitud, moneda, monto y plazo; aislamiento entre condominios | CRUD, validación de monto, permisos y aislamiento |
| CU35 | Cinco puntos con estados conforme, requiere atención y sin revisar | CRUD y validación del checklist |
| CU36 | Comparar de dos a cinco ofertas de igual solicitud y moneda; no comprar | Comparación, decimales, privacidad, duplicados y cuota |
| CU37 | Sugerir seguimiento sin crear órdenes; conservar los datos si no responde IA | Campos permitidos, alternativa manual y respuesta inválida |

Comandos: `python manage.py test operations --settings=config.settings_test`, build de Angular y `playwright test e2e/operations.spec.ts`. La prueba web usa una API simulada; no es una verificación de producción.

## Resultado del 19/11/2026

- Django: 7 pruebas del módulo aprobadas en SQLite y en PostgreSQL 18 aislado. Regresión completa: 722 ejecutadas, 6 omitidas, sin fallos.
- Angular: compilación correcta y recorrido de Edge aprobado. Capturas del [comparador a 1440 px](evidencias/cu36-escritorio.png) y de la [alternativa manual a 390 px](evidencias/cu37-angosto.png).
- NVIDIA: ambos asistentes devolvieron propuestas válidas con datos sintéticos; cinco acciones para cotizaciones y dos para inspecciones. No se enviaron registros de un condominio.
- PlantUML: se renderizaron los 25 diagramas. Las escalas de tiempo son ilustrativas.
- No se aplicaron migraciones ni se desplegó este incremento en producción.
