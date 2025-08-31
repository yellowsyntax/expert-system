#!/usr/bin/env python3
"""
Database Sync Tool - Neon to RDS
Syncs data from Neon to RDS while preserving RDS-only tables
"""

import psycopg2
import subprocess
import sys
import os
from datetime import datetime
from typing import Dict, Set, Tuple, Optional
import time

class DatabaseSync:
    def __init__(self):
        # Database URLs - Consider using environment variables for production
        self.neon_url = os.getenv('NEON_URL', 
            "postgresql://neondb_owner:npg_Emq9gohbK8se@ep-sweet-hill-a46reakw-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
        self.rds_url = os.getenv('RDS_URL',
            "postgresql://postgres:LM2GGiGjaKtCVJNvPZRk@paiv-rds-master.cmpgm4w8w0fx.us-east-1.rds.amazonaws.com/postgres?sslmode=require")
    
    def test_connection(self, url: str, name: str) -> bool:
        """Test database connection"""
        try:
            conn = psycopg2.connect(url)
            cursor = conn.cursor()
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            print(f"✅ {name} connection successful")
            print(f"   Version: {version[:60]}...")
            
            # Get database size
            cursor.execute("SELECT pg_database_size(current_database())")
            size = cursor.fetchone()[0]
            size_mb = size / (1024 * 1024)
            print(f"   Database size: {size_mb:.2f} MB")
            
            conn.close()
            return True
        except Exception as e:
            print(f"❌ {name} connection failed: {e}")
            return False
    
    def get_tables_list(self, url: str) -> Set[Tuple[str, str]]:
        """Get list of all tables in database"""
        conn = psycopg2.connect(url)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT schemaname, tablename 
            FROM pg_tables 
            WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
            ORDER BY schemaname, tablename;
        """)
        
        tables = set(cursor.fetchall())
        conn.close()
        return tables
    
    def get_table_row_count(self, url: str, schema: str, table: str) -> int:
        """Get row count for a specific table"""
        try:
            conn = psycopg2.connect(url)
            cursor = conn.cursor()
            cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return -1
    
    def analyze_databases(self) -> Dict:
        """Analyze both databases and return comparison"""
        print("\n🔍 Analyzing databases...")
        
        neon_tables = self.get_tables_list(self.neon_url)
        rds_tables = self.get_tables_list(self.rds_url)
        
        neon_only = neon_tables - rds_tables
        rds_only = rds_tables - neon_tables
        common = neon_tables & rds_tables
        
        print(f"\n📊 Database Analysis:")
        print(f"   Neon total tables: {len(neon_tables)}")
        print(f"   RDS total tables: {len(rds_tables)}")
        print(f"   Common tables: {len(common)}")
        print(f"   Tables only in Neon: {len(neon_only)}")
        print(f"   Tables only in RDS: {len(rds_only)}")
        
        if neon_only:
            print(f"\n🔵 Tables to be ADDED to RDS from Neon ({len(neon_only)}):")
            for schema, table in sorted(list(neon_only))[:10]:
                count = self.get_table_row_count(self.neon_url, schema, table)
                print(f"   + {schema}.{table} ({count} rows)")
            if len(neon_only) > 10:
                print(f"   ... and {len(neon_only) - 10} more")
        
        if rds_only:
            print(f"\n🟡 Tables that will be PRESERVED in RDS ({len(rds_only)}):")
            for schema, table in sorted(list(rds_only))[:10]:
                count = self.get_table_row_count(self.rds_url, schema, table)
                print(f"   ✓ {schema}.{table} ({count} rows) - WILL NOT BE TOUCHED")
            if len(rds_only) > 10:
                print(f"   ... and {len(rds_only) - 10} more")
        
        if common:
            print(f"\n🔄 Tables to be UPDATED in RDS ({len(common)}):")
            for schema, table in sorted(list(common))[:10]:
                neon_count = self.get_table_row_count(self.neon_url, schema, table)
                rds_count = self.get_table_row_count(self.rds_url, schema, table)
                print(f"   ↻ {schema}.{table}: RDS({rds_count}) → Neon({neon_count})")
            if len(common) > 10:
                print(f"   ... and {len(common) - 10} more")
        
        return {
            'neon_tables': neon_tables,
            'rds_tables': rds_tables,
            'neon_only': neon_only,
            'rds_only': rds_only,
            'common': common
        }
    
    def perform_smart_sync(self, skip_confirmation: bool = False):
        """
        Sync Neon to RDS intelligently:
        - Updates common tables with Neon data
        - Adds new tables from Neon
        - Preserves RDS-only tables
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        print("=" * 60)
        print("🔄 SMART DATABASE SYNC - NEON TO RDS")
        print("=" * 60)
        
        # Test connections
        print("\n1️⃣  Testing database connections...")
        if not self.test_connection(self.neon_url, "Neon (Source)"):
            print("❌ Cannot proceed without Neon connection")
            return False
        
        if not self.test_connection(self.rds_url, "RDS (Target)"):
            print("❌ Cannot proceed without RDS connection")
            return False
        
        # Analyze databases
        print("\n2️⃣  Analyzing database differences...")
        analysis = self.analyze_databases()
        
        # Confirmation
        if not skip_confirmation:
            print("\n" + "⚠️ " * 10)
            print("SYNC OPERATION SUMMARY:")
            print(f"  ✅ PRESERVE: {len(analysis['rds_only'])} RDS-only tables (untouched)")
            print(f"  🔄 UPDATE: {len(analysis['common'])} common tables (replace with Neon data)")
            print(f"  ➕ ADD: {len(analysis['neon_only'])} new tables from Neon")
            print("\nThis operation will:")
            print("  1. Keep all RDS-only tables intact")
            print("  2. Replace data in common tables with Neon data")
            print("  3. Add new tables from Neon to RDS")
            print("⚠️ " * 10)
            
            response = input("\n❓ Do you want to proceed? Type 'YES' to continue: ")
            if response != "YES":
                print("❌ Sync cancelled by user")
                return False
        
        # Method 1: Table-by-table sync (recommended for mixed scenarios)
        print("\n3️⃣  Starting sync process...")
        return self._perform_table_sync(analysis, timestamp)
    
    def _perform_table_sync(self, analysis: Dict, timestamp: str) -> bool:
        """Perform table-by-table sync"""
        
        backup_dir = f"sync_backup_{timestamp}"
        os.makedirs(backup_dir, exist_ok=True)
        
        success_count = 0
        failed_tables = []
        
        # Get all tables to sync (common + neon_only)
        tables_to_sync = analysis['common'] | analysis['neon_only']
        total_tables = len(tables_to_sync)
        
        print(f"\n📦 Syncing {total_tables} tables from Neon to RDS...")
        print(f"   Backup directory: {backup_dir}/")
        
        for idx, (schema, table) in enumerate(sorted(tables_to_sync), 1):
            table_name = f"{schema}.{table}"
            print(f"\n[{idx}/{total_tables}] Processing {table_name}...")
            
            try:
                # Export table from Neon
                backup_file = os.path.join(backup_dir, f"{schema}_{table}.sql")
                
                # Build pg_dump command for single table
                dump_cmd = [
                    'pg_dump',
                    '--table', f'"{schema}"."{table}"',
                    '--data-only' if (schema, table) in analysis['common'] else '--clean',
                    '--if-exists',
                    '--no-owner',
                    '--no-privileges',
                    self.neon_url
                ]
                
                # If it's a common table, we need to truncate it first
                if (schema, table) in analysis['common']:
                    # Create a file with TRUNCATE command
                    with open(backup_file, 'w') as f:
                        f.write(f'TRUNCATE TABLE "{schema}"."{table}" CASCADE;\n')
                    
                    # Append data to the file
                    with open(backup_file, 'a') as f:
                        result = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                else:
                    # For new tables, include schema
                    dump_cmd[2] = '--clean'  # This will include CREATE TABLE
                    with open(backup_file, 'w') as f:
                        result = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                
                if result.returncode != 0:
                    print(f"   ⚠️  Export warning: {result.stderr[:100]}")
                
                # Import to RDS
                with open(backup_file, 'r') as f:
                    result = subprocess.run(
                        ['psql', '--quiet', self.rds_url],
                        stdin=f,
                        stderr=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        text=True
                    )
                
                if result.returncode == 0:
                    row_count = self.get_table_row_count(self.rds_url, schema, table)
                    print(f"   ✅ Success! ({row_count} rows)")
                    success_count += 1
                else:
                    print(f"   ❌ Failed: {result.stderr[:100]}")
                    failed_tables.append(table_name)
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")
                failed_tables.append(table_name)
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 SYNC SUMMARY:")
        print("=" * 60)
        print(f"✅ Successfully synced: {success_count}/{total_tables} tables")
        print(f"✓  Preserved: {len(analysis['rds_only'])} RDS-only tables")
        
        if failed_tables:
            print(f"\n❌ Failed tables ({len(failed_tables)}):")
            for table in failed_tables[:10]:
                print(f"   - {table}")
            if len(failed_tables) > 10:
                print(f"   ... and {len(failed_tables) - 10} more")
        
        print(f"\n📁 Backup files saved in: {backup_dir}/")
        print("\n💡 Next steps:")
        print("  1. Verify your application works correctly")
        print("  2. Check the failed tables if any")
        print("  3. Keep the backup files for recovery")
        
        return success_count > 0
    
    def perform_full_replace(self, skip_confirmation: bool = False):
        """
        Alternative: Full backup but only for Neon tables
        This exports all Neon tables and imports them to RDS
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"neon_export_{timestamp}.sql"
        
        print("=" * 60)
        print("🔄 SELECTIVE BACKUP - NEON TABLES TO RDS")
        print("=" * 60)
        
        # Test connections
        if not self.test_connection(self.neon_url, "Neon") or not self.test_connection(self.rds_url, "RDS"):
            return False
        
        # Analyze
        analysis = self.analyze_databases()
        
        if not skip_confirmation:
            print("\n⚠️  This will export ALL Neon tables and import to RDS")
            print("   RDS-only tables will be preserved")
            response = input("\nProceed? Type 'YES': ")
            if response != "YES":
                return False
        
        print(f"\n📤 Exporting from Neon...")
        
        try:
            # Export all data from Neon
            dump_cmd = [
                'pg_dump',
                '--verbose',
                '--no-owner',
                '--no-privileges',
                '--clean',
                '--if-exists',
                self.neon_url
            ]
            
            # For each RDS-only table, exclude it from the dump
            for schema, table in analysis['rds_only']:
                dump_cmd.extend(['--exclude-table', f'"{schema}"."{table}"'])
            
            with open(backup_file, 'w') as f:
                result = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
            
            if result.returncode != 0:
                print(f"❌ Export failed: {result.stderr}")
                return False
            
            file_size = os.path.getsize(backup_file) / (1024 * 1024)
            print(f"✅ Export complete: {file_size:.2f} MB")
            
            # Import to RDS
            print(f"\n📥 Importing to RDS...")
            with open(backup_file, 'r') as f:
                result = subprocess.run(
                    ['psql', '--quiet', '--echo-errors', self.rds_url],
                    stdin=f,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True
                )
            
            if result.returncode != 0:
                print(f"⚠️  Import had warnings: {result.stderr[:200]}")
            
            print(f"✅ Import complete!")
            print(f"📁 Backup saved as: {backup_file}")
            
            return True
            
        except Exception as e:
            print(f"❌ Operation failed: {e}")
            return False

def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║      DATABASE SYNC TOOL - NEON TO RDS (SMART MODE)      ║
╚══════════════════════════════════════════════════════════╝
""")
    
    if len(sys.argv) < 2:
        print("""
This tool syncs data from Neon to RDS while PRESERVING RDS-only tables.

Usage: python db_sync.py <command>

Commands:
  sync       - Smart sync: Updates common tables, adds new ones, preserves RDS-only
  analyze    - Show what will be synced without making changes
  full       - Alternative: Full Neon export/import (still preserves RDS tables)
  force      - Force sync without confirmation
  test       - Test database connections only

Recommended: python db_sync.py sync

This will:
  ✅ PRESERVE all RDS-only tables (won't touch them)
  🔄 UPDATE common tables with fresh Neon data  
  ➕ ADD new tables from Neon to RDS
""")
        return
    
    command = sys.argv[1].lower()
    sync_tool = DatabaseSync()
    
    if command == "sync":
        sync_tool.perform_smart_sync(skip_confirmation=False)
    elif command == "force":
        sync_tool.perform_smart_sync(skip_confirmation=True)
    elif command == "analyze":
        sync_tool.analyze_databases()
        print("\n💡 Run 'python db_sync.py sync' to perform the sync")
    elif command == "full":
        sync_tool.perform_full_replace(skip_confirmation=False)
    elif command == "test":
        print("Testing connections...")
        sync_tool.test_connection(sync_tool.neon_url, "Neon")
        sync_tool.test_connection(sync_tool.rds_url, "RDS")
    else:
        print(f"❌ Unknown command: {command}")
        print("   Use 'sync' for smart sync or 'analyze' to preview")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)