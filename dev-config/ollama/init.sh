#!/bin/sh
# Entrypoint for the librarian-ollama container in dev. Starts
# `ollama serve` in the background, waits for the daemon to answer,
# pulls the dev models, then blocks on the daemon — with a signal
# trap so `docker compose down` / Ctrl-C cleanly stops ollama instead
# of letting Docker's 10s grace timer SIGKILL it. (POSIX sh catches
# signals at PID 1 but does not propagate them to backgrounded
# children automatically, so without the trap SIGTERM would wake up
# `wait` while the daemon kept running.)
#
# The model cache lives on a bind mount (/root/.ollama), so each
# `ollama pull` below is a no-op after the first start — it just
# checks the registry for updates and returns. Add a model by adding
# a line.
set -eu

ollama serve &
SERVER_PID=$!

# Forward SIGTERM/SIGINT to the daemon, wait for it to exit cleanly,
# then exit with the daemon's status. `exit` inside the trap prevents
# the script from falling through to the trailing `wait` after the
# signal has been handled.
trap 'kill -TERM "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID"; exit' TERM INT

# Poll until the daemon answers; `ollama list` only succeeds once it's
# bound to the port.
until ollama list > /dev/null 2>&1; do
    sleep 1
done

ollama pull qwen3-embedding:8b

wait "$SERVER_PID"
