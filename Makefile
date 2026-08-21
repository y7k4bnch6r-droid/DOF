.PHONY: install test run mes-pasado limpiar

install:
	pip install -r requirements-dev.txt

test:
	python -m pytest

# make mes-pasado            -> procesa el mes anterior
mes-pasado:
	python -m dofwatch.cli -v run

# make run MES=2026-07       -> procesa un mes específico
run:
	python -m dofwatch.cli -v run --month $(MES)

# make run-rapido MES=2026-07 -> sólo títulos, sin descargar el texto completo
run-rapido:
	python -m dofwatch.cli -v run --month $(MES) --titles-only

limpiar:
	rm -rf .cache .pytest_cache __pycache__ */__pycache__
