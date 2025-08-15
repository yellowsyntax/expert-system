import os
from dotenv import load_dotenv
from src.database.neon_connection import (
    test_database_connection, 
    get_database_session_context,
    DatabaseSessionManager,
    create_all_tables
)
from sqlalchemy import text

# Load environment variables
load_dotenv()

def test_basic_connection():
    """Test basic database connectivity"""
    print("Testing database connection...")
    
    if test_database_connection():
        print("✅ Database connection successful!")
        return True
    else:
        print("❌ Database connection failed!")
        return False

def test_session_context():
    """Test session context manager"""
    print("\nTesting session context...")
    
    try:
        with get_database_session_context() as session:
            result = session.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✅ PostgreSQL version: {version}")
        return True
    except Exception as e:
        print(f"❌ Session context failed: {e}")
        return False

def test_session_manager():
    """Test DatabaseSessionManager"""
    print("\nTesting DatabaseSessionManager...")
    
    try:
        with DatabaseSessionManager() as db:
            result = db.session.execute(text("SELECT current_database()"))
            database = result.fetchone()[0]
            print(f"✅ Connected to database: {database}")
        return True
    except Exception as e:
        print(f"❌ DatabaseSessionManager failed: {e}")
        return False

def test_environment_variables():
    """Check if all required environment variables are set"""
    print("\nChecking environment variables...")
    
    required_vars = ["NEON_HOST", "NEON_DATABASE", "NEON_USERNAME", "NEON_PASSWORD"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
        else:
            print(f"✅ {var} is set")
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        return False
    
    return True

def main():
    print("=== NEON DATABASE CONNECTION TEST ===\n")
    
    tests = [
        test_environment_variables,
        test_basic_connection,
        test_session_context,
        test_session_manager
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n=== TEST RESULTS ===")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! Your database connection is working.")
    else:
        print("❌ Some tests failed. Check your configuration.")

if __name__ == "__main__":
    main()