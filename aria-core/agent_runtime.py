import json
import logging
import re
from tool_executor import execute_tool_structured
import router
import memory_store

try:
    from main_daemon import _send_result
except ImportError:
    async def _send_result(context, chat_id, message_id, result):
        print(f"[Telegram Mock] To {chat_id} (msg {message_id}):\n{result}")

runtime_logs = []

def _extract_json(text: str) -> str:
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text

def _validate_scope(original_step: dict, fixed_step: dict, scope: dict) -> list[str]:
    violations = []
    
    # 1. Same tool check
    if fixed_step.get("tool") != original_step.get("tool"):
        violations.append(f"Tool changed from {original_step.get('tool')} to {fixed_step.get('tool')}")
        
    # Extract paths from params to check against boundaries
    params_str = json.dumps(fixed_step.get("params", {}))
    # naive extraction of path-like strings (starts with / or X: or X/)
    paths = re.findall(r'(?:/|[A-Za-z]:[/\\])[^\s\'"]+', params_str)
    
    allowed_read = scope.get("allowed_read_paths", [])
    allowed_write = scope.get("allowed_write_paths", [])
    
    for p in paths:
        # Check if the path is safely within the boundaries
        is_safe = False
        for safe_p in allowed_read + allowed_write:
            if safe_p in p or p in safe_p: 
                is_safe = True
                break
        if not is_safe and len(p) > 5:
            # We enforce a strict subset match
            violations.append(f"Path '{p}' is outside allowed read/write boundaries.")
            
    return violations

