import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get your DB URL from .env
db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url)

# Tables to export
tables = ["apps", "tracked_users", "events", "sessions", "insights"]

with open("backup.sql", "w") as f:
    with engine.connect() as conn:
        for table in tables:
            print(f"Exporting {table}...")
            result = conn.execute(text(f"SELECT * FROM {table}"))
            for row in result:
                # Basic representation of data to SQL-like format
                f.write(f"INSERT INTO {table} VALUES {row};\n")

print("Done! Check your backup.sql file.")
