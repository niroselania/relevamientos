# Relevamiento de equipos

App web en español para consultar, buscar, agregar, editar y eliminar equipos. Incluye los datos de inicio del Excel compartido.

## Incluye

- Las cinco pestañas detectadas: Computadoras, Colectora Datos, Tablet, Faltantes y Dadas de baja.
- Búsqueda en todos los nombres de campo y valores, sin distinguir mayúsculas ni acentos.
- Alta, edición, eliminación y exportación CSV por pestaña.
- Importación masiva de libros `.xlsx`: actualiza coincidencias por número de serie, incorpora registros nuevos y conserva registros del sitio que no aparecen en el archivo.
- Color opcional por fila para distinguir registros sin afectar los demás.
- Persistencia SQLite en el volumen Docker `relevamiento_data`. La autenticación es opcional: si definís `APP_PASSWORD`, se solicitarán credenciales; si la dejás vacía, no se pedirá contraseña.
- Bot de Telegram `sistemarelevamiento_bot`, conectado a la misma base de datos que el sitio y con búsqueda en todas las pestañas y columnas.

La pestaña **Dadas de baja** no tenía encabezados; se cargó usando los primeros nueve encabezados de Computadoras, en el orden de los datos originales. En **Tablet** se conservaron los 16 campos y su orden, incluidos encabezados repetidos.

Para importar una planilla nueva, abrí el sitio y elegí **Importar Excel**. Seleccioná el `.xlsx` actualizado y confirmá. Los registros con una serie coincidente se actualizan; los que no existan se agregan. No se borran registros del sitio. Las pestañas del archivo deben conservar los nombres usados en el relevamiento.

Para marcar una fila, abrila, elegí un color (por ejemplo, **Naranja**) y guardá los cambios. El color queda asociado a esa fila; **Sin color** lo quita. Los otros registros no cambian.

## Subir a GitHub

Subí todo el contenido de esta carpeta a la raíz de un repositorio Git. No subas archivos `.env` ni bases SQLite.

## Desplegar en Portainer

1. Creá un Stack desde Git Repository y configurá URL y rama del repositorio.
2. Usá `compose.yaml` como archivo del stack.
3. `APP_PASSWORD` es opcional. Si la dejás vacía, no se pedirá contraseña. `APP_USER` es opcional (por defecto `admin`). La app publica el puerto `18088` del servidor.
4. Desplegá el stack. Abrí `http://IP-DE-TU-SERVIDOR:18088`.
5. Si estará disponible desde Internet, publicalo detrás de HTTPS en tu proxy inverso.

Portainer construye la imagen con el Dockerfile del repositorio. El volumen `relevamiento_data` conserva los registros al recrear o actualizar el contenedor. Respaldá ese volumen periódicamente desde el host Docker.

Al actualizar los archivos en GitHub, recreá/actualizá el stack desde Portainer. La base existente sigue en el volumen; las modificaciones guardadas en la app no se escriben de vuelta al Excel.

## Activar el bot de Telegram

1. En Telegram, abrí `@BotFather`. Creá el bot con `/newbot` o buscá el que ya tenés con `/mybots` y consultá su token. Podés usar `sistemarelevamiento_bot` como nombre de usuario si está disponible.
2. En Portainer, abrí las variables del mismo Stack y agregá `TELEGRAM_BOT_TOKEN` con el token de BotFather. No lo publiques en GitHub.
3. Actualizá/recreá el Stack. Se iniciará el contenedor del bot junto al sitio y compartirá su volumen SQLite.
4. Abrí el bot en Telegram, mandale `/start` y escribí un dato que esté en la planilla, por ejemplo una serie o un nombre. También acepta `/buscar dato`.

El bot busca coincidencias parciales en los valores de cualquier campo y devuelve los registros completos. Consulta la base al recibir cada búsqueda, así que ve las altas y modificaciones guardadas desde el sitio sin recargar archivos. Si querés limitar quién puede usarlo, definí `ALLOWED_CHAT_IDS` en Portainer como una lista de IDs separados por coma; si lo dejás vacío, cualquier persona que encuentre el bot podrá consultarlo.

## Inicio local opcional

Requiere Docker Compose:

```powershell
docker compose up --build -d
```

Luego abrí `http://localhost:18088`.
