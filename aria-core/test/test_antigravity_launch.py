import subprocess
import shutil

exe = shutil.which("antigravity")
print("which antigravity:", exe)

if exe:
    try:
        proc = subprocess.Popen([exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(timeout=5)
        print("Success without shell=True!", out.decode())
    except Exception as e:
        print("Failed without shell=True:", e)
else:
    print("shutil.which couldn't find antigravity. Trying 'antigravity' directly.")
    try:
        proc = subprocess.Popen(["antigravity", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate(timeout=5)
        print("Success without shell=True directly!", out.decode())
    except Exception as e:
        print("Failed without shell=True directly:", e)
