"""Run an external engine (Ghidra, ILSpy, Vineflower, JADX...) as a cancellable subprocess.

The process tree is stopped when the job is cancelled or the timeout expires, and the
call only returns once it is really gone: a cancelled job never leaves a JVM running in
the background. Output goes to log files in the job workdir, never to our stdout.
"""
import os
import subprocess
import time
from pathlib import Path

from cytools_core import CyToolError

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _kill_tree(process):
    try:
        import psutil
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=10)
    except Exception:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run(command, *, context=None, cwd=None, env=None, timeout=None, log_name='process',
        on_line=None, stdin_text=None):
    """Run `command`; return (returncode, stdout_text, stderr_text).

    `on_line(text)` receives every stdout line as it arrives (used for progress parsing).
    """
    workdir = Path(context.workdir) if context is not None and context.workdir else None
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
    merged = dict(os.environ)
    if env:
        merged.update({k: str(v) for k, v in env.items() if v is not None})
    if context is not None:
        context.log('Running: ' + ' '.join(str(c) for c in command[:6])
                    + (' ...' if len(command) > 6 else ''))
    try:
        process = subprocess.Popen([str(c) for c in command], cwd=str(cwd) if cwd else None,
                                   env=merged, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        raise CyToolError('MissingDependency', 'Cannot start %s: %s' % (command[0], exc),
                          recoverable=True)
    import threading
    out_lines, err_lines = [], []

    def pump(stream, sink, callback):
        for raw in iter(stream.readline, b''):
            text = raw.decode('utf-8', 'replace').rstrip('\r\n')
            sink.append(text)
            if callback is not None:
                try:
                    callback(text)
                except Exception:
                    pass
        stream.close()

    threads = [threading.Thread(target=pump, args=(process.stdout, out_lines, on_line), daemon=True),
               threading.Thread(target=pump, args=(process.stderr, err_lines, None), daemon=True)]
    for thread in threads:
        thread.start()
    if stdin_text is not None:
        try:
            process.stdin.write(stdin_text.encode('utf-8'))
            process.stdin.close()
        except OSError:
            pass
    started = time.monotonic()
    try:
        while process.poll() is None:
            if context is not None:
                try:
                    context.check()
                except BaseException:
                    _kill_tree(process)
                    raise
            if timeout and time.monotonic() - started > timeout:
                _kill_tree(process)
                raise CyToolError('Timeout', '%s did not finish within %d seconds.'
                                  % (Path(str(command[0])).name, timeout), recoverable=True)
            time.sleep(0.1)
    finally:
        for thread in threads:
            thread.join(timeout=5)
        if workdir is not None:
            try:
                (workdir / (log_name + '.stdout.log')).write_text('\n'.join(out_lines), encoding='utf-8')
                (workdir / (log_name + '.stderr.log')).write_text('\n'.join(err_lines), encoding='utf-8')
            except OSError:
                pass
    return process.returncode, '\n'.join(out_lines), '\n'.join(err_lines)


def tail(text, lines=25):
    return '\n'.join(str(text).splitlines()[-lines:])
