.PHONY: install demo diagnose run test zip

install:
	pip install -r backend/requirements.txt

demo:
	python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc

diagnose:
	python -c "from weather_diag.pipeline import diagnose_file; diagnose_file('data/raw/ecmwf_demo.nc', model='ecmwf', run_id='ecmwf_demo')"

run:
	uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q
