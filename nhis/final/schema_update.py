"""
Database Schema Update Script for NHIS Duplicate Detection
Run this first before starting the production processor
"""

import asyncio
import logging
from neon_db_connection import get_nhis_queries, initialize_database, close_database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def update_claims_schema_for_duplicate_tracking():
    """
    Update claims_v3 table schema to support duplicate detection tracking
    """
    try:
        logger.info("Initializing database connection...")
        await initialize_database()
        queries = await get_nhis_queries()
        
        logger.info("Updating claims_v3 schema for duplicate detection...")
        
        # Add columns for tracking duplicate detection phases
        schema_updates = [
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS duplicate_detection_started_at TIMESTAMP",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS duplicate_detection_completed_at TIMESTAMP",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP", 
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS processing_completed_at TIMESTAMP",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS processed_status VARCHAR(20) DEFAULT 'PENDING'",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS duplicate_count INTEGER DEFAULT 0",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS highest_duplicate_confidence DECIMAL(5,3) DEFAULT 0.000",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS flag_reason JSONB",
            "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS flagged_at TIMESTAMP"
        ]
        
        logger.info("Adding new columns...")
        for i, update in enumerate(schema_updates, 1):
            try:
                await queries.db.execute(update)
                logger.info(f"  [{i}/{len(schema_updates)}] Added column: {update.split('ADD COLUMN IF NOT EXISTS')[1].split()[0] if 'ADD COLUMN' in update else 'processing'}")
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")
        
        # Create indexes for performance
        logger.info("Creating indexes...")
        index_updates = [
            "CREATE INDEX IF NOT EXISTS idx_claims_duplicate_detection_started ON claims_v3(duplicate_detection_started_at)",
            "CREATE INDEX IF NOT EXISTS idx_claims_processed_status ON claims_v3(processed_status)",
            "CREATE INDEX IF NOT EXISTS idx_claims_flag_reason ON claims_v3 USING GIN(flag_reason)",
            "CREATE INDEX IF NOT EXISTS idx_claims_batch_processed_status ON claims_v3(batch_id, processed_status)",
            "CREATE INDEX IF NOT EXISTS idx_claims_duplicate_count ON claims_v3(duplicate_count)"
        ]
        
        for i, index in enumerate(index_updates, 1):
            try:
                await queries.db.execute(index)
                logger.info(f"  [{i}/{len(index_updates)}] Created index: {index.split('idx_claims_')[1].split()[0] if 'idx_claims_' in index else 'processing'}")
            except Exception as e:
                logger.debug(f"Index may already exist: {e}")
        
        # Create duplicate detection log tables
        logger.info("Creating duplicate detection log tables...")
        
        create_main_table = """
        CREATE TABLE IF NOT EXISTS duplicate_detection_log (
            id SERIAL PRIMARY KEY,
            encounter_id VARCHAR(50) NOT NULL,
            detection_timestamp TIMESTAMP NOT NULL,
            flag_status VARCHAR(20) NOT NULL,
            total_duplicates_found INTEGER DEFAULT 0,
            highest_confidence DECIMAL(5,3) DEFAULT 0.000,
            recommendation TEXT,
            detection_details JSONB,
            structured_flag_reason JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_duplicate_log_encounter ON duplicate_detection_log(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_duplicate_log_timestamp ON duplicate_detection_log(detection_timestamp);
        CREATE INDEX IF NOT EXISTS idx_duplicate_log_flag_status ON duplicate_detection_log(flag_status);
        CREATE INDEX IF NOT EXISTS idx_duplicate_log_structured_flag ON duplicate_detection_log USING GIN(structured_flag_reason);
        """
        
        create_matches_table = """
        CREATE TABLE IF NOT EXISTS duplicate_matches_log (
            id SERIAL PRIMARY KEY,
            primary_encounter_id VARCHAR(50) NOT NULL,
            duplicate_encounter_id VARCHAR(50) NOT NULL,
            duplicate_type VARCHAR(50) NOT NULL,
            confidence_score DECIMAL(5,3) NOT NULL,
            matching_fields JSONB,
            differing_fields JSONB,
            detection_timestamp TIMESTAMP NOT NULL,
            match_details JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_duplicate_matches_primary ON duplicate_matches_log(primary_encounter_id);
        CREATE INDEX IF NOT EXISTS idx_duplicate_matches_duplicate ON duplicate_matches_log(duplicate_encounter_id);
        CREATE INDEX IF NOT EXISTS idx_duplicate_matches_type ON duplicate_matches_log(duplicate_type);
        CREATE INDEX IF NOT EXISTS idx_duplicate_matches_confidence ON duplicate_matches_log(confidence_score);
        """
        
        await queries.db.execute(create_main_table)
        logger.info("  Created duplicate_detection_log table with indexes")
        
        await queries.db.execute(create_matches_table)
        logger.info("  Created duplicate_matches_log table with indexes")
                
        logger.info("✅ Claims table schema updated successfully for duplicate detection!")
        logger.info("✅ Duplicate detection log tables created!")
        logger.info("✅ All indexes created for optimal performance!")
        
        # Verify the schema updates
        logger.info("Verifying schema updates...")
        verify_query = """
        SELECT column_name, data_type, is_nullable 
        FROM information_schema.columns 
        WHERE table_name = 'claims_v3' 
        AND column_name IN ('processed_status', 'flag_reason', 'duplicate_count', 'flagged_at')
        ORDER BY column_name
        """
        
        columns = await queries.db.fetch_all(verify_query)
        if columns:
            logger.info("Verified new columns exist:")
            for col in columns:
                logger.info(f"  - {col['column_name']}: {col['data_type']} ({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})")
        else:
            logger.warning("Could not verify columns - but schema update completed")
        
        await close_database()
        logger.info("Database connection closed.")
        
    except Exception as e:
        logger.error(f"Error updating claims schema for duplicate tracking: {e}")
        raise

async def check_schema_status():
    """Check if schema updates are already applied"""
    try:
        await initialize_database()
        queries = await get_nhis_queries()
        
        # Check if duplicate detection columns exist
        check_query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'claims_v3' 
        AND column_name IN ('processed_status', 'flag_reason', 'duplicate_count')
        """
        
        existing_columns = await queries.db.fetch_all(check_query)
        existing_column_names = [row['column_name'] for row in existing_columns]
        
        required_columns = ['processed_status', 'flag_reason', 'duplicate_count']
        missing_columns = [col for col in required_columns if col not in existing_column_names]
        
        if missing_columns:
            logger.info("❌ Schema update REQUIRED")
            logger.info(f"Missing columns: {missing_columns}")
            return False
        else:
            logger.info("✅ Schema already up to date")
            return True
            
    except Exception as e:
        logger.error(f"Error checking schema status: {e}")
        return False
    finally:
        await close_database()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        # Check schema status
        asyncio.run(check_schema_status())
    else:
        # Run schema update
        try:
            asyncio.run(update_claims_schema_for_duplicate_tracking())
            print("\n" + "="*60)
            print("✅ SCHEMA UPDATE COMPLETED SUCCESSFULLY!")
            print("✅ You can now run the production processor")
            print("✅ Command: python production_claims_processor.py")
            print("="*60)
        except Exception as e:
            print(f"\n❌ SCHEMA UPDATE FAILED: {e}")
            print("Please check your database connection and try again.")