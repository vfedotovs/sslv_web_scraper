FROM postgres:15
# Copies any *.sql (including init.sql for table creation on fresh volumes,
# or pg_backup_*.sql placed by make setup / restore for data + tables)
COPY *.sql /docker-entrypoint-initdb.d/

