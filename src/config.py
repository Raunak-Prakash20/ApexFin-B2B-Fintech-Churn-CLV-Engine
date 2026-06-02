"""Database connection and environment runtime configuration.

Manages connection pooling for Microsoft Azure SQL Database and handles
automatic local fallback to DuckDB when cloud credentials are not supplied.
"""

import os
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine
import duckdb

# Load environment variables from .env if present
load_dotenv()

# Base project paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
LOCAL_DB_PATH = os.path.join(BASE_DIR, "data", "fintech_warehouse.duckdb")
SQL_DIR = os.path.join(BASE_DIR, "sql")
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Azure SQL Database Configuration (from Environment Variables)
AZURE_SQL_SERVER = os.getenv("AZURE_SQL_SERVER")         # e.g., "fintech-sql-srv.database.windows.net"
AZURE_SQL_DATABASE = os.getenv("AZURE_SQL_DATABASE")     # e.g., "fintech-dw"
AZURE_SQL_USER = os.getenv("AZURE_SQL_USER")             # e.g., "sqladmin"
AZURE_SQL_PASSWORD = os.getenv("AZURE_SQL_PASSWORD")     # e.g., "YourStrongPwd!"
AZURE_SQL_DRIVER = os.getenv("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")

# Check if full Azure SQL credentials are provided
IS_AZURE_CONFIGURED = bool(
    AZURE_SQL_SERVER and AZURE_SQL_DATABASE and AZURE_SQL_USER and AZURE_SQL_PASSWORD
)

def get_database_engine():
    """
    Returns an active SQLAlchemy engine.
    - If Azure SQL environment variables exist, connects to Azure SQL Database.
    - Otherwise, returns a local DuckDB engine for 100% free local development.
    """
    if IS_AZURE_CONFIGURED:
        print(f"[*] Connecting to Microsoft Azure SQL Database: {AZURE_SQL_SERVER}/{AZURE_SQL_DATABASE}...")
        params = urllib.parse.quote_plus(
            f"DRIVER={{{AZURE_SQL_DRIVER}}};"
            f"SERVER={AZURE_SQL_SERVER};"
            f"DATABASE={AZURE_SQL_DATABASE};"
            f"UID={AZURE_SQL_USER};"
            f"PWD={AZURE_SQL_PASSWORD};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        )
        connection_url = f"mssql+pyodbc:///?odbc_connect={params}"
        engine = create_engine(
            connection_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True
        )
        return engine
    else:
        print(f"[*] Azure SQL not configured. Using local zero-cost DuckDB engine at: {LOCAL_DB_PATH}")
        # DuckDB engine via duckdb_engine or direct duckdb connection
        return duckdb.connect(database=LOCAL_DB_PATH, read_only=False)

def get_duckdb_connection():
    """Returns a direct DuckDB connection for high-speed local analytical SQL execution."""
    return duckdb.connect(database=LOCAL_DB_PATH, read_only=False)
