# comidas-bot

Bot de Telegram para planificar comidas y cenas de la semana según tu calendario de turnos, y generar la lista de la compra.

## Cómo funciona

Lee el calendario `Turnos` de tu servidor Radicale. Cada día trabajado tiene un evento con el turno codificado como `MT` (7-22), `M` (7-15) o `T` (15-22); los días sin evento se consideran libres. Según el turno, cada comida/cena de ese día exige un plato `tupper` (para llevar) o `rapido` (rápido de preparar), o no exige nada.

Para cada una de las 14 franjas de la semana (comida/cena × 7 días) el bot te ofrece 3 platos candidatos de tu catálogo que cumplan la restricción. Si eliges un plato que no es `fresco` (carne/pescado fresco), te pregunta para cuántos días más quieres repetirlo y rellena esos días automáticamente. Si un plato rinde más días de los que caben en la semana, el sobrante se traspasa a la semana siguiente.

Al terminar, manda la lista de la compra agrupada por tanda de cocina, y la añade también como tarea (con la lista dentro) en tu calendario `Tareas` de Radicale.

El catálogo viene sembrado con 8 recetas de ejemplo (Thermomix, Airfryer y fuego normal) para que no arranques con la lista vacía; bórralas o edítalas con `/borrarplato` / `/editplato` cuando quieras.

## 1. Prerequisitos

- Docker y el plugin `docker compose` instalados en tu servidor casero.
- Tu servidor Radicale ya funcionando y accesible (aquí: `radicale.pollete.duckdns.org`) con el calendario `Turnos`, y un calendario/lista de tareas llamado `Tareas` (o el nombre que pongas en `RADICALE_TASKS_CALENDAR_NAME`) donde el bot pueda crear tareas de tipo VTODO.
- Una cuenta de Telegram.
- Una API key de Gemini (para `/addplatourl`) desde [Google AI Studio](https://aistudio.google.com/apikey). Si no la configuras, el resto del bot funciona igual, solo falla ese comando.

## 2. Crear el bot en Telegram

1. Habla con [@BotFather](https://t.me/BotFather) y ejecuta `/newbot`, sigue las instrucciones.
2. Copia el token que te da en `TELEGRAM_BOT_TOKEN`.

## 3. Obtener tu chat_id

1. Manda cualquier mensaje a tu bot recién creado.
2. Abre en el navegador `https://api.telegram.org/bot<TOKEN>/getUpdates` y busca `result[0].message.chat.id` (o pregúntale a [@userinfobot](https://t.me/userinfobot)).
3. Copia ese número en `TELEGRAM_CHAT_ID`.

## 4. Configurar

```bash
cp .env.example .env
```

Rellena todas las claves de `.env`: token y chat_id de Telegram, URL/usuario/contraseña de Radicale, `GEMINI_API_KEY`, y opcionalmente `WEEKLY_JOB_DAY`/`WEEKLY_JOB_TIME`/`TZ` si quieres cambiar cuándo se dispara la planificación automática (por defecto domingo 20:00, `Europe/Madrid`).

## 5. Arrancar

```bash
docker compose up -d --build
docker compose logs -f
```

Comprueba en los logs que no hay errores de autenticación con Telegram o Radicale al arrancar.

## 6. Verificar el acceso

Manda `/start` al bot desde tu propia cuenta: debería saludarte. Desde cualquier otra cuenta de Telegram, el bot no responde nada — así confirmas que el filtro de `chat_id` único está activo.

## 7. Revisar/ampliar el catálogo

El catálogo arranca con 8 platos de ejemplo. Revísalos con `/listaplatos` y ajústalos a tu gusto:

- `/addplato` — dar de alta un plato a mano
- `/addplatourl <enlace>` — dar de alta un plato a partir de una receta online (usa Gemini para extraer ingredientes y pasos; luego confirmas o ajustas etiquetas/rendimiento)
- `/editplato` — editar un plato existente (nombre, tipo de comida, etiquetas, ingredientes, pasos, método, rendimiento)
- `/listaplatos` — ver el catálogo activo
- `/verplato [nombre o número]` — ver la receta completa (ingredientes y pasos) de un plato; sin argumento te deja elegir de una lista
- `/borrarplato` — dar de baja un plato (baja lógica, no se borra el historial)

Asegúrate de tener al menos algunos platos etiquetados `tupper` y `rapido` (para comida y para cena) — si una franja no tiene ningún plato candidato que cumpla su restricción, el bot no podrá ofrecerte opciones ahí.

## 8. Planificar

- `/planificar` — arranca o continúa la planificación de la semana en curso, en cualquier momento.
- El job automático semanal hace lo mismo sin que tengas que pedirlo (día/hora configurables en `.env`).
- `/estasemana` — muestra lo que llevas planificado esta semana (comida/cena de cada día), esté completo o no.
- `/lista` — vuelve a mandar la lista de la compra de la semana actual.
- `/tarea` — vuelve a crear/actualizar la tarea de la lista de la compra en tu calendario `Tareas` (ya se hace sola al terminar de planificar, esto es solo por si quieres forzarlo).
- `/semana <YYYY-MM-DD>` — consulta una semana pasada por su fecha de inicio (lunes).

## Troubleshooting

- **Inspeccionar la base de datos**: `sqlite3 data/comidas.db` (es una DB de uso personal, la cirugía manual con SQL directo es aceptable si algo se queda atascado).
- **Resetear una semana atascada**: borra a mano las filas de `plan_slots` y `weekly_plans` correspondientes a esa `week_start_date`.
- **Probar la conexión CalDAV** sin pasar por el bot: usa un script suelto de Python con el paquete `caldav` contra `RADICALE_URL`/`RADICALE_USERNAME`/`RADICALE_PASSWORD` para confirmar que lees bien los eventos de `Turnos` antes de depurar el bot en sí.
- **`/addplatourl` falla**: comprueba que `GEMINI_API_KEY` está rellena en `.env` y que el enlace es accesible públicamente (sin login).
- **`/tarea` o la tarea automática fallan**: comprueba que existe en Radicale un calendario/lista de tareas con el nombre exacto de `RADICALE_TASKS_CALENDAR_NAME` (por defecto `Tareas`) y que admite componentes `VTODO`.
