"""Drop-in replacement for subprocess.run() that executes in terminal pods.

This module provides a terminal_run() function that mimics subprocess.run() API
but executes commands in isolated terminal pods via kubectl exec.

Safety guardrails (signature matcher + LLM judge) run automatically unless
the caller passes ``trusted=True`` for known-safe internal operations.
"""

import logging
import os
import re
import shlex
import signal
import subprocess
from typing import Optional, List, Union, Dict
from dataclasses import dataclass

from utils.cloud.cloud_utils import get_user_context
from utils.terminal.terminal_ssh_setup_local import ensure_local_ssh_keys

logger = logging.getLogger(__name__)


@dataclass
class CompletedProcess:
    """Mimics subprocess.CompletedProcess for compatibility."""
    args: Union[str, List[str]]
    returncode: int
    stdout: str
    stderr: str


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a timed-out command and any shell-spawned children."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _decode_communicate_output(value, text: bool) -> str:
    if value is None:
        return ""
    if text and isinstance(value, (bytes, bytearray)):
        return value.decode()
    return value if isinstance(value, str) else str(value)


def _run_local_subprocess(
    args: Union[str, List[str]],
    cmd: Union[str, List[str]],
    *,
    capture_output: bool,
    text: bool,
    shell: bool,
    timeout: int,
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    kwargs: dict,
) -> CompletedProcess:
    use_shell = shell if isinstance(cmd, str) else False
    popen_kwargs = {
        "cwd": cwd,
        "env": env,
        "start_new_session": True,
        "text": text,
    }
    if capture_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE

    safe_kwargs = {
        k: v for k, v in kwargs.items()
        if k not in {"check", "timeout", "capture_output", "text", "shell"}
    }

    proc = subprocess.Popen(cmd, shell=use_shell, **popen_kwargs, **safe_kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return CompletedProcess(
            args=args,
            returncode=proc.returncode,
            stdout=_decode_communicate_output(stdout, text) if capture_output else "",
            stderr=_decode_communicate_output(stderr, text) if capture_output else "",
        )
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        out = _decode_communicate_output(stdout or exc.stdout, text)
        err = _decode_communicate_output(stderr or exc.stderr, text)
        if not err:
            err = f"Command timed out after {timeout} seconds"
        logger.error("Command timed out after %ss: %s", timeout, cmd)
        return CompletedProcess(args=args, returncode=124, stdout=out, stderr=err)


def terminal_run(
    args: Union[str, List[str]],
    *,
    capture_output: bool = False,
    text: bool = False,
    shell: bool = False,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    trusted: bool = False,
    **kwargs
) -> CompletedProcess:
    """
    Drop-in replacement for subprocess.run() that executes in terminal pods.
    
    Compatible with subprocess.run() API. Usage:
        Replace: subprocess.run(...) 
        With:    terminal_run(...)
    
    When ENABLE_POD_ISOLATION=false (local dev), uses subprocess.run() directly.
    When ENABLE_POD_ISOLATION=true (k8s prod), uses terminal pods for isolation.
    
    Args:
        args: Command and arguments (string or list)
        capture_output: If True, capture stdout/stderr
        text: If True, return text instead of bytes
        shell: If True, run command through shell
        timeout: Command timeout in seconds (default: 300)
        cwd: Working directory
        env: Environment variables to set
        trusted: If True, skip safety guardrail checks (for internal infra ops)
        **kwargs: Other subprocess.run() arguments
    
    Returns:
        CompletedProcess with returncode, stdout, stderr
    """
    # --- Safety guardrails ---
    if not trusted:
        blocked = _check_guardrails(args)
        if blocked is not None:
            return blocked
    # Check if pod isolation is enabled (default: true for security)
    # Only explicitly set to "false" for local development
    enable_pod_isolation = os.getenv('ENABLE_POD_ISOLATION', 'true') == 'true'
    
    if not enable_pod_isolation:
        # LOCAL DEV MODE: Use direct subprocess execution
        logger.debug("Pod isolation disabled, using direct subprocess execution")
        
        # Setup SSH keys locally if user context available
        try:
            context = get_user_context()
            if context and context.get('user_id'):
                ensure_local_ssh_keys(context['user_id'])
        except Exception as e:
            logger.warning(f"Failed to setup SSH keys in local dev mode: {e}")
        
        # Convert args to list if needed
        if isinstance(args, str):
            if shell:
                cmd = args
            else:
                cmd = shlex.split(args)
        else:
            cmd = args
        
        try:
            return _run_local_subprocess(
                args,
                cmd,
                capture_output=capture_output,
                text=text,
                shell=shell,
                timeout=timeout or 300,
                cwd=cwd,
                env=env,
                kwargs=kwargs,
            )
        except Exception as e:
            logger.error(f"Subprocess execution failed: {e}")
            return CompletedProcess(
                args=args,
                returncode=127,
                stdout="",
                stderr=str(e)
            )
    
    # K8S PROD MODE: Use terminal pod execution
    logger.debug("Pod isolation enabled, using terminal pod execution")
    
    # Import here to avoid circular dependencies
    from utils.tools.tool_executor import get_tool_executor
    
    # Get user context
    try:
        context = get_user_context()
        user_id = context.get('user_id')
        session_id = context.get('session_id')
    except Exception as e:
        logger.error(f"Failed to get user context: {e}")
        raise RuntimeError(f"Cannot execute command without user context: {e}") from e
    
    # Require user context for terminal pod execution
    if not user_id or not session_id:
        logger.error(f"Missing user context: user_id={user_id}, session_id={session_id}")
        raise RuntimeError("Cannot execute command: user_id and session_id required for terminal pod isolation")
    
    # Convert args to command string
    if isinstance(args, list):
        # Check if this is a bash -c command (common pattern for chaining)
        if len(args) >= 3 and args[0] == "bash" and args[1] == "-c":
            # Preserve the bash -c <script> pattern - don't just join with spaces
            command = f"bash -c {shlex.quote(args[2])}"
        else:
            # Join list into shell command
            command = ' '.join(shlex.quote(str(arg)) for arg in args)
    else:
        command = str(args)
    
    # Get tool executor
    try:
        executor = get_tool_executor()
    except Exception as e:
        logger.error(f"Failed to get tool executor: {e}")
        raise RuntimeError(f"Cannot execute command: tool executor unavailable: {e}") from e
    
    # Setup environment variables if provided
    # Keep the original user command for safe logging (before env exports are prepended)
    loggable_command = command
    if env:
        env_setup_commands = []
        for key, value in env.items():
            # Escape value for shell
            escaped_value = value.replace("'", "'\"'\"'")
            env_setup_commands.append(f"export {key}='{escaped_value}'")

        # Prepend env setup to command
        command = '; '.join(env_setup_commands) + f'; {command}'

    # Redact known sensitive flags from the loggable command
    redacted_command = re.sub(r'(--password\s+)\S+', r'\1[REDACTED]', loggable_command)

    # Execute command in terminal pod
    logger.info(f"Executing command in terminal pod for user {user_id}, session {session_id}: {redacted_command[:100]}")
    try:
        returncode, stdout, stderr = executor.execute_command(
            user_id=user_id,
            session_id=session_id,
            command=command,
            timeout=timeout or 300,
            working_dir=cwd
        )
    except Exception as e:
        logger.error(f"Terminal pod execution failed for user {user_id}, session {session_id}: {e}")
        raise RuntimeError(f"Command execution failed in terminal pod: {e}") from e
    
    # Log execution result
    if returncode != 0:
        logger.warning(f"Command exited with code {returncode} (user={user_id}, session={session_id}): {stderr[:200]}")
    
    # Return subprocess-compatible result
    return CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr
    )


