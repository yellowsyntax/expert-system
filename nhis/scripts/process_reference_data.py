

import sys
import os
from pathlib import Path

# Add src to Python path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main():
    """Main function to process the CSV file"""
    
    print("=" * 60)
    print("NHIS Expert System - Reference Data Processor")
    print("=" * 60)
    
    # Define file paths
    csv_file = "reference_data/raw/nhis_clinical_inference.csv"
    output_dir = "reference_data"
    
    # Check if CSV file exists
    if not os.path.exists(csv_file):
        print(f"❌ CSV file not found: {csv_file}")
        print("Please make sure your CSV file is in the correct location.")
        return False
    
    print(f"📂 Input CSV: {csv_file}")
    print(f"📂 Output directory: {output_dir}")
    
    try:
        # Import the CSV processor
        from src.reference import process_clinical_inference_csv
        
        # Process the CSV file
        result = process_clinical_inference_csv(csv_file, output_dir)
        
        # Print results
        print("\n" + "=" * 60)
        print("PROCESSING COMPLETE!")
        print("=" * 60)
        
        stats = result['stats']
        print(f"📊 Total records: {stats['total_records']}")
        print(f"✅ Processed: {stats['processed_records']}")
        print(f"❌ Errors: {stats['error_records']}")
        print(f"🏥 Unique ICD-10 codes: {stats['unique_icd10_codes']}")
        print(f"🏷️ Unique G-DRG codes: {stats['unique_gdrg_codes']}")
        print(f"💊 Unique medicines: {stats['unique_medicines']}")
        
        print(f"\n📁 Created files:")
        for file_path in result['files_created']:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            print(f"   - {file_name} ({file_size:,} bytes)")
        
        print("\n✅ Reference data is ready!")
        print("You can now use the expert system with this reference data.")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure all required modules are installed:")
        print("   pip install pandas")
        return False
        
    except Exception as e:
        print(f"❌ Processing failed: {str(e)}")
        return False


if __name__ == "__main__":
    # Process the CSV file
    csv_success = main()
    
    if csv_success:
        print(f"\n🎉 SUCCESS! Reference data system is working!")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED! CSV processing failed")
        sys.exit(1)
EOF