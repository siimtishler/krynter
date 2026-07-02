# TODO: Add formatting for .js, .css and .html also 
format fmt:
	poetry run ruff check backend/ --fix
	poetry run black backend/

# TODO: Add tests for frontend
test:
	poetry run pytest backend/tests -v

integration test-integration:
	KRUNTER_RUN_INTEGRATION=1 poetry run pytest -m integration backend/tests/test_detailplan_golden.py

vector-tiles:
	scripts/build_vector_tiles.sh

docker-vector-tiles:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose run --rm --build --no-deps backend scripts/build_vector_tiles.sh
