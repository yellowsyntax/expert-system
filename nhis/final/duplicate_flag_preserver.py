import asyncio
import json
import logging
from typing import Dict, Optional, Any

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DuplicateFlagPreserver:
    def __init__(self):
        self.queries = None
    
    async def initialize(self):
        await initialize_database()
        self.queries = await get_nhis_queries()
    
    async def close(self):
        await close_database()
    
    async def preserve_batch_duplicate_flags(self, batch_id: str):
        """Preserve duplicate detection flags after batch processing"""
        try:
            # Update claims that were flagged during duplicate detection but now have generic flag_reasons
            query = """
            UPDATE claims_v3 
            SET flag_reasons = CASE 
                WHEN ddl.detection_details IS NOT NULL THEN
                    CASE  
                        WHEN claims_v3.flag_reasons::text LIKE '%duplicate_detection%' THEN claims_v3.flag_reasons
                        ELSE jsonb_build_object(
                            'primary_flag', 'duplicate_detection',
                            'duplicate_detection', ddl.detection_details,
                            'additional_flags', claims_v3.flag_reasons,
                            'note', 'Claim flagged for duplicate detection and other validation issues'
                        )
                    END
                ELSE claims_v3.flag_reasons
                END,
                updated_at = CURRENT_TIMESTAMP
            FROM duplicate_detection_log ddl
            WHERE claims_v3.encounter_id = ddl.encounter_id
            AND claims_v3.batch_id = $1
            AND claims_v3.processed_status = 'flagged'
            AND ddl.flag_status = 'flagged'
            AND ddl.detection_details IS NOT NULL
            """
            
            await self.queries.db.execute(query, batch_id)
            
            # Count what was updated
            count_query = """
            SELECT COUNT(*) as count
            FROM claims_v3 c
            JOIN duplicate_detection_log ddl ON c.encounter_id = ddl.encounter_id
            WHERE c.batch_id = $1
            AND c.processed_status = 'flagged'
            AND ddl.flag_status = 'flagged'
            AND c.flag_reasons::text LIKE '%duplicate_detection%'
            """
            
            count_result = await self.queries.db.fetch_one(count_query, batch_id)
            count = count_result['count'] if count_result else 0
            
            logger.info(f"Preserved duplicate flags for {count} claims in batch {batch_id}")
            return count
            
        except Exception as e:
            logger.error(f"Error preserving duplicate flags for batch {batch_id}: {e}")
            return 0


async def preserve_batch_flags(batch_id: str):
    """Main function to preserve duplicate flags for a batch"""
    preserver = DuplicateFlagPreserver()
    try:
        await preserver.initialize()
        count = await preserver.preserve_batch_duplicate_flags(batch_id)
        return count
    finally:
        await preserver.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        batch_id = sys.argv[1]
        asyncio.run(preserve_batch_flags(batch_id))
    else:
        print("Usage: python duplicate_flag_preserver.py <batch_id>")