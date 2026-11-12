# Run from spike/:  make producer  |  make consumer  |  make clean
DBT = uv run dbt
FLAGS = --no-version-check --no-send-anonymous-usage-stats --profiles-dir .

.PHONY: producer consumer compile-consumer clean query

producer:
	cd producer && $(DBT) build $(FLAGS)

consumer:
	cd consumer && $(DBT) deps $(FLAGS) && $(DBT) build $(FLAGS)

compile-consumer:
	cd consumer && $(DBT) deps $(FLAGS) && $(DBT) compile $(FLAGS)

clean:
	rm -f warehouse.duckdb warehouse.duckdb.wal
	rm -rf producer/target consumer/target consumer/dbt_packages producer/logs consumer/logs

# Inspect the warehouse:  make query Q="select * from information_schema.tables"
query:
	@uv run python -c "import duckdb,sys; duckdb.connect('warehouse.duckdb', read_only=True).sql(sys.argv[1]).show()" "$(Q)"
