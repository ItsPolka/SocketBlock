# SocketBlock Live — interfaz gráfica

Dashboard en vivo para tu nodo: minado en tiempo real, cadena de bloques animada, red del salón, ranking de mineros y chat.

- Escribe el contenido del bloque y pulsa **Crear oferta**. Cada usuario puede publicar ofertas.
- Selecciona una oferta pendiente y pulsa **Iniciar salón** para abrir una ronda en toda la red, o **Minar** para hacerlo en tu nodo. **Pausar** detiene tu minero local.
- Al validar el bloque ganador, verás quién ganó y la ronda se detendrá. La cadena completa queda visible desde el génesis. Pulsa un bloque para ver su oferta, minero, hash y nonce.
- El panel muestra el tiempo de la ronda y ejemplos SHA-256 calculados en el navegador a partir de la oferta activa. Python realiza la minería. La dificultad adaptativa tiene una meta de 120 segundos en promedio.
- En **Actividad y chat**, elige **Todo el salón** o selecciona a un usuario conectado para enviarle un mensaje directo.

Componentes `background-paths` y `split-flap-text` de [kokonutui](https://github.com/kokonut-labs/kokonutui) (MIT).

## Cómo funciona

`bridge.py` arranca el nodo con `--json`, lee sus eventos y los manda al navegador (Server-Sent Events). Los botones envían comandos al nodo. Solo escucha en `127.0.0.1`: nadie más en la red puede controlar tu nodo. No necesita paquetes de Python.

## Uso

Requiere Node.js 22.12+ solo para compilar el front una vez:

```sh
cd gui/web
npm install
npm run build
cd ../..
```

Luego, desde la raíz del repo (sin otro nodo usando el puerto 6000 ni la misma `--data-dir`):

```sh
python3 gui/bridge.py --name Ana --advertise 192.168.1.11 --peer 192.168.1.10:6000
```

Abre http://127.0.0.1:8765. Todo lo que va después de `bridge.py` se pasa al nodo (`--workers 4`, `--port`, `--data-dir`, etc.); `--ui-port` cambia el puerto de la página. Ctrl+C cierra la interfaz y el nodo.

Para desarrollo con recarga en caliente: deja corriendo `bridge.py` y usa `npm run dev` dentro de `gui/web`.
