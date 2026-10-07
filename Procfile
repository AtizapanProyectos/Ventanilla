web: python manage.py migrate --noinput && gunicorn core_dif.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
