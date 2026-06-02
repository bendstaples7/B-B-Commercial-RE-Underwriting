SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'real_estate_analysis'
  AND pid <> pg_backend_pid();
