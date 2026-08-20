# Contrato REST de Taji

La API pública usa el prefijo `/api/v1`. Los cuerpos de entrada y salida son
JSON, excepto OpenAPI, que puede negociarse como YAML o JSON.

## Documentación interactiva

- Swagger UI: `http://<servidor>:8000/api/v1/docs/`
- OpenAPI: `http://<servidor>:8000/api/v1/openapi/`
- Los alias `/api/docs/` y `/api/schema/` se conservan temporalmente.

El esquema se puede validar sin levantar el servidor:

```powershell
.\.venv\Scripts\python.exe manage.py spectacular --file openapi.yaml --validate
```

## Errores uniformes

Todos los endpoints DRF devuelven la misma envoltura de error:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Revisa los campos indicados.",
    "fields": {
      "email": ["Ya existe una cuenta con este correo."]
    }
  }
}
```

`fields` solo aparece cuando hay errores asociados a campos. Los códigos base
son `validation_error`, `bad_request`, `authentication_failed`,
`permission_denied`, `not_found`, `method_not_allowed`, `conflict`, `throttled`,
`service_unavailable` e `internal_error`.

## Paginación

Los listados futuros usan `page` y `page_size`. El tamaño predeterminado es 20
y el máximo permitido es 100:

```json
{
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 42,
    "total_pages": 3,
    "next": "http://servidor/api/v1/recurso/?page=2",
    "previous": null
  },
  "results": []
}
```

## Registro

`POST /api/v1/auth/register/` acepta `email`, `first_name`, `last_name`, `phone`,
`password` y `password_confirm`. El rol enviado por un cliente se ignora: todo
registro público recibe `residente`. La creación de `Person` y `User` es
atómica; un conflicto no deja personas huérfanas.

La web recibe la sesión mediante cookies HttpOnly. Flutter debe enviar
`"client": "mobile"` al iniciar o renovar sesión y recibe el par JWT en el
cuerpo.
