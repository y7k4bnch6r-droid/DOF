.PHONY: install test run mes-pasado radar limpiar

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

# make radar                 -> radar mensual de Pink Doll (menciones y métricas)
radar:
	python3 radar/monitor.py

# make radar-rapido          -> lo mismo, con menos resultados por query
radar-rapido:
	python3 radar/monitor.py --limit 5

limpiar:
	rm -rf .cache .pytest_cache __pycache__ */__pycache__