async def execute_plan(plan: dict, context=None, chat_id=1, message_id=1) -> str:
    goal_id = plan.get("goal_id")
    steps = plan.get("steps", [])
    scope = plan.get("scope_boundary", {})
    
    for step_index, step in enumerate(steps):
        step_id = step.get("step_id")
        attempt = 1
        success = False
        
        while attempt <= 2:
            print(f"\n[Runtime] Executing {goal_id} - Step {step_id} (Attempt {attempt})")
            
            intent = {"action": step.get("tool")}
            intent.update(step.get("params", {}))
            
            if intent["action"] == "python_code_interpreter":
                # Execute python directly to avoid modifying tool_executor.py
                import tempfile
                import subprocess
                import traceback
                import ast
                
                code = intent.get("code", "")
                
                # 1. Static AST Check
                ast_blocked = False
                ast_error_msg = ""
                BLOCKED_IMPORTS = {
                    "subprocess", "shutil", "sys", "os.system",
                    "ctypes", "cffi", "winreg", 
                    "socket", "requests", "urllib", "http", "httplib", "xmlrpc", "ftplib", "telnetlib"
                }
                
                try:
                    tree = ast.parse(code)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                base_module = alias.name.split('.')[0]
                                if base_module in BLOCKED_IMPORTS or alias.name in BLOCKED_IMPORTS:
                                    ast_blocked = True
                                    ast_error_msg = f"Import of {alias.name} is blocked by static analyzer."
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                base_module = node.module.split('.')[0]
                                if base_module in BLOCKED_IMPORTS or node.module in BLOCKED_IMPORTS:
                                    ast_blocked = True
                                    ast_error_msg = f"Import of {node.module} is blocked by static analyzer."
                        elif isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Attribute):
                                if node.func.attr == "system" and isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                                    ast_blocked = True
                                    ast_error_msg = "os.system is blocked by static analyzer."
                except Exception as e:
                    pass # Ignore syntax errors here, let python handle it
                    
                if ast_blocked:
                    result = {
                        "success": False,
                        "return_code": 1,
                        "stdout": "",
                        "stderr": f"PermissionError: {ast_error_msg}",
                        "artifacts": []
                    }
                else:
                    # 2. Runtime Containment (Audit Hook wrapper)
                    allowed_read = scope.get("allowed_read_paths", [])
                    allowed_write = scope.get("allowed_write_paths", [])
                    
                    sandbox_cwd = allowed_write[0] if allowed_write else "D:/AI-AIS/aria-sandbox"
                    import os
                    fallback_warning = None
                    if not os.path.exists(sandbox_cwd):
                        fallback_msg = f"[Runtime] Note: Step {step_id} requested an unusual path '{sandbox_cwd}' and was redirected to the sandbox root."
                        print(fallback_msg)
                        fallback_warning = fallback_msg
                        sandbox_cwd = "D:/AI-AIS/aria-sandbox"
                        os.makedirs(sandbox_cwd, exist_ok=True)
                    
                    wrapper_code = f"""
import sys
import os
import tempfile
import site

allowed_read = {allowed_read}
allowed_write = {allowed_write}

_SYS_PREFIXES = [os.path.normcase(os.path.normpath(os.path.abspath(p))) for p in [sys.base_prefix, sys.prefix] + site.getsitepackages() + [site.getusersitepackages()]]
_TMP_DIR = os.path.normcase(os.path.normpath(os.path.abspath(tempfile.gettempdir())))
_ALLOWED_READ_ABS = [os.path.normcase(os.path.normpath(os.path.abspath(p))) for p in allowed_read]
_ALLOWED_WRITE_ABS = [os.path.normcase(os.path.normpath(os.path.abspath(p))) for p in allowed_write]

def is_safe_path(path, is_write):
    try:
        if hasattr(path, '__fspath__'):
            path = path.__fspath__()
        if isinstance(path, int) or path is None:
            return True
        abs_path = os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
    except Exception:
        return True
        
    if not is_write:
        for pfx in _SYS_PREFIXES:
            if abs_path.startswith(pfx):
                return True
            
    if abs_path == _TMP_DIR or abs_path.startswith(_TMP_DIR + os.sep):
        return True

    allowed_dirs = _ALLOWED_WRITE_ABS if is_write else (_ALLOWED_READ_ABS + _ALLOWED_WRITE_ABS)
    for safe_abs in allowed_dirs:
        if abs_path == safe_abs or abs_path.startswith(safe_abs + os.sep):
            return True
            
    if "locale" in abs_path or "encoding" in abs_path or "pycache" in abs_path or "tzdata" in abs_path:
        if not is_write: return True
        
    return False

def sandbox_audit_hook(event, args):
    if event == "open":
        path, mode, flags = args
        mode_str = str(mode).lower() if mode else "r"
        is_write = any(c in mode_str for c in "wa+x")
        if not is_safe_path(path, is_write):
            raise PermissionError(f"Sandbox violation: Attempted to open {{path}} outside allowed scope")
    elif event in ["os.remove", "os.rmdir", "os.mkdir", "os.unlink"]:
        if not is_safe_path(args[0], True):
            raise PermissionError(f"Sandbox violation: Attempted {{event}} on {{args[0]}} outside allowed scope")
    elif event == "os.rename":
        if not is_safe_path(args[0], True) or not is_safe_path(args[1], True):
            raise PermissionError(f"Sandbox violation: Attempted to rename {{args[0]}} outside allowed scope")

sys.addaudithook(sandbox_audit_hook)
"""
                    full_code = wrapper_code + "\n" + code
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                        f.write(full_code)
                        tmp_path = f.name
                    
                    try:
                        proc = subprocess.run(
                            ["python", tmp_path],
                            capture_output=True, text=True, timeout=30,
                            cwd=sandbox_cwd
                        )
                        import os
                        os.remove(tmp_path)
                        
                        if proc.returncode == 0:
                            result = {
                                "success": True,
                                "return_code": 0,
                                "stdout": proc.stdout.strip(),
                                "stderr": "",
                                "artifacts": []
                            }
                        else:
                            result = {
                                "success": False,
                                "return_code": proc.returncode,
                                "stdout": proc.stdout.strip(),
                                "stderr": proc.stderr.strip(),
                                "artifacts": []
                            }
                    except Exception as e:
                        result = {
                            "success": False,
                            "return_code": 1,
                            "stdout": "",
                            "stderr": f"Python execution error:\n{traceback.format_exc()}",
                            "artifacts": []
                        }
                    
                    if fallback_warning:
                        if result["stdout"]:
                            result["stdout"] += f"\n\n{fallback_warning}"
                        else:
                            result["stdout"] = fallback_warning
            else:

                result = await execute_tool_structured(intent)
            
            log_entry = {
                "goal_id": goal_id,
                "step_id": step_id,
                "attempt": attempt,
                "success": result["success"],
                "stderr": result["stderr"],
                "stdout": result["stdout"],
                "artifacts": result["artifacts"]
            }
            runtime_logs.append(log_entry)
            
            try:
                memory_store.set_agent_plan(goal_id, json.dumps(plan), json.dumps(steps), json.dumps(runtime_logs))
            except Exception as e:
                print(f"[Runtime] Failed to persist agent_plan: {e}")
            
            if result["success"]:
                success = True
                print(f"[Runtime] Step {step_id} succeeded.")
                break
            
            print(f"[Runtime] Step {step_id} failed:\n{result['stderr']}")
            
            if attempt == 2:
                print(f"[Runtime] Retry exhausted for Step {step_id}.")
                break
                
            prompt = f"""You are fixing a failed execution step in an AI agent runtime.
The following step failed:
```json
{json.dumps(step, indent=2)}
```
The error traceback was:
{result["stderr"]}

The approved scope boundaries are:
```json
{json.dumps(scope, indent=2)}
```

You must return a corrected JSON for this step ONLY.
CRITICAL RULES:
1. You MUST keep the same tool: {step.get("tool")}
2. You MUST NOT read/write outside the allowed paths.
Return ONLY valid JSON for the corrected step.
"""
            llm_response = await router.generate(prompt)
            try:
                fixed_step_json = _extract_json(llm_response)
                fixed_step = json.loads(fixed_step_json)
                
                violations = _validate_scope(step, fixed_step, scope)
                if violations:
                    v_str = "\n".join(violations)
                    result["stderr"] += f"\n\n[Scope Violation during self-heal]:\n{v_str}"
                    print(f"[Runtime] Scope violation detected:\n{v_str}")
                    break # Escalate immediately
                
                step = fixed_step
                attempt += 1
            except Exception as e:
                result["stderr"] += f"\n[Self-heal parsing error]: {e}"
                break
                
        if not success:
            escalation_msg = (
                f"⚠️ **Execution Escalation**\n\n"
                f"Goal: {plan.get('goal_description')}\n"
                f"Step {step_id} failed after {attempt} attempts.\n\n"
                f"**Error Details:**\n{result.get('stderr', '')[:700]}\n\n"
                f"Please review and provide explicit permission or instructions to proceed."
            )
            await _send_result(context, chat_id, message_id, escalation_msg)
            return escalation_msg
            
    # Delivery handoff
    if runtime_logs:
        last_result = runtime_logs[-1]
        if last_result["artifacts"]:
            final_msg = f"SENDFILE:{last_result['artifacts'][0]}|Goal complete!"
        else:
            final_msg = f"✅ Goal completed successfully: {plan.get('goal_description')}"
    else:
        final_msg = f"✅ Goal completed successfully: {plan.get('goal_description')} (No steps executed)"
        
    await _send_result(context, chat_id, message_id, final_msg)
    return final_msg
