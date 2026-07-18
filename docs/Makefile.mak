.PHONY: install test lint run paper scanner dashboard clean format security

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v

lint:
	ruff check .

format:
	ruff format .

run:
	python main.py

paper:
	python run_paper.py

scanner:
	python run_scanner.py

dashboard:
	cd dashboard && npm install && npm run dev

security:
	pip-audit

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +