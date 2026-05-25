#!/usr/bin/env bash
set -e

COMPOSE="docker-compose"

usage() {
  echo "Usage: bash run.sh [COMMAND]"
  echo ""
  echo "Commands:"
  echo "  --build              Build images, start all services, apply pending migrations"
  echo "  --migrate [msg]      Generate new migration + copy to host + apply (msg optional)"
  echo "  --api                Follow recruitflow-api logs"
  echo "  --logs               Follow all service logs"
  echo "  --down               Stop and remove containers (keeps volumes)"
  echo "  --reset              Stop and remove containers + volumes (wipes DB)"
  echo "  --restart            Restart recruitflow-api container only"
  echo "  --shell              Open bash shell inside recruitflow-api container"
  echo ""
}

case "$1" in

  --build)
    echo "==> Building and starting services..."
    $COMPOSE up --build -d --remove-orphans

    echo "==> Waiting for recruitflow-api to be ready..."
    sleep 3

    echo "==> Applying pending migrations..."
    $COMPOSE exec recruitflow-api alembic upgrade head

    echo ""
    echo "Done. App running at http://localhost:8000"
    echo "Docs at http://localhost:8000/docs"
    ;;

  --migrate)
    MSG="${2:-auto_$(date +%Y%m%d_%H%M%S)}"

    echo "==> Generating migration: '$MSG'..."
    $COMPOSE exec recruitflow-api alembic revision --autogenerate -m "$MSG"

    echo "==> Copying migration files to host..."
    docker cp recruitflow-api:/app/alembic/versions/. backend/alembic/versions/

    echo "==> Applying migration..."
    $COMPOSE exec recruitflow-api alembic upgrade head

    echo "Done. Migration '$MSG' applied."
    ;;

  --api)
    $COMPOSE logs -f --tail=100 recruitflow-api
    ;;

  --logs)
    $COMPOSE logs -f --tail=100
    ;;

  --down)
    $COMPOSE down --remove-orphans
    ;;

  --reset)
    echo "WARNING: This will wipe the database."
    read -p "Are you sure? (y/N) " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
      $COMPOSE down -v --remove-orphans
      echo "Done. All containers and volumes removed."
    else
      echo "Aborted."
    fi
    ;;

  --restart)
    $COMPOSE restart recruitflow-api
    echo "recruitflow-api restarted."
    ;;

  --shell)
    $COMPOSE exec recruitflow-api bash
    ;;

  *)
    usage
    exit 1
    ;;

esac
