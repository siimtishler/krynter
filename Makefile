# TODO: Add formatting for .js, .css and .html also 
format fmt:
	poetry run ruff check backend/ --fix
	poetry run black backend/

# TODO: Add tests for frontend
test:
	poetry run pytest backend/tests -v

integration test-integration:
	KRUNTER_RUN_INTEGRATION=1 poetry run pytest -m integration backend/tests/test_detailplan_golden.py