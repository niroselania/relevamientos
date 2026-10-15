# Relevamiento de equipos

App web en español para consultar, buscar, agregar, editar y eliminar equipos. Incluye los datos de inicio del Excel compartido.

## Incluye

- Las cinco pestañas detectadas: Computadoras, Colectora Datos, Tablet, Faltantes y Dadas de baja.
- Búsqueda en todos los nombres de campo y valores, sin distinguir mayúsculas ni acentos.
- Alta, edición, eliminación y exportación CSV por pestaña.
- Persistencia SQLite en el volumen Docker `relevamiento_data`. La autenticación es opcional: si definís `APP_PASSWORD`, se solicitarán credenciales; si la dejás vacía, no se pedirá contraseña.

La pestaña **Dadas de baja** no tenía encabezados; se cargó usando los primeros nueve encabezados de Computadoras, en el orden de los datos originales. En **Tablet** se conservaron los 16 campos y su orden, incluidos encabezados repetidos.

## Subir a GitHub

Subí todo el contenido de esta carpeta a la raíz de un repositorio Git. No subas archivos `.env` ni bases SQLite.

## Desplegar en Portainer

1. Creá un Stack desde Git Repository y configurá URL y rama del repositorio.
2. Usá `compose.yaml` como archivo del stack.
3. `APP_PASSWORD` ahora es opcional. Si la dejás vacía, no se pedirá contraseña. `APP_USER` (por defecto `admin`) y `APP_PORT` (por defecto `8080`) también son opcionales.
4. Desplegá el stack. Abrí `http://IP-DE-TU-SERVIDOR:APP_PORT` (puerto predeterminado 8080).
5. Si estará disponible desde Internet, publicalo detrás de HTTPS en tu proxy inverso.

Portainer construye la imagen con el Dockerfile del repositorio. El volumen `relevamiento_data` conserva los registros al recrear o actualizar el contenedor. Respaldá ese volumen periódicamente desde el host Docker.

Al actualizar los archivos en GitHub, recreá/actualizá el stack desde Portainer. La base existente sigue en el volumen; las modificaciones guardadas en la app no se escriben de vuelta al Excel.

## Inicio local opcional

Requiere Docker Compose:

```powershell
docker compose up --build -d
```

Luego abrí `http://localhost:8080`.
