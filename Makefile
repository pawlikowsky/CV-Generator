.PHONY: test lint format

test:
	pytest . -v

lint:
	ruff check .

format:
	ruff format .