def _check_guardrails(args: Union[str, List[str]]) -> Optional[CompletedProcess]:
    """Run signature check + LLM judge. Returns CompletedProcess if blocked, else None."""
    from utils.security.command_safety import evaluate_command

    cmd = args if isinstance(args, str) else shlex.join(str(a) for a in args)

    # Agent-path short-circuit: command_gate ran the same signature+judge check
    # moments ago for this exact command. Skipping avoids a second LLM call
    # (cheap but not cached) and eliminates the small risk of a divergent
    # verdict on the second run. Direct callers (no contextvar set) still
    # execute the full check and fail closed as before.
    try:
        from utils.auth.command_gate import guardrails_approved_hash
        import hashlib
        approved = guardrails_approved_hash()
        if approved and approved == hashlib.sha256(cmd.encode("utf-8", errors="replace")).hexdigest():
            return None
    except Exception:
        logger.debug("[Guardrails] command_gate bypass unavailable", exc_info=True)

    uid, sid = None, None
    try:
        ctx = get_user_context()
        uid, sid = ctx.get("user_id"), ctx.get("session_id")
    except Exception:
        logger.debug("[Guardrails] user context unavailable; proceeding without it", exc_info=True)

    decision = evaluate_command(cmd, tool="terminal_run", user_id=uid, session_id=sid)
    if not decision.blocked:
        return None
    return CompletedProcess(
        args=args, returncode=126, stdout="",
        stderr=f"Blocked by safety guardrail: {decision.reason}",
    )
