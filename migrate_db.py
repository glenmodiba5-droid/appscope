from sqlalchemy import create_engine, MetaData, Table

# 1. Paste both of your connection strings here
# Make sure they start with postgresql:// (not postgresql+asyncpg://)
RENDER_URL = "postgresql://appscope_db_user:KE9yxXefcHsmD2GW5SMcWMggYNo1mTzX@dpg-d974pgss728c738mot9g-a.frankfurt-postgres.render.com/appscope_db"
SUPABASE_URL = "postgresql://postgres.okjsknbgeptonssazzmr:#Glen2007modiba@aws-0-eu-west-3.pooler.supabase.com:5432/postgres"

print("Connecting to databases...")
render_engine = create_engine(RENDER_URL)
supabase_engine = create_engine(SUPABASE_URL)

# 2. Read the exact structure from Render
print("Reading table structures from Render...")
metadata = MetaData()
metadata.reflect(bind=render_engine)

# 3. Build that exact structure in Supabase
print("Building tables in Supabase...")
metadata.create_all(bind=supabase_engine)

# 4. Copy the data over
with render_engine.connect() as r_conn:
    # Use begin() to automatically commit the transaction in SQLAlchemy 2.0
    with supabase_engine.begin() as s_conn:
        for table_name in metadata.tables:
            table = Table(table_name, metadata, autoload_with=render_engine)

            print(f"Copying data for '{table_name}'...")

            # Fetch all rows from Render
            result = r_conn.execute(table.select()).fetchall()

            if result:
                # Convert rows to a format Supabase can insert
                rows_to_insert = [dict(row._mapping) for row in result]
                # Insert directly into Supabase
                s_conn.execute(table.insert(), rows_to_insert)
                print(f" -> Inserted {len(result)} rows.")
            else:
                print(f" -> Table is empty, skipping data.")

print("Migration complete! Your users are safely in Supabase.")
