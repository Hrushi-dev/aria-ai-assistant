import os
from dotenv import load_dotenv
load_dotenv()
import memory_store as memory
env_mode = os.getenv('AUTONOMY_MODE', '0')
mem_mode = memory.get_fact('autonomy_mode')
print(f"env: {env_mode}, mem: {mem_mode}")
