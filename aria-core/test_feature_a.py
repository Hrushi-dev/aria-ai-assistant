import asyncio
from sim_bot import test_cmd
import os

async def main():
    print("--- Test 1: Create a real file on desktop ---")
    await test_cmd("create a file on my desktop named featureA_test.txt")
    
    # Check if file exists using python
    desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "Desktop")
    if not os.path.exists(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    
    test_file = os.path.join(desktop, "featureA_test.txt")
    print(f"\nChecking if {test_file} exists: {os.path.exists(test_file)}")

    print("\n--- Test 2: Ask about a file that doesn't exist ---")
    await test_cmd("is there a file named definitely_does_not_exist_123 on desktop")

    print("\n--- Test 3: Zip and receive a real file ---")
    await test_cmd("zip the file named featureA_test on desktop")

if __name__ == "__main__":
    asyncio.run(main())
