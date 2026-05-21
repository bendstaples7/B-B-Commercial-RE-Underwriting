web: python backend/run.py
worker: bash -c "cd backend && celery -A celery_worker worker --loglevel=info --pool=solo"
